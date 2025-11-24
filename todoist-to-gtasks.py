#!/usr/bin/env python3
"""
Todoist to Google Tasks One-Way Sync Tool

This program syncs all tasks from Todoist projects to Google Tasks lists.
Projects in Todoist map to lists in Google Tasks (one-to-one).
Recurring tasks are converted to gtasks-recurring.py compatible format.

Requirements:
- pip install todoist-api-python google-api-python-client google-auth-oauthlib google-auth-httplib2

Setup:
1. Get Todoist API token from https://todoist.com/prefs/integrations
2. Set up Google Tasks API credentials (OAuth2)
3. Configure sync settings in project_sync_config.json
"""

import json
import os
import logging
import sys
import re
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
import time

# Third-party imports
from todoist_api_python.api import TodoistAPI
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Configure logging with custom handlers
class StdoutHandler(logging.StreamHandler):
    """Handler that only processes INFO and WARNING messages to stdout."""
    def __init__(self):
        super().__init__(sys.stdout)

    def emit(self, record):
        if record.levelno in (logging.INFO, logging.WARNING):
            super().emit(record)

class StderrHandler(logging.StreamHandler):
    """Handler that only processes ERROR and CRITICAL messages to stderr."""
    def __init__(self):
        super().__init__(sys.stderr)

    def emit(self, record):
        if record.levelno >= logging.ERROR:
            super().emit(record)

# Set up logger with custom handlers
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create formatters
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# Create and configure handlers
stdout_handler = StdoutHandler()
stdout_handler.setFormatter(formatter)

stderr_handler = StderrHandler()
stderr_handler.setFormatter(formatter)

# Add handlers to logger
logger.addHandler(stdout_handler)
logger.addHandler(stderr_handler)

# Prevent duplicate messages from root logger
logger.propagate = False


class ProjectSyncManager:
    """Manages one-way synchronization from Todoist projects to Google Tasks lists."""

    def __init__(self, config_file: str = "todoist-to-gtasks.conf", verbose: bool = False, dry_run: bool = False, limit: Optional[int] = None):
        self.config_file = config_file
        self.mapping_file = "todoist-to-gtasks-mappings.json"
        self.verbose = verbose
        self.dry_run = dry_run
        self.limit = limit
        self.load_config()
        self.load_mappings()

        # Initialize APIs
        self.todoist = TodoistAPI(self.config['todoist_token'])
        self.gtasks = self._init_google_tasks()

        if self.dry_run:
            logger.info("DRY-RUN MODE: No changes will be made")
        if self.limit:
            logger.info(f"LIMIT MODE: Maximum {self.limit} tasks will be synced")

    def load_config(self):
        """Load configuration from file or create default."""
        default_config = {
            "todoist_token": "",
            "google_credentials_file": "credentials.json",
            "google_token_file": "token.json",
            "sync_settings": {
                "excluded_projects": [],
                "sync_interval_minutes": 15,
                "inbox_list_name": "Todoist Inbox"
            }
        }

        if os.path.exists(self.config_file):
            with open(self.config_file, 'r') as f:
                self.config = json.load(f)
        else:
            self.config = default_config
            self.save_config()
            logger.warning(f"Created default config file: {self.config_file}")
            logger.warning("Please update with your API credentials!")

    def save_config(self):
        """Save configuration to file."""
        with open(self.config_file, 'w') as f:
            json.dump(self.config, f, indent=2)

    def load_mappings(self):
        """Load task and project/list ID mappings."""
        if os.path.exists(self.mapping_file):
            with open(self.mapping_file, 'r') as f:
                self.mappings = json.load(f)
        else:
            self.mappings = {
                "project_to_list": {},      # todoist_project_id -> gtasks_list_id
                "todoist_to_gtasks": {},    # todoist_task_id -> gtasks_task_id
                "gtasks_to_todoist": {},    # gtasks_task_id -> todoist_task_id
                "last_sync": None
            }

    def save_mappings(self):
        """Save mappings to file."""
        self.mappings["last_sync"] = datetime.now(timezone.utc).isoformat()
        with open(self.mapping_file, 'w') as f:
            json.dump(self.mappings, f, indent=2)

    def _init_google_tasks(self):
        """Initialize Google Tasks API client."""
        SCOPES = ['https://www.googleapis.com/auth/tasks']

        creds = None
        token_file = self.config['google_token_file']

        # Load existing credentials
        if os.path.exists(token_file):
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)

        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.config['google_credentials_file']):
                    raise FileNotFoundError(
                        f"Google credentials file not found: {self.config['google_credentials_file']}\n"
                        "Please download from Google Cloud Console."
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    self.config['google_credentials_file'], SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save credentials
            with open(token_file, 'w') as token:
                token.write(creds.to_json())

        return build('tasks', 'v1', credentials=creds)

    def get_todoist_projects(self) -> List:
        """Get all Todoist projects including inbox."""
        try:
            # get_projects() returns a paginator that yields lists of projects
            projects_paginator = self.todoist.get_projects()

            # Collect all projects from paginator
            projects = []
            for page in projects_paginator:
                projects.extend(page)

            # Add special "Inbox" project (represented by project_id=None in tasks)
            inbox_project = type('obj', (object,), {
                'id': 'inbox',
                'name': self.config['sync_settings'].get('inbox_list_name', 'Todoist Inbox'),
                'is_inbox': True
            })()

            all_projects = [inbox_project] + projects

            if self.verbose:
                logger.info(f"Found {len(all_projects)} Todoist projects (including inbox)")
                for proj in all_projects:
                    logger.info(f"  - {proj.name} (ID: {proj.id})")

            return all_projects
        except Exception as e:
            logger.error(f"Error fetching Todoist projects: {e}")
            if self.verbose:
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
            return []

    def get_todoist_tasks_by_project(self, project_id: str) -> List:
        """Get all tasks from a specific Todoist project."""
        try:
            if project_id == 'inbox':
                # Get tasks with no project (inbox tasks)
                all_tasks = []
                tasks_paginator = self.todoist.get_tasks()
                for page in tasks_paginator:
                    all_tasks.extend(page)

                # Filter for tasks with no project_id
                inbox_tasks = [t for t in all_tasks if not hasattr(t, 'project_id') or not t.project_id]

                if self.verbose:
                    logger.info(f"Found {len(inbox_tasks)} tasks in inbox")

                return inbox_tasks
            else:
                # Get tasks for specific project
                tasks = []
                tasks_paginator = self.todoist.get_tasks(project_id=project_id)
                for page in tasks_paginator:
                    tasks.extend(page)

                if self.verbose:
                    logger.info(f"Found {len(tasks)} tasks in project {project_id}")

                return tasks
        except Exception as e:
            logger.error(f"Error fetching tasks for project {project_id}: {e}")
            if self.verbose:
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
            return []

    def find_or_create_gtasks_list(self, project_name: str, project_id: str) -> Optional[str]:
        """Find existing Google Tasks list or create new one matching Todoist project."""
        try:
            # Check if we already have a mapping
            if project_id in self.mappings['project_to_list']:
                list_id = self.mappings['project_to_list'][project_id]

                # Verify the list still exists
                try:
                    self.gtasks.tasklists().get(tasklist=list_id).execute()
                    if self.verbose:
                        logger.info(f"Using existing mapped list for project '{project_name}': {list_id}")
                    return list_id
                except:
                    # List no longer exists, remove mapping
                    if self.verbose:
                        logger.info(f"Mapped list {list_id} no longer exists, will create new")
                    del self.mappings['project_to_list'][project_id]

            # Search for existing list by name
            results = self.gtasks.tasklists().list().execute()
            lists = results.get('items', [])

            for task_list in lists:
                if task_list['title'] == project_name:
                    list_id = task_list['id']
                    self.mappings['project_to_list'][project_id] = list_id
                    if self.verbose:
                        logger.info(f"Found existing list '{project_name}': {list_id}")
                    return list_id

            # Create new list
            if self.dry_run:
                logger.info(f"[DRY-RUN] Would create new Google Tasks list: '{project_name}'")
                # Return a fake ID for dry-run
                return f"dry_run_list_{project_id}"

            new_list = self.gtasks.tasklists().insert(body={'title': project_name}).execute()
            list_id = new_list['id']
            self.mappings['project_to_list'][project_id] = list_id
            logger.info(f"Created new Google Tasks list: '{project_name}' (ID: {list_id})")

            return list_id

        except Exception as e:
            logger.error(f"Error finding/creating Google Tasks list for project '{project_name}': {e}")
            if self.verbose:
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
            return None

    def parse_todoist_recurrence(self, task) -> Optional[int]:
        """
        Extract recurrence interval in days from Todoist recurring task.
        Returns number of days, or None if not recurring.
        """
        if not hasattr(task, 'due') or not task.due:
            return None

        if not hasattr(task.due, 'is_recurring') or not task.due.is_recurring:
            return None

        # Get the human-readable recurrence string
        due_string = getattr(task.due, 'string', '').lower()

        if self.verbose:
            logger.info(f"Parsing recurrence for task '{task.content}': '{due_string}'")

        # Remove "every!" (non-strict recurring) and treat as "every"
        due_string = due_string.replace('every!', 'every')

        # Common daily patterns
        if 'every day' in due_string or 'daily' in due_string:
            return 1

        # Weekly patterns (including day names)
        if 'every week' in due_string or 'weekly' in due_string:
            return 7

        # Day of week patterns (every monday, every tuesday, etc.)
        weekdays = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        for day in weekdays:
            if f'every {day}' in due_string or f'every! {day}' in due_string:
                return 7

        # Monthly patterns
        if 'every month' in due_string or 'monthly' in due_string:
            return 30

        # Day of month patterns (every 1st, every 15th, etc.)
        match = re.search(r'every\s+(\d+)(?:st|nd|rd|th)', due_string)
        if match:
            # It's monthly on a specific day
            return 30

        # Yearly patterns
        if 'every year' in due_string or 'yearly' in due_string or 'annually' in due_string:
            return 365

        # Pattern: "every X days"
        match = re.search(r'every\s+(\d+)\s+days?', due_string)
        if match:
            return int(match.group(1))

        # Pattern: "every X weeks"
        match = re.search(r'every\s+(\d+)\s+weeks?', due_string)
        if match:
            return int(match.group(1)) * 7

        # Pattern: "every X months"
        match = re.search(r'every\s+(\d+)\s+months?', due_string)
        if match:
            return int(match.group(1)) * 30

        # Pattern: "every X years"
        match = re.search(r'every\s+(\d+)\s+years?', due_string)
        if match:
            return int(match.group(1)) * 365

        # Default: if recurring but we can't parse, use 7 days (conservative weekly default)
        if self.verbose:
            logger.warning(f"Could not parse recurrence pattern '{due_string}', defaulting to 7 days")
        return 7

    def sync_task_to_gtasks(self, todoist_task, list_id: str) -> bool:
        """
        Sync a Todoist task to Google Tasks (create or update).
        Returns True if successful, False otherwise.
        """
        try:
            task_id_str = str(todoist_task.id)

            # Prepare task notes - start with recurrence if present
            notes = ""

            # Check for recurrence and prepend raw due.string
            if hasattr(todoist_task, 'due') and todoist_task.due:
                if hasattr(todoist_task.due, 'is_recurring') and todoist_task.due.is_recurring:
                    due_string = getattr(todoist_task.due, 'string', '')
                    if due_string:
                        notes = due_string
                        if self.verbose:
                            logger.info(f"Added recurrence string: {due_string}")

            # Add task description if present
            if hasattr(todoist_task, 'description') and todoist_task.description:
                if notes:
                    notes += f"\n\n{todoist_task.description}"
                else:
                    notes = todoist_task.description

            # Handle due date
            due_date_for_gtask = None
            if hasattr(todoist_task, 'due') and todoist_task.due:
                if hasattr(todoist_task.due, 'datetime') and todoist_task.due.datetime:
                    due_date_for_gtask = todoist_task.due.datetime
                elif hasattr(todoist_task.due, 'date') and todoist_task.due.date:
                    if isinstance(todoist_task.due.date, str):
                        due_date_for_gtask = todoist_task.due.date + "T00:00:00.000Z"
                    else:
                        due_date_for_gtask = todoist_task.due.date.strftime("%Y-%m-%dT00:00:00.000Z")

            task_body = {
                'title': todoist_task.content,
                'notes': notes
            }

            if due_date_for_gtask:
                task_body['due'] = due_date_for_gtask

            # Check if task already exists
            if task_id_str in self.mappings['todoist_to_gtasks']:
                gtasks_id = self.mappings['todoist_to_gtasks'][task_id_str]

                # Update existing task
                if self.dry_run:
                    logger.info(f"[DRY-RUN] Would update Google Task: '{todoist_task.content}'")
                else:
                    task_body['id'] = gtasks_id
                    self.gtasks.tasks().update(
                        tasklist=list_id,
                        task=gtasks_id,
                        body=task_body
                    ).execute()

                    if self.verbose:
                        logger.info(f"Updated Google Task: '{todoist_task.content}'")

            else:
                # Create new task
                if self.dry_run:
                    logger.info(f"[DRY-RUN] Would create Google Task: '{todoist_task.content}'")
                else:
                    result = self.gtasks.tasks().insert(
                        tasklist=list_id,
                        body=task_body
                    ).execute()

                    gtasks_id = result['id']
                    self.mappings['todoist_to_gtasks'][task_id_str] = gtasks_id
                    self.mappings['gtasks_to_todoist'][gtasks_id] = task_id_str

                    logger.info(f"Created Google Task: '{todoist_task.content}'")

            return True

        except Exception as e:
            logger.error(f"Error syncing task '{todoist_task.content}': {e}")
            if self.verbose:
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
            return False

    def sync_all_projects(self):
        """Main sync loop: sync all Todoist projects to Google Tasks lists."""
        logger.info("Starting Todoist → Google Tasks project sync...")

        # Get all projects
        projects = self.get_todoist_projects()
        excluded = self.config['sync_settings'].get('excluded_projects', [])

        # Filter excluded projects
        projects_to_sync = [p for p in projects if p.name not in excluded]

        if excluded:
            logger.info(f"Excluding {len(excluded)} project(s): {excluded}")

        logger.info(f"Syncing {len(projects_to_sync)} project(s)")

        total_tasks = 0
        total_created = 0
        total_updated = 0
        total_limit_reached = False

        for project in projects_to_sync:
            logger.info(f"\nProcessing project: '{project.name}'")

            # Find or create corresponding Google Tasks list
            list_id = self.find_or_create_gtasks_list(project.name, str(project.id))
            if not list_id:
                logger.error(f"Could not get list ID for project '{project.name}', skipping")
                continue

            # Get all tasks in this project
            tasks = self.get_todoist_tasks_by_project(str(project.id))
            logger.info(f"Found {len(tasks)} task(s) in project '{project.name}'")

            # Sync each task
            for task in tasks:
                # Check limit
                if self.limit and total_tasks >= self.limit:
                    logger.info(f"\n⚠ Limit of {self.limit} tasks reached, stopping sync")
                    total_limit_reached = True
                    break

                task_id_str = str(task.id)
                was_new = task_id_str not in self.mappings['todoist_to_gtasks']

                if self.sync_task_to_gtasks(task, list_id):
                    total_tasks += 1
                    if was_new:
                        total_created += 1
                    else:
                        total_updated += 1

            # Break outer loop if limit reached
            if total_limit_reached:
                break

        # Save mappings (skip in dry-run mode)
        if not self.dry_run:
            self.save_mappings()
        else:
            logger.info("[DRY-RUN] Would save mappings")

        status_msg = f"\nSync complete: {total_tasks} tasks processed ({total_created} created, {total_updated} updated)"
        if total_limit_reached:
            status_msg += f" [LIMIT REACHED: {self.limit}]"
        logger.info(status_msg)

    def full_sync(self):
        """Perform a complete synchronization cycle."""
        logger.info("=" * 50)
        logger.info("Starting full synchronization cycle")
        logger.info("=" * 50)

        try:
            self.sync_all_projects()
            logger.info("Synchronization completed successfully")
        except Exception as e:
            logger.error(f"Error during synchronization: {e}")
            if self.verbose:
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")

    def run_continuous_sync(self):
        """Run continuous synchronization with specified interval."""
        interval = self.config['sync_settings']['sync_interval_minutes']
        logger.info(f"Starting continuous sync with {interval} minute intervals")
        logger.info("Press Ctrl+C to stop")

        try:
            while True:
                self.full_sync()
                logger.info(f"Waiting {interval} minutes until next sync...")
                time.sleep(interval * 60)
        except KeyboardInterrupt:
            logger.info("Synchronization stopped by user")


def main():
    """Main function with CLI interface."""
    import argparse

    parser = argparse.ArgumentParser(
        description="One-way sync from Todoist projects to Google Tasks lists"
    )
    parser.add_argument(
        '--daemon',
        action='store_true',
        help='Run continuous sync mode (default: run once and exit)'
    )
    parser.add_argument(
        '--config',
        default='todoist-to-gtasks.conf',
        help='Config file path (default: todoist-to-gtasks.conf)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making any changes'
    )
    parser.add_argument(
        '--limit',
        type=int,
        help='Limit number of tasks to sync (useful for testing)'
    )

    args = parser.parse_args()

    # Set logging level based on verbose flag
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("Verbose logging enabled")

    # Create sync manager
    try:
        sync_manager = ProjectSyncManager(
            args.config,
            verbose=args.verbose,
            dry_run=args.dry_run,
            limit=args.limit
        )
    except Exception as e:
        logger.error(f"Failed to initialize sync manager: {e}")
        if args.verbose:
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
        return 1

    # Check if configuration is complete
    if not sync_manager.config.get('todoist_token'):
        logger.error(f"Todoist token not configured. Please update {args.config}")
        return 1

    if args.verbose:
        logger.info("Configuration loaded successfully")
        logger.info(f"Todoist token: {'*' * 10}...{sync_manager.config['todoist_token'][-4:]}")
        logger.info(f"Config: {sync_manager.config['sync_settings']}")

    # Run synchronization
    if args.daemon:
        sync_manager.run_continuous_sync()
    else:
        sync_manager.full_sync()

    return 0


if __name__ == "__main__":
    exit(main())
