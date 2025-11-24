#!/usr/bin/env python3
"""
Google Tasks Recurring Task Manager

Monitors completed Google Tasks for '!every X days' directives and automatically
recreates them with updated due dates, implementing repeat-after-completion functionality.
"""

import argparse
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


# Logging configuration
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


class RecurringTaskManager:
    """Manages recurring tasks in Google Tasks based on completion directives."""

    SCOPES = ['https://www.googleapis.com/auth/tasks']
    DIRECTIVE_PATTERN = re.compile(r'every!\s+(\d+)\s+days?', re.IGNORECASE)

    def __init__(self, config_file='gtasks-recurring.conf', dry_run=False):
        """Initialize the recurring task manager.

        Args:
            config_file: Path to the configuration file
            dry_run: If True, only report actions without making changes
        """
        self.config_file = config_file
        self.dry_run = dry_run
        self.config = self._load_config()
        self.gtasks = None
        self._init_google_tasks()

        if self.dry_run:
            logging.info("DRY-RUN MODE: No changes will be made")

    def _load_config(self) -> Dict:
        """Load configuration from JSON file.

        Returns:
            Configuration dictionary
        """
        if not os.path.exists(self.config_file):
            logging.info(f"Config file not found, creating default: {self.config_file}")
            default_config = {
                "google_credentials_file": "credentials.json",
                "google_token_file": "token.json",
                "settings": {
                    "check_interval_minutes": 15,
                    "target_lists": []
                }
            }
            with open(self.config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
            return default_config

        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
                logging.info(f"Loaded configuration from {self.config_file}")
                return config
        except Exception as e:
            logging.error(f"Failed to load config file: {e}")
            raise

    def _init_google_tasks(self):
        """Initialize Google Tasks API with OAuth2 authentication."""
        creds = None
        creds_file = self.config.get('google_credentials_file', 'credentials.json')
        token_file = self.config.get('google_token_file', 'token.json')

        # Load existing token if available
        if os.path.exists(token_file):
            try:
                creds = Credentials.from_authorized_user_file(token_file, self.SCOPES)
            except Exception as e:
                logging.warning(f"Failed to load existing token: {e}")

        # Refresh or obtain new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logging.info("Refreshing expired credentials...")
                creds.refresh(Request())
            else:
                logging.info("No valid credentials, starting OAuth flow...")
                if not os.path.exists(creds_file):
                    logging.error(f"Credentials file not found: {creds_file}")
                    logging.error("Please download OAuth credentials from Google Cloud Console")
                    raise FileNotFoundError(f"Missing credentials file: {creds_file}")

                flow = InstalledAppFlow.from_client_secrets_file(creds_file, self.SCOPES)
                creds = flow.run_local_server(port=0)

            # Save credentials for future use
            with open(token_file, 'w') as token:
                token.write(creds.to_json())
                logging.info(f"Saved credentials to {token_file}")

        self.gtasks = build('tasks', 'v1', credentials=creds)
        logging.info("Google Tasks API initialized successfully")

    def get_all_task_lists(self) -> List[Dict]:
        """Retrieve all task lists from Google Tasks.

        Returns:
            List of task list dictionaries
        """
        try:
            results = self.gtasks.tasklists().list().execute()
            lists = results.get('items', [])
            logging.info(f"Found {len(lists)} task list(s)")
            return lists
        except Exception as e:
            logging.error(f"Failed to retrieve task lists: {e}")
            return []

    def get_completed_tasks(self, list_id: str) -> List[Dict]:
        """Get all completed tasks from a specific list.

        Args:
            list_id: The ID of the task list

        Returns:
            List of completed task dictionaries
        """
        try:
            result = self.gtasks.tasks().list(
                tasklist=list_id,
                showCompleted=True,
                showHidden=True
            ).execute()

            all_tasks = result.get('items', [])
            completed = [t for t in all_tasks if t.get('status') == 'completed']

            return completed
        except Exception as e:
            logging.error(f"Failed to retrieve tasks from list {list_id}: {e}")
            return []

    def parse_directive(self, task: Dict) -> Optional[int]:
        """Parse the '!every X days' directive from task notes.

        Args:
            task: Google Task dictionary

        Returns:
            Number of days, or None if no directive found
        """
        notes = task.get('notes', '')
        match = self.DIRECTIVE_PATTERN.search(notes)

        if match:
            days = int(match.group(1))
            logging.debug(f"Found directive: !every {days} days in task '{task.get('title')}'")
            return days

        return None

    def calculate_new_due_date(self, completed_date: str, days_offset: int) -> str:
        """Calculate new due date based on completion date and offset.

        Args:
            completed_date: ISO format completion timestamp
            days_offset: Number of days to add

        Returns:
            RFC 3339 formatted due date string
        """
        # Parse completion timestamp
        completed_dt = datetime.fromisoformat(completed_date.replace('Z', '+00:00'))

        # Calculate new due date
        new_due_dt = completed_dt + timedelta(days=days_offset)

        # Format as RFC 3339 (Google Tasks format)
        new_due_str = new_due_dt.strftime('%Y-%m-%dT00:00:00.000Z')

        logging.debug(f"Calculated new due date: {new_due_str} (completed: {completed_date}, offset: {days_offset})")
        return new_due_str

    def create_recurring_task(self, original_task: Dict, list_id: str, new_due_date: str) -> bool:
        """Create a new recurring task based on the completed one.

        Args:
            original_task: The completed task dictionary
            list_id: The task list ID
            new_due_date: RFC 3339 formatted due date

        Returns:
            True if successful, False otherwise
        """
        task_body = {
            'title': original_task.get('title', 'Untitled'),
            'notes': original_task.get('notes', ''),
            'due': new_due_date
        }

        if self.dry_run:
            logging.info(f"[DRY-RUN] Would create recurring task: '{task_body['title']}' (due: {new_due_date})")
            return True

        try:
            result = self.gtasks.tasks().insert(
                tasklist=list_id,
                body=task_body
            ).execute()

            logging.info(f"Created recurring task: '{task_body['title']}' (due: {new_due_date})")
            return True
        except Exception as e:
            logging.error(f"Failed to create recurring task: {e}")
            return False

    def delete_task(self, list_id: str, task_id: str, task_title: str = None) -> bool:
        """Delete a task from Google Tasks.

        Args:
            list_id: The task list ID
            task_id: The task ID to delete
            task_title: Optional task title for better logging

        Returns:
            True if successful, False otherwise
        """
        if self.dry_run:
            title_info = f" ('{task_title}')" if task_title else ""
            logging.info(f"[DRY-RUN] Would delete completed task{title_info}")
            return True

        try:
            self.gtasks.tasks().delete(
                tasklist=list_id,
                task=task_id
            ).execute()

            logging.debug(f"Deleted task {task_id}")
            return True
        except Exception as e:
            logging.error(f"Failed to delete task {task_id}: {e}")
            return False

    def process_recurring_tasks(self):
        """Main processing loop: scan for completed tasks and recreate recurring ones."""
        logging.info("Starting recurring task processing...")

        # Get task lists to process
        all_lists = self.get_all_task_lists()
        target_lists = self.config.get('settings', {}).get('target_lists', [])

        # Filter to target lists if specified
        if target_lists:
            lists_to_process = [l for l in all_lists if l.get('title') in target_lists]
            logging.info(f"Processing {len(lists_to_process)} target list(s): {target_lists}")
        else:
            lists_to_process = all_lists
            logging.info(f"Processing all {len(lists_to_process)} list(s)")

        total_processed = 0
        total_created = 0

        for task_list in lists_to_process:
            list_id = task_list['id']
            list_title = task_list.get('title', 'Untitled')

            logging.info(f"Checking list: '{list_title}'")

            completed_tasks = self.get_completed_tasks(list_id)
            logging.info(f"Found {len(completed_tasks)} completed task(s)")

            for task in completed_tasks:
                # Check for recurring directive
                days_offset = self.parse_directive(task)

                if days_offset is None:
                    continue

                total_processed += 1

                # Get completion timestamp
                completed_date = task.get('completed')
                if not completed_date:
                    logging.warning(f"Completed task '{task.get('title')}' has no completion timestamp, skipping")
                    continue

                # Calculate new due date
                new_due_date = self.calculate_new_due_date(completed_date, days_offset)

                # Create new recurring task
                if self.create_recurring_task(task, list_id, new_due_date):
                    total_created += 1
                    # Delete the completed task
                    self.delete_task(list_id, task['id'], task.get('title'))

        logging.info(f"Processing complete. Found {total_processed} recurring task(s), created {total_created} new task(s)")

    def run_once(self):
        """Run a single processing cycle."""
        self.process_recurring_tasks()

    def run_daemon(self, interval_minutes: Optional[int] = None):
        """Run continuously, checking at regular intervals.

        Args:
            interval_minutes: Override config interval (optional)
        """
        if interval_minutes is None:
            interval_minutes = self.config.get('settings', {}).get('check_interval_minutes', 15)

        interval_seconds = interval_minutes * 60

        logging.info(f"Starting daemon mode (check interval: {interval_minutes} minutes)")

        while True:
            try:
                self.process_recurring_tasks()
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
    """Main entry point with argument parsing."""
    parser = argparse.ArgumentParser(
        description='Google Tasks Recurring Task Manager - Implements repeat-after-completion'
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
        default='gtasks-recurring.conf',
        help='Path to configuration file (default: gtasks-recurring.conf)'
    )
    parser.add_argument(
        '--interval',
        type=int,
        help='Override check interval in minutes (daemon mode only)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making any changes'
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(verbose=args.verbose)

    try:
        # Initialize manager
        manager = RecurringTaskManager(config_file=args.config, dry_run=args.dry_run)

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
