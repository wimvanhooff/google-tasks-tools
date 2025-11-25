# Google Tasks Tools

This repository contains a collection of tools for working with Google Tasks. For detailed documentation, see [CLAUDE.md](CLAUDE.md).

## Tools Overview

### 1. Todoist-Google Tasks Sync (`todoist-sync.py`)
Bidirectional synchronization between Todoist and Google Tasks, focusing on priority tasks and tasks with specific labels.

**Key Features:**
- Syncs priority tasks (p3, p2, p1) and labeled tasks
- Filters to tasks due within 1 day
- Bidirectional completion sync
- One-time or daemon mode

**Quick Start:**
```bash
python3 todoist-sync.py --dry-run --verbose
```

### 2. Todoist to Google Tasks Project Sync (`todoist-to-gtasks.py`)
One-way sync from Todoist projects to Google Tasks lists, maintaining a complete mirror of your Todoist structure.

**Key Features:**
- Syncs ALL tasks from Todoist projects to corresponding Google Tasks lists
- Automatically creates lists for each project
- Handles inbox tasks separately
- Supports recurring tasks (integrates with gtasks-recurring.py)
- Can sync single projects with `--project` flag

**Quick Start:**
```bash
python3 todoist-to-gtasks.py --dry-run --limit 10 --verbose
```

### 3. Recurring Tasks Tool (`gtasks-recurring.py`)
Implements repeat-after-completion functionality for Google Tasks.

**Key Features:**
- Detects `every! X days` directive in task notes
- Creates new task X days after completion
- Completion-based recurring (not calendar-based)
- Works with tasks synced from Todoist

**Quick Start:**
```bash
python3 gtasks-recurring.py --dry-run --verbose
```

### 4. Tasks to TRMNL Sync (`gtasks-trmnl.py`)
Syncs tasks tagged with `#trmnl` in their notes from all Google Tasks lists into a consolidated "TRMNL" list.

**Key Features:**
- Detects `#trmnl` hashtag in task notes (case-insensitive)
- Removes `#trmnl` tag from TRMNL copies for clean display
- One-way sync (original lists → TRMNL)
- Auto-cleanup when tasks are untagged, deleted, or completed
- Does not sync due dates (avoids duplicate calendar entries)
- Perfect for TRMNL e-ink displays

**Quick Start:**
```bash
python3 gtasks-trmnl.py --dry-run --verbose
```

## Environment Setup

### Prerequisites
- Python 3.7+
- pip package manager

### Installation

1. **Clone the repository**
   ```bash
   cd /path/to/google-tasks-tools
   ```

2. **Create virtual environment**
   ```bash
   python3 -m venv todoist-sync-env
   ```

3. **Activate virtual environment**
   ```bash
   source todoist-sync-env/bin/activate
   ```

4. **Install dependencies**
   ```bash
   pip install todoist-api-python google-api-python-client google-auth-oauthlib google-auth-httplib2
   ```

### Google Cloud Console Setup

All tools that use Google Tasks API require OAuth2 credentials:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable the **Google Tasks API**
4. Go to **Credentials** → **Create Credentials** → **OAuth client ID**
5. Choose **Desktop application**
6. Download the JSON file and save as `credentials.json` in the project directory

First run will open browser for OAuth consent and save token to `token.json` for future use.

### Todoist API Token

For tools that sync with Todoist (`todoist-sync.py`, `todoist-to-gtasks.py`):

1. Go to [Todoist Integrations](https://todoist.com/prefs/integrations)
2. Copy your API token
3. Add to the tool's configuration file

## Configuration

Each tool uses its own configuration file with a `.template` version provided:

- `todoist-sync.conf` / `todoist-sync.conf.template`
- `todoist-to-gtasks.conf` / `todoist-to-gtasks.conf.template`
- `gtasks-recurring.conf` / `gtasks-recurring.conf.template`
- `gtasks-trmnl.conf` / `gtasks-trmnl.conf.template`

Configuration files use a simple `key = value` format with `#` comments:
```
# Example configuration
todoist_token = your_api_token_here
google_credentials_file = credentials.json
sync_labels = urgent, important, sync
sync_interval_minutes = 15
```

Configuration files are auto-created on first run, or you can copy from templates:
```bash
cp todoist-sync.conf.template todoist-sync.conf
```

## Usage Patterns

All tools support similar command-line patterns:

```bash
# One-time execution (default, ideal for cron jobs)
python3 script.py

# Dry-run mode (preview without making changes)
python3 script.py --dry-run

# Verbose logging (detailed output)
python3 script.py --verbose

# Daemon mode (continuous sync at intervals)
python3 script.py --daemon

# Custom configuration file
python3 script.py --config my_config.conf

# Combine options
python3 script.py --dry-run --verbose
python3 script.py --daemon --verbose
```

## Automation with Cron

Run automatically every 15 minutes:

```bash
# Edit crontab
crontab -e

# Add entries for the tools you want to automate
*/15 * * * * cd /path/to/google-tasks-tools && source todoist-sync-env/bin/activate && python3 todoist-sync.py >> sync.log 2>&1
*/15 * * * * cd /path/to/google-tasks-tools && source todoist-sync-env/bin/activate && python3 todoist-to-gtasks.py >> project_sync.log 2>&1
*/15 * * * * cd /path/to/google-tasks-tools && source todoist-sync-env/bin/activate && python3 gtasks-recurring.py >> recurring.log 2>&1
*/15 * * * * cd /path/to/google-tasks-tools && source todoist-sync-env/bin/activate && python3 gtasks-trmnl.py >> trmnl_sync.log 2>&1
```

Or use daemon mode with systemd/supervisor for continuous operation.

## Common Workflows

### Workflow 1: Complete Todoist → Google Tasks Mirror
```bash
# Sync all Todoist projects to Google Tasks
python3 todoist-to-gtasks.py

# Handle completion-based recurring tasks
python3 gtasks-recurring.py
```

### Workflow 2: Priority Tasks Only
```bash
# Sync only high-priority tasks due soon
python3 todoist-sync.py

# Bidirectional completion sync
```

### Workflow 3: TRMNL Display
```bash
# Tag important tasks across all lists with #trmnl in notes
# Sync to consolidated TRMNL list
python3 gtasks-trmnl.py
```

### Workflow 4: Complete System
```bash
# Run all tools for comprehensive sync
python3 todoist-to-gtasks.py      # Mirror all Todoist projects
python3 todoist-sync.py            # Sync priority tasks bidirectionally
python3 gtasks-recurring.py        # Handle recurring tasks
python3 gtasks-trmnl.py            # Consolidate starred tasks
```

## Tool-Specific Features

### todoist-to-gtasks.py Extras
- `--project "Name"` - Sync only a specific project
- `--limit N` - Sync only first N tasks (testing)
- Supports `every!` syntax for recurring tasks

### gtasks-trmnl.py Notes
- Requires pre-created "TRMNL" list in Google Tasks
- Uses `#trmnl` hashtag in task notes (case-insensitive)
- Automatically removes `#trmnl` tag from TRMNL copies for clean display
- Does not sync due dates to avoid duplicate calendar entries

### gtasks-recurring.py Integration
- Works seamlessly with tasks synced from Todoist
- Detects `every! X days` in task notes
- Creates new occurrence X days after completion

## Data Storage

Each tool maintains its own mapping files to track relationships:

- `todoist-sync-mappings.json` - Todoist ↔ Google Tasks mappings
- `todoist-to-gtasks-mappings.json` - Project/task mappings
- `gtasks-trmnl-mappings.json` - Original task ↔ TRMNL task mappings

These files are auto-generated and should not be manually edited.

## Troubleshooting

### "No module named 'google'" error
Activate the virtual environment:
```bash
source todoist-sync-env/bin/activate
```

### OAuth consent screen
First run opens browser for Google OAuth. This is normal. Token is saved for future use.

### "TRMNL list not found"
For `gtasks-trmnl.py`, create the "TRMNL" list manually in Google Tasks first.

### Credentials expired
Delete `token.json` and run again to re-authenticate:
```bash
rm token.json
python3 script.py
```

## Documentation

See [CLAUDE.md](CLAUDE.md) for comprehensive documentation including:
- Detailed feature descriptions
- Configuration options
- API behavior and limitations
- Integration patterns
- Example workflows

## License

MIT License - See individual script headers for details.

## Contributing

This is a personal toolset. Feel free to fork and adapt for your needs.

## Support

For issues or questions, see the troubleshooting section above or consult [CLAUDE.md](CLAUDE.md) for detailed documentation.
