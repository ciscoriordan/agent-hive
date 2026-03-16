---
name: hive
description: "Distributed agent teams via GitHub Issues. Submit tasks to remote workers, check status, or start watching for incoming tasks. Use when the user wants to send work to another machine (GPU training, platform-specific builds, etc), check on remote tasks, or set up hive."
disable-model-invocation: true
argument-hint: <command> [@box] [args]
allowed-tools: Bash, Read, Write, Grep, Glob, AskUserQuestion
---

Distributed agent teams via GitHub Issues. Tasks are GitHub Issues with labels
for routing and status. Workers on different machines watch for pending issues
and execute them via Claude Code CLI.

**IMPORTANT:** Never show `python hive.py` commands to the user. All user-facing
output must use `/hive` commands only.

**Arguments:** $ARGUMENTS

## Argument Parsing

The first word of `$ARGUMENTS` is the **command**: `submit`, `status`, `setup`,
`watch`, `stop`, `rename`, `reset`. If no command is given (bare `/hive`), show the overview.

**Modifiers** (can appear in any order after the command):
- `@boxname` - route task to a specific machine
- `(after:issue-number)` - declare dependency on another task

Examples:
- `/hive submit Train the model` - submit, any watcher picks it up
- `/hive submit @gpu Train the model` - route to the gpu box
- `/hive submit @gpu Train model in ~/Documents/iliad-align` - specify working dir
- `/hive submit @mac Rebuild iOS (after:42)` - depends on issue #42
- `/hive rename gpu` - rename this machine to "gpu"

When parsing arguments:
- Extract `@boxname` if present (pass as `--target`)
- Extract `(after:number)` if present (pass as `--after`)
- If the description mentions working in a specific directory, extract it and pass as `--cwd`
- Remaining text is the task description

## Finding hive.py

Look for `hive.py` in:
1. `~/Documents/agent-hive/hive.py`
2. The current working directory
3. Parent directories of the current working directory

---

## Commands

### No command (bare `/hive`) - Overview

1. Find hive.py.
2. If not found, suggest setup.
3. If found:
   - Run `python <path-to-hive.py> notifications` and display any alerts
   - Run `python <path-to-hive.py> status`
   - Show the current box name
   - Check if a watcher is running (read `~/.hive-watcher.pid`, verify process alive)
   - List available commands

### `rename` - Rename this machine

```bash
python <path-to-hive.py> box <name>
```

### `submit` - Submit a task

1. Parse `@boxname` and `(after:number)` from arguments.
2. Find hive.py.
3. Determine `--cwd` from context (mentioned directory, or current working directory).
4. Build the submit command:
   ```bash
   python <path-to-hive.py> submit "<task description>" --cwd <dir> [--target <box>] [--after <num>]
   ```
5. Report the issue number, target box, and working directory.

### `status` - Check task status

```bash
python <path-to-hive.py> status [open|closed|all]
```

### `watch` - Start watching for tasks

1. Ensure this box is registered:
   ```bash
   python <path-to-hive.py> register
   ```
2. Start the watcher:
   ```bash
   python <path-to-hive.py> watch --daemon
   ```

### `stop` - Stop watching

1. Read PID from `~/.hive-watcher.pid`.
2. Kill the process.
3. Remove the PID file.

### `reset` - Reset a task

```bash
python <path-to-hive.py> reset <issue-number>
```

---

## Setup flow

If hive.py is not found or `/hive setup` is called:

1. Ask for box name (use AskUserQuestion).
2. Set the name: `python <path-to-hive.py> box <name>`
3. Register: `python <path-to-hive.py> register`
4. Start watching: `python <path-to-hive.py> watch --daemon`

The hive repo itself is just agent-hive. Tasks live as GitHub Issues on
whatever repo you run commands from (auto-detected from git remote).
