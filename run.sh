#!/bin/bash

# Google Tasks Tools Runner
# Usage: ./run.sh [script] [args...]
#
# Available scripts:
#   todoist-sync        - Bidirectional sync between Todoist and Google Tasks
#   todoist-to-gtasks   - One-way sync from Todoist projects to Google Tasks lists
#   gtasks-recurring    - Handle recurring tasks in Google Tasks
#   gtasks-trmnl        - Sync starred tasks to TRMNL list
#
# Examples:
#   ./run.sh todoist-sync --verbose
#   ./run.sh todoist-to-gtasks --dry-run --limit 5
#   ./run.sh gtasks-recurring --daemon
#   ./run.sh gtasks-trmnl --dry-run --verbose

set -e

# Activate virtual environment
source todoist-sync-env/bin/activate

# Check if a script argument was provided
if [ $# -eq 0 ]; then
    echo "Usage: $0 [script] [args...]"
    echo ""
    echo "Available scripts:"
    echo "  todoist-sync        - Bidirectional sync between Todoist and Google Tasks"
    echo "  todoist-to-gtasks   - One-way sync from Todoist projects to Google Tasks lists"
    echo "  gtasks-recurring    - Handle recurring tasks in Google Tasks"
    echo "  gtasks-trmnl        - Sync starred tasks to TRMNL list"
    echo ""
    echo "Examples:"
    echo "  $0 todoist-sync --verbose"
    echo "  $0 todoist-to-gtasks --dry-run --limit 5"
    echo "  $0 gtasks-recurring --daemon"
    echo "  $0 gtasks-trmnl --dry-run --verbose"
    exit 1
fi

SCRIPT=$1
shift  # Remove first argument, leaving any additional args

case "$SCRIPT" in
    todoist-sync)
        python3 todoist-sync.py "$@"
        ;;
    todoist-to-gtasks)
        python3 todoist-to-gtasks.py "$@"
        ;;
    gtasks-recurring)
        python3 gtasks-recurring.py "$@"
        ;;
    gtasks-trmnl)
        python3 gtasks-trmnl.py "$@"
        ;;
    *)
        echo "Error: Unknown script '$SCRIPT'"
        echo ""
        echo "Available scripts:"
        echo "  todoist-sync"
        echo "  todoist-to-gtasks"
        echo "  gtasks-recurring"
        echo "  gtasks-trmnl"
        exit 1
        ;;
esac
