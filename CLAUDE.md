# Google Tasks Tools

## Overview
This repository contains a collection of tools for working with Google Tasks:

1. **Todoist-Google Tasks Sync Tool** (`todoist-sync.py`) - Bidirectional synchronization between Todoist and Google Tasks
2. **Recurring Tasks Tool** (`gtasks-recurring.py`) - Implements repeat-after-completion functionality for Google Tasks

Additional Google Tasks utilities may be added in future development.

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
- Configuration management (`sync_config.json`)
- Task ID mappings (`task_mappings.json`)
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

**`sync_config.json`** - Main configuration
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

**`task_mappings.json`** - ID relationship tracking
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
!every X days
```

Examples:
- `!every 3 days` - Recreates task 3 days after completion
- `!every 1 day` - Daily recurring task (after completion)
- `!every 7 days` - Weekly recurring task (after completion)

The directive is case-insensitive and can appear anywhere in the task notes. The new task will retain the directive, so it will continue recurring indefinitely.

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
- Configuration management (`recurring_config.json`)
- Completed task scanning across lists
- Directive parsing and date calculation
- New task creation and cleanup

##### Core Methods

**`parse_directive(task)`** - Directive detection
- Searches task notes for `!every X days` pattern (regex)
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

**`recurring_config.json`** - Main configuration (auto-created on first run)
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
   - Will create default `recurring_config.json` if missing
   - Will open browser for OAuth consent (first time only)
   - Will save token to `token.json` for future use

3. **Configure** (optional):
   - Edit `recurring_config.json` to set target lists or check interval
   - Leave `target_lists` empty to process all lists

4. **Add Recurring Tasks**:
   - Create tasks in Google Tasks with due dates
   - Add `!every X days` to the task description/notes
   - Complete the task when done
   - Run the script to automatically create the next occurrence

### Example Workflow

1. Create a task: "Take vitamins"
2. Set a due date: Today
3. Add to notes: `!every 1 day`
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
