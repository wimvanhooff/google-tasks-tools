---
id: task-1
title: >-
  Introduce daemon mode on @todoist-sync.py and make the default behaviour to
  run once
status: Done
assignee: []
created_date: '2025-11-14 09:53'
updated_date: '2025-11-14 09:59'
labels: []
dependencies: []
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Currently, the script runs continuously by default (checking every 15 minutes), and users must pass `--once` to run a single sync. This should be reversed to make the tool more suitable for cron/scheduled jobs.

**Change:**
- Default behavior: Run sync once and exit
- New `--daemon` flag: Enable continuous mode with interval-based syncing

**Motivation:**
Better for cron/scheduled jobs - makes it easier to run from cron or other schedulers without needing the `--once` flag every time.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Running `python todoist-sync.py` (no flags) executes one sync and exits
- [x] #2 Running `python todoist-sync.py --daemon` starts continuous sync mode with configured interval
- [x] #3 The `--once` flag is removed or deprecated
- [x] #4 Existing `sync_interval_minutes` config still applies when in daemon mode
- [x] #5 Help text and documentation (CLAUDE.md) updated to reflect new default behavior
- [x] #6 Backward compatibility note added if needed
<!-- AC:END -->
