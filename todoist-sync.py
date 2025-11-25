"""
Todoist-Google Tasks Sync Tool

This program syncs priority tasks and tasks with specific labels from Todoist to Google Tasks.
It maintains bidirectional sync and propagates completion status between platforms.

Requirements:
- pip install todoist-api-python google-api-python-client google-auth-oauthlib google-auth-httplib2

Setup:
1. Get Todoist API token from https://todoist.com/prefs/integrations
2. Set up Google Tasks API credentials (see README section below)
3. Configure sync settings in the script
"""

import json
import os
import logging
import sys
from datetime import datetime, timezone
from typing import List, Optional
import time

from confparser import load_config, create_default_config

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

class TaskSyncManager:
    """Manages synchronization between Todoist and Google Tasks."""
    
    def __init__(self, config_file: str = "todoist-sync.conf", verbose: bool = False):
        # Resolve paths relative to script directory for cron compatibility
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.config_file = os.path.join(script_dir, config_file) if not os.path.isabs(config_file) else config_file
        self.mapping_file = os.path.join(script_dir, "todoist-sync-mappings.json")
        self.verbose = verbose
        self.load_config()
        self.load_mappings()
        
        # Initialize APIs
        self.todoist = TodoistAPI(self.config['todoist_token'])
        self.gtasks = self._init_google_tasks()
    
    def tasks_are_different(self, gtask, todoist_task) -> bool:
        """Check if Google Task and Todoist task have differences that require updating."""
        # Compare title
        if gtask.get('title', '') != todoist_task.content:
            if self.verbose:
                logger.info(f"    Title differs: '{gtask.get('title', '')}' vs '{todoist_task.content}'")
            return True
        
        # Compare notes - build expected notes with deadline if both due date and deadline exist
        expected_notes = f"Synced from Todoist\nOriginal ID: {todoist_task.id}"
        
        has_due = hasattr(todoist_task, 'due') and todoist_task.due
        has_deadline = hasattr(todoist_task, 'deadline') and todoist_task.deadline
        
        if has_due and has_deadline:
            deadline_str = ""
            if isinstance(todoist_task.deadline, str):
                deadline_str = todoist_task.deadline
            else:
                if hasattr(todoist_task.deadline, 'date') and todoist_task.deadline.date:
                    if isinstance(todoist_task.deadline.date, str):
                        deadline_str = todoist_task.deadline.date
                    else:
                        deadline_str = todoist_task.deadline.date.strftime("%Y-%m-%d")
                elif hasattr(todoist_task.deadline, 'datetime') and todoist_task.deadline.datetime:
                    deadline_str = todoist_task.deadline.datetime
                else:
                    deadline_str = str(todoist_task.deadline)
            
            expected_notes += f"\nDeadline: {deadline_str}"
        
        if gtask.get('notes', '') != expected_notes:
            if self.verbose:
                logger.info(f"    Notes differ: '{gtask.get('notes', '')}' vs '{expected_notes}'")
            return True
        
        # Skip due date comparison to prevent overwriting Google Tasks due date changes
        # Due dates only sync from Todoist -> Google Tasks, not the reverse
        # This allows users to modify due dates in Google Tasks without them being reset
        if self.verbose:
            logger.info(f"    Skipping due date comparison (due dates don't sync Google Tasks -> Todoist)")
        
        if self.verbose:
            logger.info(f"    No differences found - skipping update")
        return False

    def _should_complete_todoist_task(self, gtask, todoist_id: str) -> bool:
        """Check if we should complete a Todoist task based on date comparison with completed Google Task."""
        from datetime import datetime, timezone

        try:
            # Get the current Todoist task to check its due date
            todoist_task = self.todoist.get_task(task_id=todoist_id)

            # Get Google Task due date
            gtask_due = gtask.get('due')
            if not gtask_due:
                # If Google Task has no due date, allow completion
                if self.verbose:
                    logger.info(f"    Google Task has no due date - allowing completion")
                return True

            # Parse Google Task due date
            try:
                gtask_due_date = datetime.fromisoformat(gtask_due.replace('Z', '+00:00')).date()
            except (ValueError, AttributeError):
                # If we can't parse the Google Task date, allow completion
                if self.verbose:
                    logger.info(f"    Could not parse Google Task due date '{gtask_due}' - allowing completion")
                return True

            # Get Todoist task due date
            todoist_due_date = None
            has_due = hasattr(todoist_task, 'due') and todoist_task.due
            has_deadline = hasattr(todoist_task, 'deadline') and todoist_task.deadline

            if has_due:
                if hasattr(todoist_task.due, 'date') and todoist_task.due.date:
                    if isinstance(todoist_task.due.date, str):
                        try:
                            todoist_due_date = datetime.strptime(todoist_task.due.date, '%Y-%m-%d').date()
                        except ValueError:
                            pass
                    else:
                        todoist_due_date = todoist_task.due.date
                elif hasattr(todoist_task.due, 'datetime') and todoist_task.due.datetime:
                    try:
                        todoist_due_date = datetime.fromisoformat(todoist_task.due.datetime.replace('Z', '+00:00')).date()
                    except (ValueError, AttributeError):
                        pass
            elif has_deadline:
                # Handle deadline object similar to due date
                if hasattr(todoist_task.deadline, 'date') and todoist_task.deadline.date:
                    if isinstance(todoist_task.deadline.date, str):
                        try:
                            todoist_due_date = datetime.strptime(todoist_task.deadline.date, '%Y-%m-%d').date()
                        except ValueError:
                            pass
                    else:
                        todoist_due_date = todoist_task.deadline.date
                elif hasattr(todoist_task.deadline, 'datetime') and todoist_task.deadline.datetime:
                    try:
                        todoist_due_date = datetime.fromisoformat(todoist_task.deadline.datetime.replace('Z', '+00:00')).date()
                    except (ValueError, AttributeError):
                        pass
                elif isinstance(todoist_task.deadline, str):
                    try:
                        if 'T' in todoist_task.deadline:
                            todoist_due_date = datetime.fromisoformat(todoist_task.deadline.replace('Z', '+00:00')).date()
                        else:
                            todoist_due_date = datetime.strptime(todoist_task.deadline, '%Y-%m-%d').date()
                    except ValueError:
                        pass

            if not todoist_due_date:
                # If Todoist task has no due date, allow completion
                if self.verbose:
                    logger.info(f"    Todoist task has no due date - allowing completion")
                return True

            # Compare dates
            if self.verbose:
                logger.info(f"    Google Task due date: {gtask_due_date}")
                logger.info(f"    Todoist task due date: {todoist_due_date}")

            # Only complete if Todoist task is not significantly in the future compared to Google Task
            # Allow completion if dates match or Todoist task is not more than 1 day after Google Task
            days_diff = (todoist_due_date - gtask_due_date).days

            if days_diff <= 1:  # Allow same day or 1 day difference
                if self.verbose:
                    logger.info(f"    Date difference: {days_diff} days - allowing completion")
                return True
            else:
                if self.verbose:
                    logger.info(f"    Date difference: {days_diff} days - preventing completion (Todoist task is too far in future)")
                logger.warning(f"Skipping completion of Todoist task '{todoist_task.content}' - it's due {days_diff} days after the completed Google Task")
                return False

        except Exception as e:
            # If there's any error checking dates, err on the side of caution and allow completion
            logger.warning(f"Error checking dates for task completion: {e}")
            if self.verbose:
                import traceback
                logger.warning(f"Full traceback: {traceback.format_exc()}")
            return True

    def load_config(self):
        """Load configuration from file or create default."""
        default_template = """# Todoist-Google Tasks Bidirectional Sync Configuration
# Copy this file to 'todoist-sync.conf' and fill in your details

# Get your Todoist API token from: https://todoist.com/prefs/integrations
todoist_token = YOUR_TODOIST_API_TOKEN_HERE

# Google API credentials - download from Google Cloud Console
google_credentials_file = credentials.json
google_token_file = token.json

# Sync tasks with priority 2+ (p3, p2, p1 in Todoist)
sync_priority_tasks = true

# Sync tasks with any of these labels (comma-separated)
sync_labels = urgent, important, sync

# Target Google Tasks list name, or '@default' for default list
target_gtasks_list = @default

# How often to sync in daemon mode (minutes)
sync_interval_minutes = 15
"""

        defaults = {
            'todoist_token': '',
            'google_credentials_file': 'credentials.json',
            'google_token_file': 'token.json',
            'sync_priority_tasks': True,
            'sync_labels': ['urgent', 'important', 'sync'],
            'target_gtasks_list': '@default',
            'sync_interval_minutes': 15
        }

        if not os.path.exists(self.config_file):
            create_default_config(self.config_file, default_template)
            logger.warning(f"Created default config file: {self.config_file}")
            logger.warning("Please update with your API credentials!")

        self.config = load_config(self.config_file, defaults)

        # Resolve credential paths relative to script directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        for key in ('google_credentials_file', 'google_token_file'):
            if self.config.get(key) and not os.path.isabs(self.config[key]):
                self.config[key] = os.path.join(script_dir, self.config[key])

        # Handle sync_labels as string (if not parsed as list)
        if isinstance(self.config.get('sync_labels'), str):
            self.config['sync_labels'] = [
                label.strip() for label in self.config['sync_labels'].split(',')
            ]
    
    def load_mappings(self):
        """Load task ID mappings between platforms."""
        if os.path.exists(self.mapping_file):
            with open(self.mapping_file, 'r') as f:
                self.mappings = json.load(f)
        else:
            self.mappings = {
                "todoist_to_gtasks": {},  # todoist_id -> gtasks_id
                "gtasks_to_todoist": {},  # gtasks_id -> todoist_id
                "last_sync": None
            }
    
    def save_mappings(self):
        """Save task ID mappings to file."""
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
    
    def get_target_gtasks_list_id(self) -> str:
        """Get the target Google Tasks list ID."""
        target_list = self.config['target_gtasks_list']
        
        if self.verbose:
            logger.info(f"Looking for Google Tasks list: '{target_list}'")
        
        if target_list == "@default":
            # Get default task list
            results = self.gtasks.tasklists().list().execute()
            lists = results.get('items', [])
            if self.verbose:
                logger.info(f"Found {len(lists)} Google Tasks lists")
                for i, task_list in enumerate(lists):
                    logger.info(f"  {i+1}. {task_list['title']} (ID: {task_list['id']})")
            
            if lists:
                selected_id = lists[0]['id']
                if self.verbose:
                    logger.info(f"Using default list: '{lists[0]['title']}' (ID: {selected_id})")
                return selected_id
            else:
                raise Exception("No Google Tasks lists found")
        else:
            # Find list by title
            results = self.gtasks.tasklists().list().execute()
            lists = results.get('items', [])
            if self.verbose:
                logger.info(f"Searching for list named '{target_list}' among {len(lists)} lists")
            
            for task_list in lists:
                if self.verbose:
                    logger.info(f"  Checking: '{task_list['title']}'")
                if task_list['title'] == target_list:
                    if self.verbose:
                        logger.info(f"✓ Found matching list: {task_list['id']}")
                    return task_list['id']
            
            # Create list if not found
            if self.verbose:
                logger.info(f"List '{target_list}' not found, creating new list...")
            new_list = self.gtasks.tasklists().insert(body={'title': target_list}).execute()
            if self.verbose:
                logger.info(f"✓ Created new list: '{target_list}' (ID: {new_list['id']})")
            return new_list['id']
    
    def should_sync_todoist_task(self, task) -> bool:
        """Check if a Todoist task should be synced."""
        settings = self.config
        
        if self.verbose:
            logger.info(f"Evaluating task: '{task.content}' (ID: {task.id})")
            logger.info(f"  Task priority: {task.priority}")
            logger.info(f"  Task labels: {getattr(task, 'labels', 'No labels attribute')}")
            
            # Check due date, deadline and recurring status
            due_info = getattr(task, 'due', None)
            deadline = getattr(task, 'deadline', None)
            if due_info:
                is_recurring = getattr(due_info, 'is_recurring', False)
                due_date = getattr(due_info, 'date', None) or getattr(due_info, 'datetime', None)
                logger.info(f"  Due date: {due_date}")
                logger.info(f"  Is recurring: {is_recurring}")
            else:
                logger.info(f"  Due date: None")
                logger.info(f"  Is recurring: False (no due date)")
            
            if deadline:
                logger.info(f"  Deadline: {deadline}")
            else:
                logger.info(f"  Deadline: None")
        
        # First check: Must have either due date or deadline
        has_due_date = hasattr(task, 'due') and task.due and (
            (hasattr(task.due, 'date') and task.due.date) or 
            (hasattr(task.due, 'datetime') and task.due.datetime)
        )
        has_deadline = hasattr(task, 'deadline') and task.deadline
        
        if not has_due_date and not has_deadline:
            if self.verbose:
                logger.info(f"  Task has no due date or deadline - skipping sync")
            return False
        
        # Check for tasks with future due dates (applies to all tasks, not just recurring)
        from datetime import datetime
        
        due_date = None
        # Check due date from either due or deadline
        if hasattr(task, 'due') and task.due:
            if hasattr(task.due, 'date') and task.due.date:
                if isinstance(task.due.date, str):
                    try:
                        due_date = datetime.strptime(task.due.date, '%Y-%m-%d').date()
                    except ValueError:
                        due_date = None
                else:
                    due_date = task.due.date
            elif hasattr(task.due, 'datetime') and task.due.datetime:
                try:
                    due_date = datetime.fromisoformat(task.due.datetime.replace('Z', '+00:00')).date()
                except (ValueError, AttributeError):
                    due_date = None
        elif hasattr(task, 'deadline') and task.deadline:
            # Handle deadline object - check for date attribute
            if hasattr(task.deadline, 'date') and task.deadline.date:
                if isinstance(task.deadline.date, str):
                    try:
                        due_date = datetime.strptime(task.deadline.date, '%Y-%m-%d').date()
                    except ValueError:
                        due_date = None
                else:
                    due_date = task.deadline.date
            elif hasattr(task.deadline, 'datetime') and task.deadline.datetime:
                try:
                    due_date = datetime.fromisoformat(task.deadline.datetime.replace('Z', '+00:00')).date()
                except (ValueError, AttributeError):
                    due_date = None
            elif isinstance(task.deadline, str):
                try:
                    if 'T' in task.deadline:
                        due_date = datetime.fromisoformat(task.deadline.replace('Z', '+00:00')).date()
                    else:
                        due_date = datetime.strptime(task.deadline, '%Y-%m-%d').date()
                except ValueError:
                    due_date = None
        
        if due_date:
            today = datetime.now().date()
            days_until_due = (due_date - today).days
            
            is_recurring = hasattr(task, 'due') and task.due and hasattr(task.due, 'is_recurring') and task.due.is_recurring
            
            if self.verbose:
                logger.info(f"  Due date parsed: {due_date}")
                logger.info(f"  Days until due: {days_until_due}")
                logger.info(f"  Is recurring: {is_recurring}")
            
            if days_until_due > 1:
                task_type = "recurring task" if is_recurring else "task"
                if self.verbose:
                    logger.info(f"  {task_type.capitalize()} due in {days_until_due} days - skipping sync")
                return False
            else:
                task_type = "recurring task" if is_recurring else "task"
                if self.verbose:
                    logger.info(f"  {task_type.capitalize()} due in {days_until_due} days - will sync")
        else:
            if self.verbose:
                logger.info(f"  Could not parse due date - will sync")
        
        # Check priority (priority 4 is p1, 3 is p2, 2 is p3, 1 is p4/no priority)
        priority_check = settings.get('sync_priority_tasks', False) and task.priority >= 2
        if self.verbose:
            logger.info(f"  Priority check (sync_priority_tasks={settings.get('sync_priority_tasks', False)}, priority>={2}): {priority_check}")
        
        # Check labels
        sync_labels = set(settings.get('sync_labels', []))
        task_labels = set(task.labels) if hasattr(task, 'labels') and task.labels else set()
        label_check = bool(sync_labels.intersection(task_labels))
        if self.verbose:
            logger.info(f"  Sync labels configured: {sync_labels}")
            logger.info(f"  Task labels found: {task_labels}")
            logger.info(f"  Label check (intersection): {label_check}")
        
        should_sync = priority_check or label_check
        if self.verbose:
            logger.info(f"  Final decision - Should sync: {should_sync}")
            
        return should_sync
    
    def get_todoist_tasks_to_sync(self) -> List:
        """Get Todoist tasks that should be synced."""
        try:
            if self.verbose:
                logger.info("Fetching all Todoist tasks...")
            
            # Handle pagination - get_tasks() returns a paginated iterator
            all_tasks = []
            tasks_paginator = self.todoist.get_tasks()
            
            # Iterate through all pages to get all tasks
            for page in tasks_paginator:
                all_tasks.extend(page)
            
            if self.verbose:
                logger.info(f"Found {len(all_tasks)} total Todoist tasks")
                logger.info("Current sync configuration:")
                logger.info(f"  sync_priority_tasks: {self.config.get('sync_priority_tasks', False)}")
                logger.info(f"  sync_labels: {self.config.get('sync_labels', [])}")
                logger.info("")
            
            eligible_tasks = []
            for task in all_tasks:
                if self.should_sync_todoist_task(task):
                    eligible_tasks.append(task)
                    if self.verbose:
                        logger.info(f"✓ Task '{task.content}' marked for sync")
                elif self.verbose:
                    logger.info(f"✗ Task '{task.content}' skipped")
                
                if self.verbose:
                    logger.info("")  # Empty line for readability
            
            if self.verbose:
                logger.info(f"Summary: {len(eligible_tasks)} out of {len(all_tasks)} tasks will be synced")
                
            return eligible_tasks
            
        except Exception as e:
            logger.error(f"Error fetching Todoist tasks: {e}")
            if self.verbose:
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
            return []
    
    def get_google_tasks(self, list_id: str, include_completed: bool = False) -> List:
        """Get Google Tasks from specified list."""
        try:
            # The include_completed parameter doesn't seem to work reliably
            # Use the direct API call instead
            if include_completed:
                result = self.gtasks.tasks().list(
                    tasklist=list_id, 
                    showCompleted=True, 
                    showHidden=True
                ).execute()
            else:
                result = self.gtasks.tasks().list(tasklist=list_id).execute()
                
            return result.get('items', [])
        except Exception as e:
            logger.error(f"Error fetching Google Tasks: {e}")
            return []
    
    def create_google_task(self, todoist_task, list_id: str) -> Optional[str]:
        """Create a Google Task from Todoist task."""
        try:
            # Prepare task body with notes
            notes = f"Synced from Todoist\nOriginal ID: {todoist_task.id}"
            
            # Handle dates: use due date for Google Task, mention deadline in description
            due_date_for_gtask = None
            has_due = hasattr(todoist_task, 'due') and todoist_task.due
            has_deadline = hasattr(todoist_task, 'deadline') and todoist_task.deadline
            
            # Extract due date for Google Task
            if has_due:
                if hasattr(todoist_task.due, 'datetime') and todoist_task.due.datetime:
                    due_date_for_gtask = todoist_task.due.datetime
                elif hasattr(todoist_task.due, 'date') and todoist_task.due.date:
                    if isinstance(todoist_task.due.date, str):
                        due_date_for_gtask = todoist_task.due.date + "T00:00:00.000Z"
                    else:
                        due_date_for_gtask = todoist_task.due.date.strftime("%Y-%m-%dT00:00:00.000Z")
                if self.verbose:
                    logger.info(f"  Using due date for Google Task: {due_date_for_gtask}")
            
            # If no due date but has deadline, use deadline for Google Task
            elif has_deadline:
                if isinstance(todoist_task.deadline, str):
                    if 'T' in todoist_task.deadline:
                        due_date_for_gtask = todoist_task.deadline
                    else:
                        due_date_for_gtask = todoist_task.deadline + "T00:00:00.000Z"
                else:
                    # Handle deadline object
                    if hasattr(todoist_task.deadline, 'date') and todoist_task.deadline.date:
                        if isinstance(todoist_task.deadline.date, str):
                            due_date_for_gtask = todoist_task.deadline.date + "T00:00:00.000Z"
                        else:
                            due_date_for_gtask = todoist_task.deadline.date.strftime("%Y-%m-%dT00:00:00.000Z")
                    elif hasattr(todoist_task.deadline, 'datetime') and todoist_task.deadline.datetime:
                        due_date_for_gtask = todoist_task.deadline.datetime
                    else:
                        due_date_for_gtask = str(todoist_task.deadline) + "T00:00:00.000Z" if 'T' not in str(todoist_task.deadline) else str(todoist_task.deadline)
                if self.verbose:
                    logger.info(f"  Using deadline for Google Task (no due date): {due_date_for_gtask}")
            
            # Add deadline to description if both due date and deadline exist
            if has_due and has_deadline:
                deadline_str = ""
                if isinstance(todoist_task.deadline, str):
                    deadline_str = todoist_task.deadline
                else:
                    if hasattr(todoist_task.deadline, 'date') and todoist_task.deadline.date:
                        if isinstance(todoist_task.deadline.date, str):
                            deadline_str = todoist_task.deadline.date
                        else:
                            deadline_str = todoist_task.deadline.date.strftime("%Y-%m-%d")
                    elif hasattr(todoist_task.deadline, 'datetime') and todoist_task.deadline.datetime:
                        deadline_str = todoist_task.deadline.datetime
                    else:
                        deadline_str = str(todoist_task.deadline)
                
                notes += f"\nDeadline: {deadline_str}"
                if self.verbose:
                    logger.info(f"  Added deadline to description: {deadline_str}")
            
            task_body = {
                'title': todoist_task.content,
                'notes': notes
            }
            
            if due_date_for_gtask:
                task_body['due'] = due_date_for_gtask
            
            if self.verbose:
                logger.info(f"  Task body: {task_body}")
            
            # Create task
            result = self.gtasks.tasks().insert(tasklist=list_id, body=task_body).execute()
            
            # Update mappings
            gtasks_id = result['id']
            self.mappings['todoist_to_gtasks'][str(todoist_task.id)] = gtasks_id
            self.mappings['gtasks_to_todoist'][gtasks_id] = str(todoist_task.id)
            
            logger.info(f"Created Google Task: {todoist_task.content}")
            if self.verbose:
                logger.info(f"  Google Task ID: {gtasks_id}")
            return gtasks_id
            
        except Exception as e:
            logger.error(f"Error creating Google Task: {e}")
            if self.verbose:
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
                logger.info(f"Task due info: {getattr(todoist_task, 'due', 'No due date')}")
                if hasattr(todoist_task, 'due') and todoist_task.due:
                    logger.info(f"Due date type: {type(todoist_task.due.date) if hasattr(todoist_task.due, 'date') else 'No date attr'}")
            return None
    
    def update_google_task(self, gtasks_id: str, todoist_task, list_id: str):
        """Update existing Google Task."""
        try:
            # Prepare task body with notes
            notes = f"Synced from Todoist\nOriginal ID: {todoist_task.id}"
            
            # Handle dates: use due date for Google Task, mention deadline in description
            due_date_for_gtask = None
            has_due = hasattr(todoist_task, 'due') and todoist_task.due
            has_deadline = hasattr(todoist_task, 'deadline') and todoist_task.deadline
            
            # Extract due date for Google Task
            if has_due:
                if hasattr(todoist_task.due, 'datetime') and todoist_task.due.datetime:
                    due_date_for_gtask = todoist_task.due.datetime
                elif hasattr(todoist_task.due, 'date') and todoist_task.due.date:
                    if isinstance(todoist_task.due.date, str):
                        due_date_for_gtask = todoist_task.due.date + "T00:00:00.000Z"
                    else:
                        due_date_for_gtask = todoist_task.due.date.strftime("%Y-%m-%dT00:00:00.000Z")
                if self.verbose:
                    logger.info(f"  Using due date for Google Task: {due_date_for_gtask}")
            
            # If no due date but has deadline, use deadline for Google Task
            elif has_deadline:
                if isinstance(todoist_task.deadline, str):
                    if 'T' in todoist_task.deadline:
                        due_date_for_gtask = todoist_task.deadline
                    else:
                        due_date_for_gtask = todoist_task.deadline + "T00:00:00.000Z"
                else:
                    # Handle deadline object
                    if hasattr(todoist_task.deadline, 'date') and todoist_task.deadline.date:
                        if isinstance(todoist_task.deadline.date, str):
                            due_date_for_gtask = todoist_task.deadline.date + "T00:00:00.000Z"
                        else:
                            due_date_for_gtask = todoist_task.deadline.date.strftime("%Y-%m-%dT00:00:00.000Z")
                    elif hasattr(todoist_task.deadline, 'datetime') and todoist_task.deadline.datetime:
                        due_date_for_gtask = todoist_task.deadline.datetime
                    else:
                        due_date_for_gtask = str(todoist_task.deadline) + "T00:00:00.000Z" if 'T' not in str(todoist_task.deadline) else str(todoist_task.deadline)
                if self.verbose:
                    logger.info(f"  Using deadline for Google Task (no due date): {due_date_for_gtask}")
            
            # Add deadline to description if both due date and deadline exist
            if has_due and has_deadline:
                deadline_str = ""
                if isinstance(todoist_task.deadline, str):
                    deadline_str = todoist_task.deadline
                else:
                    if hasattr(todoist_task.deadline, 'date') and todoist_task.deadline.date:
                        if isinstance(todoist_task.deadline.date, str):
                            deadline_str = todoist_task.deadline.date
                        else:
                            deadline_str = todoist_task.deadline.date.strftime("%Y-%m-%d")
                    elif hasattr(todoist_task.deadline, 'datetime') and todoist_task.deadline.datetime:
                        deadline_str = todoist_task.deadline.datetime
                    else:
                        deadline_str = str(todoist_task.deadline)
                
                notes += f"\nDeadline: {deadline_str}"
                if self.verbose:
                    logger.info(f"  Added deadline to description: {deadline_str}")
            
            task_body = {
                'id': gtasks_id,  # Google Tasks API requires the ID in the body
                'title': todoist_task.content,
                'notes': notes
            }
            
            if due_date_for_gtask:
                task_body['due'] = due_date_for_gtask
            
            if self.verbose:
                logger.info(f"  Updating with task body: {task_body}")
            
            self.gtasks.tasks().update(
                tasklist=list_id, 
                task=gtasks_id, 
                body=task_body
            ).execute()
            
            logger.info(f"Updated Google Task: {todoist_task.content}")
            
        except Exception as e:
            logger.error(f"Error updating Google Task: {e}")
            if self.verbose:
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
    
    def complete_todoist_task(self, task_id: str):
        """Mark Todoist task as completed."""
        try:
            result = self.todoist.complete_task(task_id=task_id)
            if self.verbose:
                logger.info(f"  Used complete_task method, result: {result}")
            logger.info(f"Completed Todoist task: {task_id}")
        except Exception as e:
            logger.error(f"Error completing Todoist task: {e}")
            if self.verbose:
                import traceback
                logger.error(f"Full traceback: {traceback.format_exc()}")
                # Show available methods for debugging
                methods = [method for method in dir(self.todoist) if not method.startswith('_')]
                logger.info(f"Available TodoistAPI methods: {methods}")
    
    def sync_todoist_to_gtasks(self):
        """Sync tasks from Todoist to Google Tasks."""
        logger.info("Starting Todoist -> Google Tasks sync...")
        
        if self.verbose:
            logger.info("Step 1: Getting Todoist tasks to sync...")
        
        todoist_tasks = self.get_todoist_tasks_to_sync()
        
        if self.verbose:
            logger.info("Step 2: Getting target Google Tasks list...")
        
        list_id = self.get_target_gtasks_list_id()
        
        if self.verbose:
            logger.info("Step 3: Getting existing Google Tasks (incomplete only)...")
        
        # Only get incomplete tasks for sync - completed ones are handled separately
        gtasks = self.get_google_tasks(list_id, include_completed=False)
        
        if self.verbose:
            logger.info(f"Found {len(gtasks)} existing incomplete Google Tasks")
            logger.info("Step 4: Processing sync operations...")
        
        # Get existing Google Tasks IDs
        existing_gtasks_ids = {task['id'] for task in gtasks}
        
        # Clean up mappings for Google Tasks that no longer exist
        orphaned_mappings = []
        for todoist_id, gtasks_id in self.mappings['todoist_to_gtasks'].items():
            if gtasks_id not in existing_gtasks_ids:
                # Check if this Google Task was completed and cleaned up
                if self.verbose:
                    logger.info(f"Found orphaned mapping: Todoist {todoist_id} -> Google Task {gtasks_id}")
                orphaned_mappings.append((todoist_id, gtasks_id))
        
        # Remove orphaned mappings
        for todoist_id, gtasks_id in orphaned_mappings:
            if self.verbose:
                logger.info(f"Removing orphaned mapping for Todoist task {todoist_id}")
            if todoist_id in self.mappings['todoist_to_gtasks']:
                del self.mappings['todoist_to_gtasks'][todoist_id]
            if gtasks_id in self.mappings['gtasks_to_todoist']:
                del self.mappings['gtasks_to_todoist'][gtasks_id]
        
        synced_count = 0
        updated_count = 0
        created_count = 0
        
        for i, task in enumerate(todoist_tasks, 1):
            if self.verbose:
                logger.info(f"Processing task {i}/{len(todoist_tasks)}: '{task.content}'")
            
            task_id_str = str(task.id)
            
            if task_id_str in self.mappings['todoist_to_gtasks']:
                # Task already synced, check if we need to update
                gtasks_id = self.mappings['todoist_to_gtasks'][task_id_str]
                if self.verbose:
                    logger.info(f"  Task already mapped to Google Task ID: {gtasks_id}")
                
                if gtasks_id in existing_gtasks_ids:
                    # Find the corresponding Google Task to compare
                    corresponding_gtask = next((gt for gt in gtasks if gt['id'] == gtasks_id), None)
                    
                    if corresponding_gtask and self.tasks_are_different(corresponding_gtask, task):
                        if self.verbose:
                            logger.info("  Differences found - updating existing Google Task...")
                        self.update_google_task(gtasks_id, task, list_id)
                        updated_count += 1
                    elif self.verbose:
                        logger.info("  No changes needed - skipping update")
                else:
                    # This case should not happen now due to cleanup above
                    if self.verbose:
                        logger.info("  Mapping cleaned up, creating new Google Task...")
                    self.create_google_task(task, list_id)
                    created_count += 1
            else:
                # New task to sync
                if self.verbose:
                    logger.info("  Creating new Google Task...")
                self.create_google_task(task, list_id)
                created_count += 1
            
            synced_count += 1
        
        logger.info(f"Sync summary: {synced_count} tasks processed ({created_count} created, {updated_count} updated, {synced_count - created_count - updated_count} unchanged)")
    
    def sync_completions_from_gtasks(self):
        """Check for completed Google Tasks and mark corresponding Todoist tasks as complete."""
        logger.info("Checking for completed Google Tasks...")
        
        if self.verbose:
            logger.info("Step 1: Getting target Google Tasks list...")
        
        list_id = self.get_target_gtasks_list_id()
        
        if self.verbose:
            logger.info("Step 2: Getting all Google Tasks (including completed)...")
            logger.info(f"Current mappings count: {len(self.mappings['gtasks_to_todoist'])} Google->Todoist, {len(self.mappings['todoist_to_gtasks'])} Todoist->Google")
            if self.mappings['gtasks_to_todoist']:
                logger.info("Current Google->Todoist mappings:")
                for gtask_id, todoist_id in self.mappings['gtasks_to_todoist'].items():
                    logger.info(f"  {gtask_id} -> {todoist_id}")
        
        # Get ALL tasks including completed ones
        gtasks = self.get_google_tasks(list_id, include_completed=True)
        
        if self.verbose:
            logger.info(f"Found {len(gtasks)} Google Tasks to check (including completed)")
        
        completed_count = 0
        tasks_to_clean = []  # Track tasks to clean up after processing
        orphaned_completed_tasks = []  # Track completed tasks with no mapping
        
        for i, gtask in enumerate(gtasks, 1):
            gtasks_id = gtask.get('id')
            if self.verbose:
                status = gtask.get('status', 'needsAction')
                logger.info(f"Checking task {i}/{len(gtasks)}: '{gtask.get('title', 'Untitled')}' (status: {status}, ID: {gtasks_id})")
                
                # Check if this task has a mapping
                if gtasks_id in self.mappings['gtasks_to_todoist']:
                    logger.info(f"  ✓ Has mapping to Todoist task: {self.mappings['gtasks_to_todoist'][gtasks_id]}")
                else:
                    logger.info(f"  ✗ No mapping found for this Google Task")
            
            if gtask.get('status') == 'completed':
                if self.verbose:
                    logger.info(f"  ✓ Task is completed, checking for Todoist mapping...")
                
                if gtasks_id in self.mappings['gtasks_to_todoist']:
                    todoist_id = self.mappings['gtasks_to_todoist'][gtasks_id]

                    if self.verbose:
                        logger.info(f"  Found mapping to Todoist task ID: {todoist_id}")

                    # Check if we should complete this task by comparing dates
                    should_complete = self._should_complete_todoist_task(gtask, todoist_id)

                    if should_complete:
                        if self.verbose:
                            logger.info(f"  Date check passed - completing Todoist task...")

                        # Complete the Todoist task
                        self.complete_todoist_task(todoist_id)

                        completed_count += 1

                        # Mark for cleanup (don't modify mappings during iteration)
                        tasks_to_clean.append((gtasks_id, todoist_id, gtask))
                    else:
                        if self.verbose:
                            logger.info(f"  Date check failed - skipping completion but cleaning up Google Task")

                        # Still clean up the completed Google Task even if we don't complete the Todoist task
                        # Remove the mapping since the Google Task is completed and no longer relevant
                        tasks_to_clean.append((gtasks_id, None, gtask))  # None indicates no Todoist completion
                else:
                    if self.verbose:
                        logger.info(f"  No mapping found for this completed Google Task - marking as orphaned")
                    # This is an orphaned completed task - clean it up
                    orphaned_completed_tasks.append((gtasks_id, gtask))
            elif self.verbose:
                logger.info(f"  Task not completed, skipping")
        
        # Clean up completed tasks with mappings
        for gtasks_id, todoist_id, gtask in tasks_to_clean:
            try:
                # Remove from mappings since the Google Task is completed
                if gtasks_id in self.mappings['gtasks_to_todoist']:
                    del self.mappings['gtasks_to_todoist'][gtasks_id]
                # Only remove Todoist mapping if we actually completed the Todoist task
                if todoist_id and todoist_id in self.mappings['todoist_to_gtasks']:
                    del self.mappings['todoist_to_gtasks'][todoist_id]
                
                # Delete the completed Google Task to keep things clean
                self.gtasks.tasks().delete(tasklist=list_id, task=gtasks_id).execute()
                if self.verbose:
                    status = "and completed Todoist task" if todoist_id else "but skipped Todoist completion due to date mismatch"
                    logger.info(f"  Cleaned up completed Google Task {status}: {gtask.get('title', 'Untitled')}")

                status_msg = "and corresponding Todoist task" if todoist_id else "(Todoist completion skipped due to date mismatch)"
                logger.info(f"Cleaned up completed Google Task {status_msg}: {gtask.get('title', 'Untitled')}")
            except Exception as e:
                logger.warning(f"Could not delete completed Google Task {gtask.get('title', 'Untitled')}: {e}")
        
        # Clean up orphaned completed tasks (these have no mapping)
        for gtasks_id, gtask in orphaned_completed_tasks:
            try:
                self.gtasks.tasks().delete(tasklist=list_id, task=gtasks_id).execute()
                if self.verbose:
                    logger.info(f"  Cleaned up orphaned completed Google Task: {gtask.get('title', 'Untitled')}")
                logger.info(f"Cleaned up orphaned completed Google Task: {gtask.get('title', 'Untitled')}")
            except Exception as e:
                logger.warning(f"Could not delete orphaned completed Google Task {gtask.get('title', 'Untitled')}: {e}")
        
        if completed_count > 0:
            logger.info(f"Completed {completed_count} Todoist tasks based on Google Tasks")
        
        if len(orphaned_completed_tasks) > 0:
            logger.info(f"Cleaned up {len(orphaned_completed_tasks)} orphaned completed Google Tasks")
            
        if completed_count == 0 and len(orphaned_completed_tasks) == 0:
            if self.verbose:
                logger.info("No completed Google Tasks found")
            
        # Debug: Show current mappings after completion check
        if self.verbose:
            logger.info(f"Mappings after completion check: {len(self.mappings['gtasks_to_todoist'])} Google->Todoist, {len(self.mappings['todoist_to_gtasks'])} Todoist->Google")
    
    def full_sync(self):
        """Perform a complete synchronization cycle."""
        logger.info("=" * 50)
        logger.info("Starting full synchronization cycle")
        logger.info("=" * 50)
        
        try:
            # Check for completions FIRST, before syncing tasks
            # This prevents the race condition where completed tasks get recreated
            self.sync_completions_from_gtasks()
            
            # Then sync tasks from Todoist to Google Tasks
            self.sync_todoist_to_gtasks()
            
            # Save mappings
            self.save_mappings()
            
            logger.info("Synchronization completed successfully")
            
        except Exception as e:
            logger.error(f"Error during synchronization: {e}")
    
    def run_continuous_sync(self):
        """Run continuous synchronization with specified interval."""
        interval = self.config['sync_interval_minutes']
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
    
    parser = argparse.ArgumentParser(description="Sync tasks between Todoist and Google Tasks")
    parser.add_argument('--daemon', action='store_true', help='Run continuous sync mode (default: run once and exit)')
    parser.add_argument('--config', default='todoist-sync.conf', help='Config file path (default: todoist-sync.conf)')
    parser.add_argument('--verbose', action='store_true', help='Enable verbose logging')
    
    args = parser.parse_args()
    
    # Set logging level based on verbose flag
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("Verbose logging enabled")
    
    # Create sync manager
    try:
        sync_manager = TaskSyncManager(args.config, verbose=args.verbose)
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
        logger.info(f"Config: sync_priority_tasks={sync_manager.config.get('sync_priority_tasks')}, sync_labels={sync_manager.config.get('sync_labels')}")
    
    # Run synchronization
    if args.daemon:
        sync_manager.run_continuous_sync()
    else:
        sync_manager.full_sync()
    
    return 0


if __name__ == "__main__":
    exit(main())


"""
README - Setup Instructions:

1. Install dependencies:
   pip install todoist-api-python google-api-python-client google-auth-oauthlib google-auth-httplib2

2. Get Todoist API Token:
   - Go to https://todoist.com/prefs/integrations
   - Copy your API token

3. Set up Google Tasks API:
   - Go to Google Cloud Console (console.cloud.google.com)
   - Create a new project or select existing one
   - Enable the Google Tasks API
   - Go to Credentials → Create Credentials → OAuth client ID
   - Choose "Desktop application"
   - Download the JSON file and save as "credentials.json"

4. Configure the script:
   - Run the script once to create sync_config.json
   - Edit sync_config.json with your Todoist token
   - Adjust sync settings as needed

5. Run the script:
   - First run: python todoist_gtasks_sync.py --once
   - Continuous sync: python todoist_gtasks_sync.py

Configuration Options:
- sync_priority_tasks: Sync tasks with priority 2+ (p3, p2, p1)
- sync_labels: List of labels to sync (e.g., ["urgent", "important"])
- target_gtasks_list: Google Tasks list name or "@default" for default list
- sync_interval_minutes: How often to sync in continuous mode

The script maintains local storage in task_mappings.json to track relationships
between Todoist and Google Tasks. When you complete a task in Google Tasks,
it will automatically complete the corresponding task in Todoist.
"""