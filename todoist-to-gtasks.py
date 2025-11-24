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

    def __init__(self, config_file: str = "todoist-to-gtasks.conf", verbose: bool = False, dry_run: bool = False, limit: Optional[int] = None, single_project: Optional[str] = None):
        self.config_file = config_file
        self.verbose = verbose
        self.dry_run = dry_run
        self.limit = limit
        self.single_project = single_project
        self.load_config()

        # Initialize APIs
        self.todoist = TodoistAPI(self.config['todoist_token'])
        self.gtasks = self._init_google_tasks()

        if self.dry_run:
            logger.info("DRY-RUN MODE: No changes will be made")
        if self.limit:
            logger.info(f"LIMIT MODE: Maximum {self.limit} tasks will be synced")
        if self.single_project:
            logger.info(f"SINGLE PROJECT MODE: Only syncing project '{self.single_project}'")

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

    def find_or_create_gtasks_list(self, project_name: str) -> Optional[str]:
        """Find existing Google Tasks list or create new one matching Todoist project."""
        try:
            # Search for existing list by name
            results = self.gtasks.tasklists().list().execute()
            lists = results.get('items', [])

            for task_list in lists:
                if task_list['title'] == project_name:
                    list_id = task_list['id']
                    if self.verbose:
                        logger.info(f"Found existing list '{project_name}': {list_id}")
                    return list_id

            # Create new list
            if self.dry_run:
                logger.info(f"[DRY-RUN] Would create new Google Tasks list: '{project_name}'")
                # Return a fake ID for dry-run
                return f"dry_run_list_{project_name}"

            new_list = self.gtasks.tasklists().insert(body={'title': project_name}).execute()
            list_id = new_list['id']
            logger.info(f"Created new Google Tasks list: '{project_name}' (ID: {list_id})")

            return list_id

        except Exception as e:
            logger.error(f"Error finding/creating Google Tasks list for project '{project_name}': {e}")
            if self.verbose:
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
            return None

    def get_gtasks_in_list(self, list_id: str) -> Dict[str, Dict]:
        """Get all tasks in a Google Tasks list, indexed by title."""
        try:
            result = self.gtasks.tasks().list(
                tasklist=list_id,
                showCompleted=True,
                showHidden=True
            ).execute()

            tasks = result.get('items', [])
            # Index by title for easy lookup
            return {task['title']: task for task in tasks}
        except Exception as e:
            logger.error(f"Error fetching Google Tasks from list {list_id}: {e}")
            return {}

    def sync_task_to_gtasks(self, todoist_task, list_id: str, existing_gtasks: Dict[str, Dict]) -> bool:
        """
        Sync a Todoist task to Google Tasks (create or update).
        Returns True if successful, False otherwise.
        """
        try:
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

            # Check if task already exists by title
            if todoist_task.content in existing_gtasks:
                existing_task = existing_gtasks[todoist_task.content]
                gtasks_id = existing_task['id']

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

                    logger.info(f"Created Google Task: '{todoist_task.content}'")

            return True

        except Exception as e:
            logger.error(f"Error syncing task '{todoist_task.content}': {e}")
            if self.verbose:
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
            return False

    def get_project_sections(self, project_id: str) -> Dict[str, str]:
        """Get all sections in a project, returning a dict of section_id -> section_name."""
        try:
            if project_id == 'inbox':
                # Inbox doesn't have sections
                return {}

            # get_sections() returns a list, not a paginator
            sections_list = self.todoist.get_sections(project_id=project_id)

            # Handle both single list and paginated results
            sections = []
            if hasattr(sections_list, '__iter__'):
                # Check if it's a paginator by trying to iterate
                try:
                    for item in sections_list:
                        if isinstance(item, list):
                            # It's paginated - item is a list of sections
                            sections.extend(item)
                        else:
                            # It's a direct list - item is a section
                            sections.append(item)
                except:
                    sections = list(sections_list)

            sections_dict = {str(section.id): section.name for section in sections}

            if self.verbose and sections_dict:
                logger.info(f"Found {len(sections_dict)} section(s): {list(sections_dict.values())}")

            return sections_dict
        except Exception as e:
            logger.error(f"Error fetching sections for project {project_id}: {e}")
            if self.verbose:
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
            return {}

    def sync_all_projects(self):
        """Main sync loop: sync all Todoist projects to Google Tasks lists."""
        logger.info("Starting Todoist → Google Tasks project sync...")

        # Get all projects
        projects = self.get_todoist_projects()
        excluded = self.config['sync_settings'].get('excluded_projects', [])

        # Filter to single project if specified
        if self.single_project:
            projects_to_sync = [p for p in projects if p.name == self.single_project]
            if not projects_to_sync:
                logger.error(f"Project '{self.single_project}' not found")
                logger.info(f"Available projects: {[p.name for p in projects]}")
                return
            logger.info(f"Syncing single project: '{self.single_project}'")
        else:
            # Filter excluded projects
            projects_to_sync = [p for p in projects if p.name not in excluded]

            if excluded:
                logger.info(f"Excluding {len(excluded)} project(s): {excluded}")

            logger.info(f"Syncing {len(projects_to_sync)} project(s)")

        total_tasks = 0
        total_limit_reached = False

        for project in projects_to_sync:
            logger.info(f"\nProcessing project: '{project.name}'")

            # Get sections for this project
            sections = self.get_project_sections(str(project.id))

            # Get all tasks in this project
            tasks = self.get_todoist_tasks_by_project(str(project.id))
            logger.info(f"Found {len(tasks)} task(s) in project '{project.name}'")

            # Group tasks by section
            tasks_by_section = {}  # section_id -> [tasks]
            for task in tasks:
                section_id = getattr(task, 'section_id', None)
                section_id_str = str(section_id) if section_id else None

                if section_id_str not in tasks_by_section:
                    tasks_by_section[section_id_str] = []
                tasks_by_section[section_id_str].append(task)

            # Process each section (or no section)
            for section_id, section_tasks in tasks_by_section.items():
                if total_limit_reached:
                    break

                # Determine list name
                if section_id and section_id in sections:
                    list_name = f"{project.name} - {sections[section_id]}"
                else:
                    list_name = project.name

                if self.verbose:
                    logger.info(f"\nProcessing section: '{list_name}' ({len(section_tasks)} tasks)")

                # Find or create corresponding Google Tasks list
                list_id = self.find_or_create_gtasks_list(list_name)
                if not list_id:
                    logger.error(f"Could not get list ID for '{list_name}', skipping")
                    continue

                # Get existing tasks in Google Tasks list
                existing_gtasks = self.get_gtasks_in_list(list_id)
                if self.verbose:
                    logger.info(f"Found {len(existing_gtasks)} existing Google Task(s) in list")

                # Sync each task in this section
                for task in section_tasks:
                    # Check limit
                    if self.limit and total_tasks >= self.limit:
                        logger.info(f"\n⚠ Limit of {self.limit} tasks reached, stopping sync")
                        total_limit_reached = True
                        break

                    if self.sync_task_to_gtasks(task, list_id, existing_gtasks):
                        total_tasks += 1

            # Break outer loop if limit reached
            if total_limit_reached:
                break

        status_msg = f"\nSync complete: {total_tasks} tasks processed"
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
    parser.add_argument(
        '--project',
        type=str,
        help='Sync only a specific Todoist project by name (e.g., "Inbox", "Work")'
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
            limit=args.limit,
            single_project=args.project
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
