# Google Tasks Tools

## Overview
This repository contains a collection of tools for working with Google Tasks:

1. **Todoist-Google Tasks Sync Tool** (`todoist-sync.py`) - Bidirectional synchronization between Todoist and Google Tasks
2. **Todoist to Google Tasks Project Sync** (`todoist-to-gtasks.py`) - One-way sync from Todoist projects to Google Tasks lists
3. **Recurring Tasks Tool** (`gtasks-recurring.py`) - Implements repeat-after-completion functionality for Google Tasks
4. **Starred Tasks to TRMNL Sync** (`gtasks-trmnl.py`) - Syncs starred tasks from all lists into a consolidated TRMNL display list

Additional Google Tasks utilities may be added in future development.

---

## Starred Tasks to TRMNL Sync

### Overview
This tool syncs tasks marked with ⭐ emoji from all Google Tasks lists into a dedicated "TRMNL" list. This provides a consolidated view of all your starred/important tasks for display on TRMNL devices or other purposes.

**Important Note**: Google Tasks API doesn't expose native starred status despite this feature being available in the UI since 2022. This tool uses ⭐ emoji as a marker in task titles or notes as a workaround.

### Core Functionality

#### Sync Behavior
- **Starring Method**: Detects ⭐ emoji in task title or notes
- **Direction**: One-way sync (source lists → TRMNL list)
- **Scope**: All active (incomplete) starred tasks from all lists
- **Star Emoji Handling**: Removes ⭐ from TRMNL copies for clean display
- **Updates**: Syncs changes to title, notes, and due date
- **Cleanup**: Automatically removes TRMNL copies when original is un-starred, deleted, or completed
- **Completion**: TRMNL list is read-only - completions don't sync back to originals
- **List Exclusion**: Never scans the TRMNL list itself (prevents infinite loops)

#### Key Components

##### TRMNLSyncManager Class
Main orchestrator that handles:
- Configuration management (`gtasks-trmnl.conf`)
- Task ID mappings (`gtasks-trmnl-mappings.json`)
- Google Tasks API initialization (OAuth2)
- Starred task detection and sync logic
- Cleanup of stale TRMNL tasks

##### Core Methods

**`is_task_starred(task)`** - Star detection
- Checks for ⭐ emoji in title or notes
- Returns boolean decision

**`strip_star_emoji(text)`** - Text cleaning
- Removes ⭐ from text for clean TRMNL display
- Trims excess whitespace

**`get_all_starred_tasks()`** - Task discovery
- Scans all source lists (or configured subset)
- Excludes TRMNL list itself
- Returns dictionary of list_id → starred tasks
- Only includes active (incomplete) tasks

**`sync_starred_tasks()`** - Main sync logic
- For each starred task:
  - If unmapped: Create duplicate in TRMNL (without ⭐)
  - If mapped: Check for updates, sync if changed
- Tracks all valid original task IDs for cleanup

**`cleanup_trmnl_tasks(valid_original_ids)`** - Stale task removal
- Deletes TRMNL tasks whose originals are:
  - No longer starred (⭐ removed)
  - Deleted from source list
  - Completed in source list
- Also deletes completed TRMNL tasks
- Updates mappings automatically

**`task_needs_update(original, trmnl)`** - Change detection
- Compares cleaned title, notes, and due date
- Returns True if TRMNL copy needs updating
- Strips ⭐ from original before comparison

**`get_trmnl_list_id()`** - List lookup
- Finds TRMNL list by configured name
- Returns None if not found (with error)

#### Configuration Files

**`gtasks-trmnl.conf`** - Main configuration (auto-created on first run)

A template file (`gtasks-trmnl.conf.template`) is provided with helpful comments.

```json
{
  "google_credentials_file": "credentials.json",
  "google_token_file": "token.json",
  "sync_settings": {
    "trmnl_list_name": "TRMNL",
    "source_lists": [],
    "sync_interval_minutes": 15
  }
}
```

**Configuration Options**:
- `google_credentials_file`: OAuth2 client credentials from Google Cloud Console
- `google_token_file`: Cached access/refresh tokens (auto-generated)
- `trmnl_list_name`: Name of the TRMNL list (must already exist)
- `source_lists`: List names to scan (empty array = all lists except TRMNL)
- `sync_interval_minutes`: How often to sync in daemon mode (default: 15)

**`gtasks-trmnl-mappings.json`** - ID relationship tracking
```json
{
  "original_to_trmnl": {"original_task_id": "trmnl_task_id"},
  "trmnl_to_original": {"trmnl_task_id": "original_task_id"},
  "last_sync": "2025-01-24T12:00:00Z"
}
```

#### How to Star Tasks

Since the Google Tasks API doesn't expose native starred status, use one of these methods:

1. **In title**: `⭐ Important meeting`
2. **In notes**: Add `⭐` anywhere in the task description/notes

The tool scans both fields. The ⭐ emoji will be automatically removed from the TRMNL copy for clean display.

#### Error Handling & Logging
- Dual logging: INFO/WARNING to stdout, ERROR/CRITICAL to stderr
- Verbose mode provides detailed sync decision logging
- Graceful handling of API failures
- Continues processing remaining tasks on individual failures
- Comprehensive error tracking with stack traces in verbose mode

#### Operational Modes
- **One-time sync** (default): Runs a single sync cycle and exits - ideal for cron jobs
- **Daemon mode**: `--daemon` flag enables continuous sync at configured intervals
- **Dry-run mode**: `--dry-run` shows what would be done without making any changes
- **Verbose mode**: `--verbose` for detailed logging
- **Custom config**: `--config` to specify alternate configuration file
- **Custom interval**: `--interval X` to override configured sync interval (daemon mode only)

### Usage Commands

```bash
# One-time sync (default - ideal for cron/scheduled jobs)
python gtasks-trmnl.py

# Dry-run mode (see what would be done without making changes)
python gtasks-trmnl.py --dry-run

# Daemon mode (continuous sync every 15 minutes)
python gtasks-trmnl.py --daemon

# Daemon mode with custom interval (check every 5 minutes)
python gtasks-trmnl.py --daemon --interval 5

# Verbose logging
python gtasks-trmnl.py --verbose

# Custom config file
python gtasks-trmnl.py --config my_config.json

# Combining options (dry-run with verbose logging)
python gtasks-trmnl.py --dry-run --verbose

# Combining options (daemon mode with verbose logging)
python gtasks-trmnl.py --daemon --verbose
```

### Setup Instructions

1. **Google Cloud Console Setup**:
   - Create a project in [Google Cloud Console](https://console.cloud.google.com/)
   - Enable the Google Tasks API
   - Create OAuth 2.0 credentials (Desktop application)
   - Download credentials as `credentials.json`

2. **Create TRMNL List**:
   - Open Google Tasks (web or mobile)
   - Create a new list named "TRMNL" (or your preferred name)
   - This list must exist before running the tool

3. **First Run**:
   ```bash
   python gtasks-trmnl.py
   ```
   - Will create default `gtasks-trmnl.conf` if missing
   - Will open browser for OAuth consent (first time only)
   - Will save token to `token.json` for future use

4. **Configure** (optional):
   ```bash
   # Option: Use the provided template
   cp gtasks-trmnl.conf.template gtasks-trmnl.conf
   ```
   - Edit `gtasks-trmnl.conf` to customize TRMNL list name or source lists
   - Leave `source_lists` empty to scan all lists
   - Template includes helpful comments explaining each option

5. **Test with Dry-Run** (recommended):
   ```bash
   python gtasks-trmnl.py --dry-run --verbose
   ```
   - Safely preview what would be synced without making any changes
   - Verbose mode shows detailed processing information

6. **Star Some Tasks**:
   - Add ⭐ emoji to task titles or notes in any list
   - Run the tool to sync them to TRMNL list

### Example Workflow

1. In your "Work" list, create task: "⭐ Finish presentation"
2. In your "Personal" list, add ⭐ to notes of "Buy groceries"
3. Run `python gtasks-trmnl.py`
4. Both tasks now appear in TRMNL list as:
   - "Finish presentation" (⭐ removed)
   - "Buy groceries" (⭐ removed)
5. Complete "Finish presentation" in the Work list
6. Run sync again - task is removed from TRMNL
7. Remove ⭐ from "Buy groceries"
8. Run sync again - task is removed from TRMNL

### Use Cases

**When to use this tool:**
- **TRMNL Display**: Consolidate starred tasks for display on TRMNL e-ink devices
- **Quick View**: Single list showing all important tasks across multiple projects/lists
- **Focus List**: Create a "what matters today" view from starred tasks
- **Cross-List Priority**: Track high-priority items regardless of which list they're in

**Common Workflows:**
1. **Daily Focus**: Star today's priorities across all lists, view consolidated in TRMNL
2. **TRMNL Device**: Sync starred tasks to display on e-ink device for at-a-glance viewing
3. **VIP Tasks**: Use ⭐ for critical items that need visibility regardless of organization
4. **Temporary Priority**: Star tasks temporarily, they auto-remove from TRMNL when un-starred

### API Limitation Details

**Why use ⭐ emoji instead of native stars?**

Google Tasks added a starred/favorite feature to the UI (web and mobile apps) in June 2022, but as of January 2025, this feature is **not exposed in the Google Tasks API**. The API provides no field or filter for starred status.

This limitation has been documented in:
- [Google Tasks API Reference](https://developers.google.com/tasks/reference/rest/v1/tasks) - No starred field
- Stack Overflow discussions confirming the limitation
- Community requests for API support

**Workaround**: Using ⭐ emoji marker in title/notes fields (which ARE accessible via API) provides equivalent functionality with the following advantages:
- Works reliably across all platforms
- API-accessible for automation
- Visual indicator in the UI
- Easy to add/remove manually

### Automation with Cron

Run automatically every 15 minutes:
```bash
*/15 * * * * cd /path/to/google-tasks-tools && python gtasks-trmnl.py >> trmnl_sync.log 2>&1
```

Or use daemon mode with systemd/supervisor for continuous operation.

---

## Todoist to Google Tasks Project Sync

### Overview
This tool provides one-way synchronization from Todoist projects to Google Tasks lists. Unlike the bidirectional sync tool which focuses on filtered tasks in a single list, this tool syncs ALL tasks from Todoist projects to corresponding Google Tasks lists, maintaining a complete mirror of your Todoist structure in Google Tasks.

### Core Functionality

#### Sync Behavior
- **Direction**: One-way only (Todoist → Google Tasks)
- **Scope**: ALL tasks from ALL Todoist projects (no filtering by priority, labels, or due dates)
- **Project Mapping**: Each Todoist project becomes a separate Google Tasks list
- **Inbox Support**: Todoist inbox tasks are synced to a dedicated list (configurable name, default: "Todoist Inbox")
- **List Creation**: Automatically creates Google Tasks lists if they don't exist
- **Update Strategy**: Always updates existing Google Tasks with latest Todoist data
- **Completions**: Does NOT sync completion status (manual completion in Google Tasks only)
- **Cleanup**: Does NOT delete Google Tasks when removed from Todoist

#### Recurring Tasks Integration
The tool handles Todoist recurring tasks by prepending the raw recurrence string to the task description:

**For all recurring tasks:**
- The Todoist `due.string` (e.g., "every sunday", "every! 3 days", "every 1st") is prepended to the notes
- Format: `"{recurrence string}\n\n{original description}"`

**Two types of recurrence:**
1. **`every!` (non-strict)** - Completion-based recurrence
   - Example: `"every! 3 days"` → Handled by gtasks-recurring.py
   - The task recurs X days after completion
   - Automatically managed by gtasks-recurring.py

2. **`every` (strict)** - Calendar-based recurrence
   - Examples: `"every sunday"`, `"every 1st"`, `"every month"`
   - Must be manually configured in Google Tasks web interface
   - Google Tasks API doesn't support native recurrence, so these sync as one-time tasks
   - User needs to set up the recurrence pattern manually in the UI

#### Key Components

##### ProjectSyncManager Class
Main orchestrator that handles:
- Configuration management (`todoist-to-gtasks.conf`)
- Project/list and task ID mappings (`todoist-to-gtasks-mappings.json`)
- API initialization for both platforms
- Project-based sync coordination

##### Core Methods

**`get_todoist_projects()`** - Project retrieval
- Gets all Todoist projects
- Adds special "inbox" project for tasks without a project
- Returns list of all projects to sync

**`get_todoist_tasks_by_project(project_id)`** - Task retrieval
- Gets all tasks for a specific project
- Handles inbox (project_id='inbox') as special case
- No filtering - returns ALL tasks

**`find_or_create_gtasks_list(project_name, project_id)`** - List management
- Searches for existing Google Tasks list by name
- Creates new list if not found
- Maintains project_id → list_id mapping
- Verifies mapped lists still exist

**`parse_todoist_recurrence(task)`** - Recurrence detection
- Checks if task has `due.is_recurring = True`
- Parses `due.string` to extract human-readable pattern
- Converts to number of days
- Returns None if not recurring

**`sync_task_to_gtasks(todoist_task, list_id)`** - Task sync
- Creates new Google Task or updates existing
- Prepends recurrence directive if task is recurring
- Syncs title, notes/description, and due date
- Maintains task ID mappings

**`sync_all_projects()`** - Main sync loop
- Iterates through all projects
- Finds or creates corresponding Google Tasks lists
- Syncs all tasks in each project
- Saves mappings after completion

#### Configuration Files

**`todoist-to-gtasks.conf`** - Main configuration (auto-created on first run)

A template file (`todoist-to-gtasks.conf.template`) is provided with helpful comments.

```json
{
  "todoist_token": "your_api_token",
  "google_credentials_file": "credentials.json",
  "google_token_file": "token.json",
  "sync_settings": {
    "excluded_projects": [],
    "sync_interval_minutes": 15,
    "inbox_list_name": "Todoist Inbox"
  }
}
```

**Configuration Options**:
- `todoist_token`: Your Todoist API token
- `google_credentials_file`: OAuth2 client credentials from Google Cloud Console
- `google_token_file`: Cached access/refresh tokens (auto-generated)
- `excluded_projects`: List of project names to skip (e.g., ["Archive", "Someday"])
- `sync_interval_minutes`: How often to sync in daemon mode (default: 15)
- `inbox_list_name`: Name for the Google Tasks list that receives inbox tasks

**`todoist-to-gtasks-mappings.json`** - ID relationship tracking
```json
{
  "project_to_list": {"todoist_project_id": "gtasks_list_id"},
  "todoist_to_gtasks": {"todoist_task_id": "gtasks_task_id"},
  "gtasks_to_todoist": {"gtasks_task_id": "todoist_task_id"},
  "last_sync": "2024-01-01T12:00:00Z"
}
```

#### Date Handling
- Syncs due dates from Todoist to Google Tasks
- Supports both `due.date` (date only) and `due.datetime` (with time)
- Converts to RFC 3339 format for Google Tasks API
- Date-only tasks set to midnight (00:00:00)

#### Error Handling & Logging
- Dual logging: INFO/WARNING to stdout, ERROR/CRITICAL to stderr
- Verbose mode provides detailed project and task processing logs
- Graceful handling of API failures
- Continues processing remaining projects/tasks on individual failures
- Comprehensive error tracking with stack traces in verbose mode

#### Operational Modes
- **One-time sync** (default): Runs a single sync cycle and exits - ideal for cron jobs
- **Daemon mode**: `--daemon` flag enables continuous sync at configured intervals
- **Verbose mode**: `--verbose` for detailed logging
- **Dry-run mode**: `--dry-run` shows what would be done without making any changes
- **Limit mode**: `--limit N` syncs only N tasks (useful for testing)
- **Single project mode**: `--project "Name"` syncs only the specified Todoist project
- **Custom config**: `--config` to specify alternate configuration file

### Usage Commands

```bash
# One-time sync (default - ideal for cron/scheduled jobs)
python todoist-to-gtasks.py

# Dry-run mode (see what would be done without making changes)
python todoist-to-gtasks.py --dry-run

# Limit mode (sync only first 5 tasks for testing)
python todoist-to-gtasks.py --limit 5

# Combining dry-run with limit and verbose (perfect for testing)
python todoist-to-gtasks.py --dry-run --limit 10 --verbose

# Sync only a specific project
python todoist-to-gtasks.py --project "Work" --verbose

# Daemon mode (continuous sync every 15 minutes)
python todoist-to-gtasks.py --daemon

# Verbose logging
python todoist-to-gtasks.py --verbose

# Custom config file
python todoist-to-gtasks.py --config my_config.json

# Combining options (daemon mode with verbose logging)
python todoist-to-gtasks.py --daemon --verbose
```

### Setup Instructions

1. **Get Todoist API Token**:
   - Go to [Todoist Integrations](https://todoist.com/prefs/integrations)
   - Copy your API token

2. **Google Cloud Console Setup**:
   - Create a project in [Google Cloud Console](https://console.cloud.google.com/)
   - Enable the Google Tasks API
   - Create OAuth 2.0 credentials (Desktop application)
   - Download credentials as `credentials.json`

3. **Configure**:
   ```bash
   # Option A: Let the script create default config
   python todoist-to-gtasks.py

   # Option B: Use the provided template
   cp todoist-to-gtasks.conf.template todoist-to-gtasks.conf
   ```
   - Edit `todoist-to-gtasks.conf` and add your Todoist token
   - The template includes helpful comments explaining each option
   - Run the script again - will open browser for Google OAuth consent (first time only)
   - Will save token to `token.json` for future use

4. **Test with Dry-Run** (recommended):
   ```bash
   python todoist-to-gtasks.py --dry-run --limit 5 --verbose
   ```
   - Safely preview what would be synced without making any changes
   - Limit to 5 tasks for quick testing
   - Verbose mode shows detailed processing information

5. **Configure** (optional):
   - Edit `todoist-to-gtasks.conf` to exclude projects or customize settings
   - Set `inbox_list_name` to your preferred name for inbox tasks

### Use Cases

**When to use this tool vs todoist-sync.py:**
- **Use todoist-to-gtasks.py** when you want a complete mirror of your Todoist structure in Google Tasks
- **Use todoist-sync.py** when you want filtered, bidirectional sync with a single list

**Common Workflows:**
1. **Full Mirror**: Sync all Todoist projects to Google Tasks for backup or cross-platform access
2. **Recurring Tasks**: Use Todoist's flexible recurring syntax, then let gtasks-recurring.py handle completion-based recurrence
3. **Project Organization**: Maintain separate Google Tasks lists per project for better organization
4. **One-way Flow**: Make Todoist your source of truth, use Google Tasks as read-only reference

### Integration with gtasks-recurring.py

This tool works with gtasks-recurring.py for completion-based recurring tasks:

1. **Create tasks in Todoist** with `every!` recurrence (e.g., "every! 3 days")
2. **Run todoist-to-gtasks.py** to sync to Google Tasks
   - The recurrence string is prepended to the notes
   - Example: Notes will contain `"every! 3 days\n\n[description]"`
3. **Complete the task** in Google Tasks when done
4. **Run gtasks-recurring.py** to create the next occurrence
   - Automatically detects `every! X days` pattern
   - Creates new task X days after completion
5. **Next sync** from Todoist updates the task if needed

**For strict recurring tasks** (calendar-based like "every sunday", "every 1st"):
- These sync with the recurrence string in notes
- Set up native recurrence manually in Google Tasks web interface
- gtasks-recurring.py ignores these (they use Google's native recurrence)

### Automation with Cron

Run automatically every 15 minutes:
```bash
*/15 * * * * cd /path/to/google-tasks-tools && python todoist-to-gtasks.py >> project_sync.log 2>&1
```

Or use daemon mode with systemd/supervisor for continuous operation.

---

## Todoist-Google Tasks Sync Tool

### Overview
This tool provides bidirectional synchronization between Todoist and Google Tasks, focusing on priority tasks and tasks with specific labels. It maintains task relationships and propagates completion status between both platforms.

### Core Functionality

#### Task Filtering Criteria
Tasks are synced from Todoist to Google Tasks if they meet ALL of the following conditions:

1. **Must have a due date or deadline** - Tasks without timing information are excluded
2. **Must be due within 1 day** - Tasks more than 1 day in the future are filtered out (applies to both regular and recurring tasks)
3. **Must meet priority or label criteria**:
   - Priority tasks: Tasks with priority 2+ (p3, p2, p1 in Todoist UI)
   - Label-based: Tasks containing any of the configured sync labels (default: "urgent", "important", "sync")

#### Sync Direction
- **Todoist → Google Tasks**: Creates/updates Google Tasks based on eligible Todoist tasks (title, notes, due dates)
- **Google Tasks → Todoist**: Completion status only - when a Google Task is marked complete, the corresponding Todoist task is automatically completed
- **Due Date Sync**: Due dates only sync from Todoist to Google Tasks. Changes made to due dates in Google Tasks are preserved and will NOT be overwritten by subsequent syncs

#### Key Components

##### TaskSyncManager Class
Main orchestrator that handles:
- Configuration management (`todoist-sync.conf`)
- Task ID mappings (`todoist-sync-mappings.json`)
- API initialization for both platforms
- Sync logic coordination

##### Core Methods

**`should_sync_todoist_task(task)`** - Central filtering logic
- Checks for due date/deadline presence
- Applies 1-day future filter to all tasks
- Evaluates priority and label criteria
- Returns boolean decision

**`sync_todoist_to_gtasks()`** - One-way sync from Todoist
- Fetches eligible Todoist tasks
- Creates new Google Tasks for unmapped Todoist tasks
- Updates existing Google Tasks if content differs
- Maintains bidirectional ID mappings

**`sync_completions_from_gtasks()`** - Completion propagation
- Checks all Google Tasks (including completed ones)
- Completes corresponding Todoist tasks for completed Google Tasks
- Cleans up completed Google Tasks and their mappings
- Handles orphaned completed tasks

**`full_sync()`** - Complete sync cycle
1. First processes completions (prevents race conditions)
2. Then syncs tasks from Todoist to Google Tasks
3. Saves updated mappings

#### Configuration Files

**`todoist-sync.conf`** - Main configuration

A template file (`todoist-sync.conf.template`) is provided with helpful comments.

```json
{
  "todoist_token": "your_api_token",
  "google_credentials_file": "credentials.json",
  "google_token_file": "token.json",
  "sync_settings": {
    "sync_priority_tasks": true,
    "sync_labels": ["urgent", "important", "sync"],
    "target_gtasks_list": "@default",
    "sync_interval_minutes": 15
  }
}
```

**`todoist-sync-mappings.json`** - ID relationship tracking
```json
{
  "todoist_to_gtasks": {"12345": "gtask_abc123"},
  "gtasks_to_todoist": {"gtask_abc123": "12345"},
  "last_sync": "2024-01-01T12:00:00Z"
}
```

#### Date Handling
- Supports both Todoist `due` dates and `deadline` fields
- When both exist: uses `due` date for Google Task, adds `deadline` to task description
- When only one exists: uses available date for Google Task
- Handles various date formats (ISO strings, date objects)
- Normalizes dates to RFC 3339 format for Google Tasks API

#### Error Handling & Logging
- Dual logging: INFO/WARNING to stdout, ERROR/CRITICAL to stderr
- Verbose mode provides detailed sync decision logging
- Graceful handling of API failures and malformed data
- Comprehensive error tracking with stack traces in verbose mode

#### Operational Modes
- **One-time sync** (default): Runs a single sync cycle and exits - ideal for cron jobs
- **Daemon mode**: `--daemon` flag enables continuous sync at configured intervals (default 15 minutes)
- **Verbose mode**: `--verbose` for detailed logging

### Usage Commands
```bash
# One-time sync (default - ideal for cron/scheduled jobs)
python todoist-sync.py

# Daemon mode (continuous sync)
python todoist-sync.py --daemon

# Verbose logging
python todoist-sync.py --verbose

# Custom config file
python todoist-sync.py --config my_config.json

# Combining options (daemon mode with verbose logging)
python todoist-sync.py --daemon --verbose
```

#### Backward Compatibility Note
**Breaking change**: The default behavior has changed. Previously, running `python todoist-sync.py` without flags would run continuous sync, and `--once` was required for a single execution. Now the default is to run once and exit (suitable for cron), and `--daemon` is required for continuous mode. If you have existing automation that relies on the old behavior, add the `--daemon` flag to maintain continuous operation.

---

## Recurring Tasks Tool

### Overview
This tool implements repeat-after-completion functionality for Google Tasks, a feature that's missing from the native Google Tasks interface. When a task is marked complete and contains a special directive in its description, the tool automatically creates a new copy of the task with an updated due date based on the completion time.

### Core Functionality

#### How It Works
1. **Monitors completed tasks** across all Google Tasks lists (or specific target lists)
2. **Detects recurring directive** by parsing task descriptions for `!every X days` pattern
3. **Calculates new due date** based on the completion timestamp plus X days
4. **Creates new task** with same title, description, and the new due date
5. **Deletes completed task** to keep lists clean

#### Directive Format
Add the following to any task's description/notes to make it recurring:

```
every! X days
```

Examples:
- `every! 3 days` - Recreates task 3 days after completion
- `every! 1 day` - Daily recurring task (after completion)
- `every! 7 days` - Weekly recurring task (after completion)

The directive is case-insensitive and can appear anywhere in the task notes. The new task will retain the directive, so it will continue recurring indefinitely.

**Note:** This uses Todoist's `every!` syntax (non-strict recurring). When syncing from Todoist using `todoist-to-gtasks.py`, tasks with `every! X days` patterns are automatically compatible with gtasks-recurring.py.

#### Key Features
- **Completion-based timing**: Unlike calendar-based recurring tasks, these tasks recur based on when you actually complete them
- **Preserves task content**: Title and notes (including the directive) are copied to the new task
- **All lists or selective**: Process all task lists or configure specific target lists
- **Clean completed tasks**: Automatically removes processed completed tasks
- **Dry-run mode**: Preview what would happen before making any actual changes

#### Key Components

##### RecurringTaskManager Class
Main orchestrator that handles:
- Google Tasks API authentication (OAuth2 with token caching)
- Configuration management (`gtasks-recurring.conf`)
- Completed task scanning across lists
- Directive parsing and date calculation
- New task creation and cleanup

##### Core Methods

**`parse_directive(task)`** - Directive detection
- Searches task notes for `every! X days` pattern (regex)
- Extracts the number of days
- Returns None if no directive found

**`calculate_new_due_date(completed_date, days_offset)`** - Date calculation
- Uses task's completion timestamp as baseline
- Adds the specified number of days
- Returns RFC 3339 formatted date for Google Tasks API

**`process_recurring_tasks()`** - Main processing loop
- Retrieves all task lists
- Filters to target lists if configured
- Gets completed tasks from each list
- Processes tasks with directives
- Creates new tasks and deletes completed ones

**`run_once()`** - Single execution mode
- Runs one complete processing cycle
- Exits after processing all lists

**`run_daemon(interval_minutes)`** - Continuous mode
- Loops indefinitely with configurable interval
- Graceful error handling and recovery
- Keyboard interrupt support

#### Configuration File

**`gtasks-recurring.conf`** - Main configuration (auto-created on first run)

A template file (`gtasks-recurring.conf.template`) is provided with helpful comments.

```json
{
  "google_credentials_file": "credentials.json",
  "google_token_file": "token.json",
  "settings": {
    "check_interval_minutes": 15,
    "target_lists": []
  }
}
```

**Configuration Options**:
- `google_credentials_file`: OAuth2 client credentials from Google Cloud Console
- `google_token_file`: Cached access/refresh tokens (auto-generated)
- `check_interval_minutes`: How often to check in daemon mode (default: 15)
- `target_lists`: List of task list names to process (empty array = all lists)

#### Date Calculation Details
- **Baseline**: Uses the task's `completed` timestamp from Google Tasks API
- **Offset**: Adds the number of days specified in the directive
- **Format**: Outputs RFC 3339 format (`YYYY-MM-DDTHH:MM:SS.000Z`) for Google Tasks
- **Time**: New tasks are set to midnight (00:00:00) on the calculated date

#### Error Handling & Logging
- Dual logging: INFO/WARNING to stdout, ERROR/CRITICAL to stderr
- Verbose mode provides detailed directive parsing and date calculation logs
- Graceful handling of API failures and malformed directives
- Continues processing remaining tasks even if individual tasks fail

#### Operational Modes
- **One-time execution** (default): Runs a single processing cycle and exits - ideal for cron jobs
- **Daemon mode**: `--daemon` flag enables continuous checking at configured intervals
- **Dry-run mode**: `--dry-run` flag reports what would be done without making any changes
- **Verbose mode**: `--verbose` for detailed logging
- **Custom config**: `--config` to specify alternate configuration file
- **Custom interval**: `--interval X` to override configured check interval (daemon mode only)

### Usage Commands

```bash
# One-time execution (default - ideal for cron/scheduled jobs)
python gtasks-recurring.py

# Dry-run mode (see what would be done without making changes)
python gtasks-recurring.py --dry-run

# Daemon mode (continuous checking every 15 minutes)
python gtasks-recurring.py --daemon

# Daemon mode with custom interval (check every 5 minutes)
python gtasks-recurring.py --daemon --interval 5

# Verbose logging
python gtasks-recurring.py --verbose

# Custom config file
python gtasks-recurring.py --config my_config.json

# Combining options (dry-run with verbose logging)
python gtasks-recurring.py --dry-run --verbose

# Combining options (daemon mode with verbose logging)
python gtasks-recurring.py --daemon --verbose
```

### Setup Instructions

1. **Google Cloud Console Setup**:
   - Create a project in [Google Cloud Console](https://console.cloud.google.com/)
   - Enable the Google Tasks API
   - Create OAuth 2.0 credentials (Desktop application)
   - Download credentials as `credentials.json`

2. **First Run**:
   ```bash
   python gtasks-recurring.py
   ```
   - Will create default `gtasks-recurring.conf` if missing
   - Will open browser for OAuth consent (first time only)
   - Will save token to `token.json` for future use

3. **Configure** (optional):
   ```bash
   # Option: Use the provided template
   cp gtasks-recurring.conf.template gtasks-recurring.conf
   ```
   - Edit `gtasks-recurring.conf` to set target lists or check interval
   - Leave `target_lists` empty to process all lists
   - Template includes helpful comments explaining each option

4. **Add Recurring Tasks**:
   - Create tasks in Google Tasks with due dates
   - Add `every! X days` to the task description/notes
   - Complete the task when done
   - Run the script to automatically create the next occurrence

### Example Workflow

1. Create a task: "Take vitamins"
2. Set a due date: Today
3. Add to notes: `every! 1 day`
4. Complete the task when done
5. Run `python gtasks-recurring.py`
6. Script creates new "Take vitamins" task due tomorrow
7. Completed task is automatically deleted

### Automation with Cron

Run automatically every 15 minutes:
```bash
*/15 * * * * cd /path/to/google-tasks-tools && python gtasks-recurring.py >> recurring.log 2>&1
```

Or use daemon mode with systemd/supervisor for continuous operation.

<!-- BACKLOG.MD MCP GUIDELINES START -->

<CRITICAL_INSTRUCTION>

## BACKLOG WORKFLOW INSTRUCTIONS

This project uses Backlog.md MCP for all task and project management activities.

**CRITICAL GUIDANCE**

- If your client supports MCP resources, read `backlog://workflow/overview` to understand when and how to use Backlog for this project.
- If your client only supports tools or the above request fails, call `backlog.get_workflow_overview()` tool to load the tool-oriented overview (it lists the matching guide tools).

- **First time working here?** Read the overview resource IMMEDIATELY to learn the workflow
- **Already familiar?** You should have the overview cached ("## Backlog.md Overview (MCP)")
- **When to read it**: BEFORE creating tasks, or when you're unsure whether to track work

These guides cover:
- Decision framework for when to create tasks
- Search-first workflow to avoid duplicates
- Links to detailed guides for task creation, execution, and completion
- MCP tools reference

You MUST read the overview resource to understand the complete workflow. The information is NOT summarized here.

</CRITICAL_INSTRUCTION>

<!-- BACKLOG.MD MCP GUIDELINES END -->
