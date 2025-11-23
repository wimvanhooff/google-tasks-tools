# Todoist-Google Tasks Sync Tool

## Overview
This tool provides bidirectional synchronization between Todoist and Google Tasks, focusing on priority tasks and tasks with specific labels. It maintains task relationships and propagates completion status between both platforms.

## Core Functionality

### Task Filtering Criteria
Tasks are synced from Todoist to Google Tasks if they meet ALL of the following conditions:

1. **Must have a due date or deadline** - Tasks without timing information are excluded
2. **Must be due within 1 day** - Tasks more than 1 day in the future are filtered out (applies to both regular and recurring tasks)
3. **Must meet priority or label criteria**:
   - Priority tasks: Tasks with priority 2+ (p3, p2, p1 in Todoist UI)
   - Label-based: Tasks containing any of the configured sync labels (default: "urgent", "important", "sync")

### Sync Direction
- **Todoist → Google Tasks**: Creates/updates Google Tasks based on eligible Todoist tasks (title, notes, due dates)
- **Google Tasks → Todoist**: Completion status only - when a Google Task is marked complete, the corresponding Todoist task is automatically completed
- **Due Date Sync**: Due dates only sync from Todoist to Google Tasks. Changes made to due dates in Google Tasks are preserved and will NOT be overwritten by subsequent syncs

### Key Components

#### TaskSyncManager Class
Main orchestrator that handles:
- Configuration management (`sync_config.json`)
- Task ID mappings (`task_mappings.json`) 
- API initialization for both platforms
- Sync logic coordination

#### Core Methods

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

### Configuration Files

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

### Date Handling
- Supports both Todoist `due` dates and `deadline` fields
- When both exist: uses `due` date for Google Task, adds `deadline` to task description
- When only one exists: uses available date for Google Task
- Handles various date formats (ISO strings, date objects)
- Normalizes dates to RFC 3339 format for Google Tasks API

### Error Handling & Logging
- Dual logging: INFO/WARNING to stdout, ERROR/CRITICAL to stderr
- Verbose mode provides detailed sync decision logging
- Graceful handling of API failures and malformed data
- Comprehensive error tracking with stack traces in verbose mode

### Operational Modes
- **One-time sync** (default): Runs a single sync cycle and exits - ideal for cron jobs
- **Daemon mode**: `--daemon` flag enables continuous sync at configured intervals (default 15 minutes)
- **Verbose mode**: `--verbose` for detailed logging

## Usage Commands
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

### Backward Compatibility Note
**Breaking change**: The default behavior has changed. Previously, running `python todoist-sync.py` without flags would run continuous sync, and `--once` was required for a single execution. Now the default is to run once and exit (suitable for cron), and `--daemon` is required for continuous mode. If you have existing automation that relies on the old behavior, add the `--daemon` flag to maintain continuous operation.

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
