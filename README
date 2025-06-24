# Todoist-Google Tasks Sync Tool

This program syncs priority tasks and tasks with specific labels from Todoist to Google Tasks.
It maintains bidirectional sync and propagates completion status between platforms.

Requirements:
- pip install todoist-api-python google-api-python-client google-auth-oauthlib google-auth-httplib2

Setup:
1. Get Todoist API token from https://todoist.com/prefs/integrations
2. Set up Google Tasks API credentials (see README section below)
3. Configure sync settings in the script

## Detailed instructions

### Prepare your environment

1. Create a virtual environment
python3 -m venv todoist-sync-env

2. Activate virtual environment
source todoist-sync-env/bin/activate

3. Install dependencies
pip install todoist-api-python google-api-python-client google-auth-oauthlib google-auth-httplib2

4. Run the script once to create sync_config.json
python todoist_gtasks_sync.py --once

5. Get Todoist API Token:
   - Go to https://todoist.com/prefs/integrations
   - Copy your API token

6. Set up Google Tasks API:
   - Go to Google Cloud Console (console.cloud.google.com)
   - Create a new project or select existing one
   - Enable the Google Tasks API
   - Go to Credentials → Create Credentials → OAuth client ID
   - Choose "Desktop application"
   - Download the JSON file and save as "credentials.json"

7. Configure the script:
   - Edit sync_config.json with your Todoist token
   - Adjust sync settings as needed

8. Run the script:
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