#!/usr/bin/env python3
"""
Google Tasks to TRMNL List Sync Tool

Syncs tasks tagged with #trmnl in their description from all Google Tasks lists
into a dedicated "TRMNL" list. The TRMNL list acts as a consolidated view of
tagged tasks for display on TRMNL devices.

Tagging method:
- Add #trmnl anywhere in the task description/notes (e.g., "Remember to do this #trmnl")
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

from confparser import load_config, create_default_config

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Google Tasks API scope
SCOPES = ['https://www.googleapis.com/auth/tasks']


class StdoutFilter(logging.Filter):
    """Filter to allow only INFO and WARNING to stdout."""
    def filter(self, record):
        return record.levelno in (logging.INFO, logging.WARNING)


class StderrFilter(logging.Filter):
    """Filter to allow only ERROR and CRITICAL to stderr."""
    def filter(self, record):
        return record.levelno in (logging.ERROR, logging.CRITICAL)


def setup_logging(verbose=False):
    """Configure dual-stream logging (INFO/WARNING to stdout, ERROR/CRITICAL to stderr)."""
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Stdout handler for INFO and WARNING
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stdout_handler.addFilter(StdoutFilter())
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    # Stderr handler for ERROR and CRITICAL
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.ERROR)
    stderr_handler.addFilter(StderrFilter())
    stderr_handler.setFormatter(formatter)
    logger.addHandler(stderr_handler)


class TRMNLSyncManager:
    """Manages synchronization of starred tasks to TRMNL list."""

    def __init__(self, config_file='gtasks-trmnl.conf', dry_run=False):
        """Initialize the sync manager.

        Args:
            config_file: Path to configuration file
            dry_run: If True, show what would be done without making changes
        """
        # Resolve paths relative to script directory for cron compatibility
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(script_dir, config_file) if not os.path.isabs(config_file) else config_file
        self.mapping_file = os.path.join(script_dir, 'gtasks-trmnl-mappings.json')
        self.dry_run = dry_run
        self.config = self._load_config()
        self.mappings = self._load_mappings()
        self.gtasks = self._init_google_tasks()

        if self.dry_run:
            logging.info("DRY-RUN MODE: No changes will be made")

    def _load_config(self) -> Dict:
        """Load configuration from plain .conf file."""
        default_template = """# Google Tasks to TRMNL List Sync Configuration
# Copy this file to 'gtasks-trmnl.conf' and fill in your details

# Google API credentials - download from Google Cloud Console
# 1. Create a project and enable Google Tasks API
# 2. Create OAuth 2.0 credentials (Desktop application)
# 3. Download as credentials.json
google_credentials_file = credentials.json

# OAuth token file (auto-generated after first successful authentication)
google_token_file = token.json

# Name of the Google Tasks list to sync tagged tasks into
# This list must already exist - create it manually before running the tool
trmnl_list_name = TRMNL

# List names to scan for tagged tasks (comma-separated, empty = scan all lists)
# Example: source_lists = Work, Personal
source_lists =

# How often to sync in daemon mode (minutes)
sync_interval_minutes = 15
"""

        defaults = {
            'google_credentials_file': 'credentials.json',
            'google_token_file': 'token.json',
            'trmnl_list_name': 'TRMNL',
            'source_lists': [],
            'sync_interval_minutes': 15
        }

        if not os.path.exists(self.config_file):
            logging.info(f"Config file not found, creating default: {self.config_file}")
            create_default_config(self.config_file, default_template)
            logging.info(f"Created default config. Please review {self.config_file}")

        config = load_config(self.config_file, defaults)
        logging.info(f"Loaded configuration from {self.config_file}")

        # Handle source_lists as string (if not parsed as list)
        if isinstance(config.get('source_lists'), str):
            source_lists = config['source_lists']
            if source_lists:
                config['source_lists'] = [lst.strip() for lst in source_lists.split(',') if lst.strip()]
            else:
                config['source_lists'] = []

        # Resolve credential paths relative to script directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for key in ('google_credentials_file', 'google_token_file'):
            if config.get(key) and not os.path.isabs(config[key]):
                config[key] = os.path.join(script_dir, config[key])

        return config

    def _load_mappings(self) -> Dict:
        """Load task ID mappings from file."""
        if os.path.exists(self.mapping_file):
            try:
                with open(self.mapping_file, 'r') as f:
                    mappings = json.load(f)
                    logging.info(f"Loaded mappings from {self.mapping_file}")
                    return mappings
            except Exception as e:
                logging.error(f"Failed to load mappings file: {e}")
                return self._create_empty_mappings()
        else:
            logging.info("No existing mappings file, starting fresh")
            return self._create_empty_mappings()

    def _create_empty_mappings(self) -> Dict:
        """Create empty mappings structure."""
        return {
            "original_to_trmnl": {},
            "trmnl_to_original": {},
            "last_sync": None
        }

    def _save_mappings(self):
        """Save task ID mappings to file."""
        if self.dry_run:
            logging.info(f"[DRY-RUN] Would save mappings to {self.mapping_file}")
            return

        try:
            self.mappings["last_sync"] = datetime.now(timezone.utc).isoformat()
            with open(self.mapping_file, 'w') as f:
                json.dump(self.mappings, f, indent=2)
            logging.info(f"Saved mappings to {self.mapping_file}")
        except Exception as e:
            logging.error(f"Failed to save mappings: {e}")

    def _init_google_tasks(self):
        """Initialize Google Tasks API client."""
        creds = None
        token_file = self.config.get('google_token_file', 'token.json')
        creds_file = self.config.get('google_credentials_file', 'credentials.json')

        # Load existing credentials
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)

        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logging.info("Refreshing expired Google credentials")
                creds.refresh(Request())
            else:
                if not os.path.exists(creds_file):
                    raise FileNotFoundError(
                        f"Google credentials file not found: {creds_file}\n"
                        "Please download from Google Cloud Console."
                    )

                logging.info("Starting OAuth flow for Google Tasks")
                flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
                creds = flow.run_local_server(port=0)

            # Save credentials
            with open(token_file, 'w') as token:
                token.write(creds.to_json())
            logging.info(f"Saved credentials to {token_file}")

        return build('tasks', 'v1', credentials=creds)

    def get_all_task_lists(self) -> List[Dict]:
        """Retrieve all task lists from Google Tasks."""
        try:
            results = self.gtasks.tasklists().list().execute()
            lists = results.get('items', [])
            logging.info(f"Found {len(lists)} task list(s)")
            return lists
        except Exception as e:
            logging.error(f"Failed to retrieve task lists: {e}")
            return []

    def get_tasks_in_list(self, list_id: str, include_completed: bool = False) -> List[Dict]:
        """Get tasks from a specific list.

        Args:
            list_id: The task list ID
            include_completed: Whether to include completed tasks

        Returns:
            List of task dictionaries
        """
        try:
            result = self.gtasks.tasks().list(
                tasklist=list_id,
                showCompleted=include_completed,
                showHidden=include_completed
            ).execute()
            return result.get('items', [])
        except Exception as e:
            logging.error(f"Failed to retrieve tasks from list {list_id}: {e}")
            return []

    def is_task_tagged(self, task: Dict) -> bool:
        """Check if a task is tagged with #trmnl in its description.

        Args:
            task: Task dictionary from Google Tasks API

        Returns:
            True if task has #trmnl tag in notes (case-insensitive)
        """
        notes = task.get('notes', '')

        # Check for #trmnl tag (case-insensitive)
        return '#trmnl' in notes.lower()

    def strip_trmnl_tag(self, text: str) -> str:
        """Remove #trmnl tag from text for clean TRMNL display.

        Args:
            text: Original text with potential #trmnl tag

        Returns:
            Text with #trmnl tag removed, whitespace cleaned
        """
        # Remove #trmnl tag (case-insensitive) and clean up whitespace
        text = re.sub(r'#trmnl\b', '', text, flags=re.IGNORECASE)
        # Clean up any double spaces or leading/trailing whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def get_trmnl_list_id(self) -> Optional[str]:
        """Find the TRMNL list ID.

        Returns:
            TRMNL list ID or None if not found
        """
        trmnl_list_name = self.config.get('trmnl_list_name', 'TRMNL')
        all_lists = self.get_all_task_lists()

        for task_list in all_lists:
            if task_list.get('title') == trmnl_list_name:
                list_id = task_list['id']
                logging.info(f"Found TRMNL list: '{trmnl_list_name}' (ID: {list_id})")
                return list_id

        logging.error(f"TRMNL list '{trmnl_list_name}' not found. Please create it first.")
        return None

    def task_needs_update(self, original: Dict, trmnl: Dict) -> bool:
        """Check if TRMNL task needs to be updated based on original.

        Args:
            original: Original task with #trmnl tag
            trmnl: Current TRMNL task

        Returns:
            True if TRMNL task should be updated
        """
        # Compare title (title is not modified)
        original_title = original.get('title', '')
        trmnl_title = trmnl.get('title', '')
        if original_title != trmnl_title:
            logging.debug(f"Title changed: '{trmnl_title}' -> '{original_title}'")
            return True

        # Compare notes (strip #trmnl tag from original for comparison)
        original_notes = self.strip_trmnl_tag(original.get('notes', ''))
        trmnl_notes = trmnl.get('notes', '')
        if original_notes != trmnl_notes:
            logging.debug(f"Notes changed for task '{trmnl_title}'")
            return True

        # Note: Due dates are intentionally NOT compared since we don't sync them
        # to TRMNL list (to avoid duplicate calendar entries)

        return False

    def create_trmnl_task(self, original_task: Dict, original_list_id: str, trmnl_list_id: str) -> Optional[str]:
        """Create a new task in TRMNL list (duplicate of original without #trmnl tag).

        Args:
            original_task: Original task to duplicate
            original_list_id: Original task's list ID
            trmnl_list_id: TRMNL list ID

        Returns:
            Created task ID or None on failure
        """
        original_id = original_task['id']
        clean_title = original_task.get('title', '')
        clean_notes = self.strip_trmnl_tag(original_task.get('notes', ''))

        task_body = {
            'title': clean_title,
            'notes': clean_notes
        }

        # Note: Due dates are intentionally NOT synced to TRMNL list
        # to avoid duplicate calendar entries

        if self.dry_run:
            logging.info(f"[DRY-RUN] Would create TRMNL task: '{clean_title}'")
            return f"dry_run_{original_id}"

        try:
            created_task = self.gtasks.tasks().insert(
                tasklist=trmnl_list_id,
                body=task_body
            ).execute()

            trmnl_id = created_task['id']
            logging.info(f"Created TRMNL task: '{clean_title}' (ID: {trmnl_id})")

            # Update mappings
            self.mappings['original_to_trmnl'][original_id] = trmnl_id
            self.mappings['trmnl_to_original'][trmnl_id] = original_id

            return trmnl_id
        except Exception as e:
            logging.error(f"Failed to create TRMNL task '{clean_title}': {e}")
            return None

    def update_trmnl_task(self, original_task: Dict, trmnl_task: Dict, trmnl_list_id: str) -> bool:
        """Update existing TRMNL task with changes from original.

        Args:
            original_task: Original task with updates
            trmnl_task: Current TRMNL task to update
            trmnl_list_id: TRMNL list ID

        Returns:
            True if update successful
        """
        clean_title = original_task.get('title', '')
        clean_notes = self.strip_trmnl_tag(original_task.get('notes', ''))

        task_body = {
            'id': trmnl_task['id'],
            'title': clean_title,
            'notes': clean_notes
        }

        # Note: Due dates are intentionally NOT synced to TRMNL list
        # to avoid duplicate calendar entries

        if self.dry_run:
            logging.info(f"[DRY-RUN] Would update TRMNL task: '{clean_title}'")
            return True

        try:
            self.gtasks.tasks().update(
                tasklist=trmnl_list_id,
                task=trmnl_task['id'],
                body=task_body
            ).execute()

            logging.info(f"Updated TRMNL task: '{clean_title}'")
            return True
        except Exception as e:
            logging.error(f"Failed to update TRMNL task '{clean_title}': {e}")
            return False

    def delete_trmnl_task(self, trmnl_task_id: str, trmnl_list_id: str):
        """Delete a task from TRMNL list and clean up mappings.

        Args:
            trmnl_task_id: TRMNL task ID to delete
            trmnl_list_id: TRMNL list ID
        """
        if self.dry_run:
            logging.info(f"[DRY-RUN] Would delete TRMNL task ID: {trmnl_task_id}")
            return

        try:
            self.gtasks.tasks().delete(
                tasklist=trmnl_list_id,
                task=trmnl_task_id
            ).execute()

            logging.info(f"Deleted TRMNL task ID: {trmnl_task_id}")

            # Clean up mappings
            original_id = self.mappings['trmnl_to_original'].pop(trmnl_task_id, None)
            if original_id:
                self.mappings['original_to_trmnl'].pop(original_id, None)
        except Exception as e:
            logging.error(f"Failed to delete TRMNL task {trmnl_task_id}: {e}")

    def get_all_tagged_tasks(self) -> Dict[str, List[Dict]]:
        """Scan all source lists for tasks tagged with #trmnl.

        Returns:
            Dictionary mapping list_id -> list of tagged tasks
        """
        all_lists = self.get_all_task_lists()
        source_lists = self.config.get('source_lists', [])
        trmnl_list_name = self.config.get('trmnl_list_name', 'TRMNL')

        # Filter to source lists if configured, exclude TRMNL list
        if source_lists:
            lists_to_scan = [l for l in all_lists
                           if l.get('title') in source_lists
                           and l.get('title') != trmnl_list_name]
            logging.info(f"Scanning {len(lists_to_scan)} configured source list(s)")
        else:
            lists_to_scan = [l for l in all_lists if l.get('title') != trmnl_list_name]
            logging.info(f"Scanning all {len(lists_to_scan)} list(s) (excluding TRMNL)")

        tagged_tasks_by_list = {}
        total_tagged = 0

        for task_list in lists_to_scan:
            list_id = task_list['id']
            list_title = task_list.get('title', 'Untitled')

            # Get active tasks only (not completed)
            tasks = self.get_tasks_in_list(list_id, include_completed=False)
            tagged_tasks = [t for t in tasks if self.is_task_tagged(t)]

            if tagged_tasks:
                tagged_tasks_by_list[list_id] = tagged_tasks
                total_tagged += len(tagged_tasks)
                logging.info(f"  '{list_title}': {len(tagged_tasks)} tagged task(s)")

        logging.info(f"Total tagged tasks found: {total_tagged}")
        return tagged_tasks_by_list

    def sync_tagged_tasks(self):
        """Main sync logic: sync all #trmnl tagged tasks to TRMNL list."""
        logging.info("Starting tagged tasks sync...")

        # Get TRMNL list ID
        trmnl_list_id = self.get_trmnl_list_id()
        if not trmnl_list_id:
            logging.error("Cannot proceed without TRMNL list")
            return

        # Get all tagged tasks
        tagged_tasks_by_list = self.get_all_tagged_tasks()

        # Track which original task IDs we've seen (to detect deletions later)
        seen_original_ids = set()

        # Process each tagged task
        created_count = 0
        updated_count = 0

        for list_id, tagged_tasks in tagged_tasks_by_list.items():
            for task in tagged_tasks:
                original_id = task['id']
                seen_original_ids.add(original_id)

                # Check if already mapped
                if original_id in self.mappings['original_to_trmnl']:
                    trmnl_id = self.mappings['original_to_trmnl'][original_id]

                    # Get current TRMNL task to check for updates
                    try:
                        trmnl_task = self.gtasks.tasks().get(
                            tasklist=trmnl_list_id,
                            task=trmnl_id
                        ).execute()

                        # Update if needed
                        if self.task_needs_update(task, trmnl_task):
                            if self.update_trmnl_task(task, trmnl_task, trmnl_list_id):
                                updated_count += 1
                        else:
                            logging.debug(f"No changes for: '{task.get('title', '')}'")

                    except Exception as e:
                        # TRMNL task no longer exists, recreate it
                        logging.warning(f"TRMNL task {trmnl_id} not found, recreating: {e}")
                        if self.create_trmnl_task(task, list_id, trmnl_list_id):
                            created_count += 1
                else:
                    # Create new TRMNL task
                    if self.create_trmnl_task(task, list_id, trmnl_list_id):
                        created_count += 1

        logging.info(f"Sync results: {created_count} created, {updated_count} updated")

        # Cleanup: remove TRMNL tasks whose originals are no longer starred/exist
        self.cleanup_trmnl_tasks(trmnl_list_id, seen_original_ids)

        # Save updated mappings
        self._save_mappings()
        logging.info("Sync complete")

    def cleanup_trmnl_tasks(self, trmnl_list_id: str, valid_original_ids: set):
        """Remove TRMNL tasks whose originals are gone/untagged/completed.

        Args:
            trmnl_list_id: TRMNL list ID
            valid_original_ids: Set of original task IDs that still exist and are tagged
        """
        logging.info("Cleaning up stale TRMNL tasks...")

        # Get all current TRMNL tasks
        trmnl_tasks = self.get_tasks_in_list(trmnl_list_id, include_completed=True)

        deleted_count = 0

        for trmnl_task in trmnl_tasks:
            trmnl_id = trmnl_task['id']

            # Check if this TRMNL task is mapped to an original
            if trmnl_id in self.mappings['trmnl_to_original']:
                original_id = self.mappings['trmnl_to_original'][trmnl_id]

                # Delete if original is no longer valid (untagged, deleted, or completed)
                if original_id not in valid_original_ids:
                    logging.info(f"Original task no longer valid, deleting: '{trmnl_task.get('title', '')}'")
                    self.delete_trmnl_task(trmnl_id, trmnl_list_id)
                    deleted_count += 1

            # Also delete if task is completed in TRMNL
            elif trmnl_task.get('status') == 'completed':
                logging.info(f"TRMNL task completed, deleting: '{trmnl_task.get('title', '')}'")
                self.delete_trmnl_task(trmnl_id, trmnl_list_id)
                deleted_count += 1

        if deleted_count > 0:
            logging.info(f"Cleaned up {deleted_count} stale TRMNL task(s)")
        else:
            logging.info("No cleanup needed")

    def run_once(self):
        """Run a single sync cycle."""
        self.sync_tagged_tasks()

    def run_daemon(self, interval_minutes: Optional[int] = None):
        """Run continuously, syncing at regular intervals.

        Args:
            interval_minutes: Override configured interval
        """
        if interval_minutes is None:
            interval_minutes = self.config.get('sync_interval_minutes', 15)

        interval_seconds = interval_minutes * 60
        logging.info(f"Starting daemon mode (interval: {interval_minutes} minutes)")

        while True:
            try:
                self.sync_tagged_tasks()
                logging.info(f"Sleeping for {interval_minutes} minutes...")
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                logging.info("Daemon mode interrupted by user")
                break
            except Exception as e:
                logging.error(f"Error in daemon loop: {e}")
                logging.info(f"Continuing... next check in {interval_minutes} minutes")
                time.sleep(interval_seconds)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Google Tasks to TRMNL List Sync - '
                    'Syncs tasks tagged with #trmnl in description to TRMNL display list'
    )
    parser.add_argument(
        '--daemon',
        action='store_true',
        help='Run continuously at regular intervals (default: run once and exit)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--config',
        default='gtasks-trmnl.conf',
        help='Path to configuration file (default: gtasks-trmnl.conf)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making any changes'
    )
    parser.add_argument(
        '--interval',
        type=int,
        help='Override sync interval in minutes (daemon mode only)'
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose)

    try:
        # Initialize manager
        manager = TRMNLSyncManager(
            config_file=args.config,
            dry_run=args.dry_run
        )

        # Run in selected mode
        if args.daemon:
            manager.run_daemon(interval_minutes=args.interval)
        else:
            manager.run_once()

    except KeyboardInterrupt:
        logging.info("Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
