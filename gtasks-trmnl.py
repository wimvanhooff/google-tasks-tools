#!/usr/bin/env python3
"""
Google Tasks Starred Tasks to TRMNL List Sync Tool

Syncs tasks marked with ⭐ emoji or * asterisk from all Google Tasks lists into
a dedicated "TRMNL" list. The TRMNL list acts as a consolidated view of all
starred tasks for display on TRMNL devices.

Note: Google Tasks API doesn't expose native starred status, so this tool
uses ⭐ emoji or * asterisk as markers in task titles or notes.

Starring methods:
- ⭐ emoji at the end of title or notes (e.g., "Important task ⭐")
- * asterisk at the end of title or notes (e.g., "Important task *")
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

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
        self.config_file = config_file
        self.mapping_file = 'gtasks-trmnl-mappings.json'
        self.dry_run = dry_run
        self.config = self._load_config()
        self.mappings = self._load_mappings()
        self.gtasks = self._init_google_tasks()

        if self.dry_run:
            logging.info("DRY-RUN MODE: No changes will be made")

    def _load_config(self) -> Dict:
        """Load configuration from JSON file."""
        if not os.path.exists(self.config_file):
            logging.info(f"Config file not found, creating default: {self.config_file}")
            default_config = {
                "google_credentials_file": "credentials.json",
                "google_token_file": "token.json",
                "sync_settings": {
                    "trmnl_list_name": "TRMNL",
                    "source_lists": [],
                    "sync_interval_minutes": 15
                }
            }
            with open(self.config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
            logging.info(f"Created default config. Please review {self.config_file}")
            return default_config

        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                logging.info(f"Loaded configuration from {self.config_file}")
                return config
        except Exception as e:
            logging.error(f"Failed to load config file: {e}")
            raise

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

    def is_task_starred(self, task: Dict) -> bool:
        """Check if a task is marked with star emoji or asterisk at the end.

        Args:
            task: Task dictionary from Google Tasks API

        Returns:
            True if task has ⭐ or * at the end of title or notes
        """
        title = task.get('title', '')
        notes = task.get('notes', '')

        # Check for star emoji at the end of title or notes
        if title.strip().endswith('⭐') or notes.strip().endswith('⭐'):
            return True

        # Check for asterisk at the end of title or notes (after stripping whitespace)
        if title.strip().endswith('*') or notes.strip().endswith('*'):
            return True

        return False

    def strip_star_emoji(self, text: str) -> str:
        """Remove star emoji and trailing asterisk from text for clean TRMNL display.

        Args:
            text: Original text with potential star emoji or asterisk at the end

        Returns:
            Text with star emoji and trailing asterisk removed, whitespace cleaned
        """
        # Remove star emoji
        text = text.replace('⭐', '')

        # Remove trailing asterisk (and any preceding whitespace)
        text = text.strip()
        if text.endswith('*'):
            text = text[:-1].strip()

        return text

    def get_trmnl_list_id(self) -> Optional[str]:
        """Find the TRMNL list ID.

        Returns:
            TRMNL list ID or None if not found
        """
        trmnl_list_name = self.config['sync_settings'].get('trmnl_list_name', 'TRMNL')
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
            original: Original task with star emoji
            trmnl: Current TRMNL task

        Returns:
            True if TRMNL task should be updated
        """
        # Compare cleaned title
        original_title = self.strip_star_emoji(original.get('title', ''))
        trmnl_title = trmnl.get('title', '')
        if original_title != trmnl_title:
            logging.debug(f"Title changed: '{trmnl_title}' -> '{original_title}'")
            return True

        # Compare notes (also strip star from original)
        original_notes = self.strip_star_emoji(original.get('notes', ''))
        trmnl_notes = trmnl.get('notes', '')
        if original_notes != trmnl_notes:
            logging.debug(f"Notes changed for task '{trmnl_title}'")
            return True

        # Compare due dates
        original_due = original.get('due', '')
        trmnl_due = trmnl.get('due', '')
        if original_due != trmnl_due:
            logging.debug(f"Due date changed for task '{trmnl_title}'")
            return True

        return False

    def create_trmnl_task(self, original_task: Dict, original_list_id: str, trmnl_list_id: str) -> Optional[str]:
        """Create a new task in TRMNL list (duplicate of original without star).

        Args:
            original_task: Original task to duplicate
            original_list_id: Original task's list ID
            trmnl_list_id: TRMNL list ID

        Returns:
            Created task ID or None on failure
        """
        original_id = original_task['id']
        clean_title = self.strip_star_emoji(original_task.get('title', ''))
        clean_notes = self.strip_star_emoji(original_task.get('notes', ''))

        task_body = {
            'title': clean_title,
            'notes': clean_notes
        }

        # Copy due date if present
        if 'due' in original_task:
            task_body['due'] = original_task['due']

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
        clean_title = self.strip_star_emoji(original_task.get('title', ''))
        clean_notes = self.strip_star_emoji(original_task.get('notes', ''))

        task_body = {
            'id': trmnl_task['id'],
            'title': clean_title,
            'notes': clean_notes
        }

        # Copy due date if present
        if 'due' in original_task:
            task_body['due'] = original_task['due']

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

    def get_all_starred_tasks(self) -> Dict[str, List[Dict]]:
        """Scan all source lists for starred tasks.

        Returns:
            Dictionary mapping list_id -> list of starred tasks
        """
        all_lists = self.get_all_task_lists()
        source_lists = self.config['sync_settings'].get('source_lists', [])
        trmnl_list_name = self.config['sync_settings'].get('trmnl_list_name', 'TRMNL')

        # Filter to source lists if configured, exclude TRMNL list
        if source_lists:
            lists_to_scan = [l for l in all_lists
                           if l.get('title') in source_lists
                           and l.get('title') != trmnl_list_name]
            logging.info(f"Scanning {len(lists_to_scan)} configured source list(s)")
        else:
            lists_to_scan = [l for l in all_lists if l.get('title') != trmnl_list_name]
            logging.info(f"Scanning all {len(lists_to_scan)} list(s) (excluding TRMNL)")

        starred_tasks_by_list = {}
        total_starred = 0

        for task_list in lists_to_scan:
            list_id = task_list['id']
            list_title = task_list.get('title', 'Untitled')

            # Get active tasks only (not completed)
            tasks = self.get_tasks_in_list(list_id, include_completed=False)
            starred_tasks = [t for t in tasks if self.is_task_starred(t)]

            if starred_tasks:
                starred_tasks_by_list[list_id] = starred_tasks
                total_starred += len(starred_tasks)
                logging.info(f"  '{list_title}': {len(starred_tasks)} starred task(s)")

        logging.info(f"Total starred tasks found: {total_starred}")
        return starred_tasks_by_list

    def sync_starred_tasks(self):
        """Main sync logic: sync all starred tasks to TRMNL list."""
        logging.info("Starting starred tasks sync...")

        # Get TRMNL list ID
        trmnl_list_id = self.get_trmnl_list_id()
        if not trmnl_list_id:
            logging.error("Cannot proceed without TRMNL list")
            return

        # Get all starred tasks
        starred_tasks_by_list = self.get_all_starred_tasks()

        # Track which original task IDs we've seen (to detect deletions later)
        seen_original_ids = set()

        # Process each starred task
        created_count = 0
        updated_count = 0

        for list_id, starred_tasks in starred_tasks_by_list.items():
            for task in starred_tasks:
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
        """Remove TRMNL tasks whose originals are gone/un-starred/completed.

        Args:
            trmnl_list_id: TRMNL list ID
            valid_original_ids: Set of original task IDs that still exist and are starred
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

                # Delete if original is no longer valid (un-starred, deleted, or completed)
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
        self.sync_starred_tasks()

    def run_daemon(self, interval_minutes: Optional[int] = None):
        """Run continuously, syncing at regular intervals.

        Args:
            interval_minutes: Override configured interval
        """
        if interval_minutes is None:
            interval_minutes = self.config['sync_settings'].get('sync_interval_minutes', 15)

        interval_seconds = interval_minutes * 60
        logging.info(f"Starting daemon mode (interval: {interval_minutes} minutes)")

        while True:
            try:
                self.sync_starred_tasks()
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
        description='Google Tasks Starred Tasks to TRMNL List Sync - '
                    'Syncs tasks marked with ⭐ emoji to TRMNL display list'
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
