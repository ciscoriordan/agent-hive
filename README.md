# agent-hive

Run Claude Code tasks on remote machines. Submit from your main workstation, execute on others (e.g. a Windows box with GPU). GitHub Issues is the task queue - labels for routing, comments for output, no infrastructure to set up.

## How it works

Each machine runs a watcher that polls GitHub Issues for pending tasks and
executes them via Claude Code CLI. Labels route tasks to specific machines,
comments capture output. Submit from anywhere, execute anywhere.

<p align="center">
  <img src="assets/architecture.svg" width="800" alt="agent-hive architecture: MacBook Pro submits tasks via GitHub Issues, Windows GPU Box claims and executes them">
</p>

## Requirements

Every machine (submitter and watcher) needs both:

- **`gh` CLI** (authenticated): `gh auth login`
- **Claude Code CLI**: `claude`

## Setup

On each machine, run `/hive setup` in Claude Code. It will prompt for a box
name and start watching for tasks.

```
/hive setup
```

That's it. On subsequent sessions, `/hive watch` resumes the watcher.

## Commands

| Command | Description |
|---------|-------------|
| `/hive` | Show task queue and watcher status |
| `/hive setup` | First-time setup: name this machine, start watching |
| `/hive submit @gpu Train the model` | Submit a task to the GPU box |
| `/hive submit Rebuild iOS (after:42)` | Task depends on #42 |
| `/hive status` | Show open tasks |
| `/hive watch` | Start watching for tasks |
| `/hive stop` | Stop the watcher |
| `/hive rename gpu` | Rename this machine |
| `/hive reset 42` | Reset task #42 to pending |

## Labels

Tasks are GitHub Issues with these labels:

| Label | Meaning |
|-------|---------|
| `hive` | All hive tasks have this label |
| `pending` | Waiting to be claimed |
| `in-progress` | Being executed by a watcher |
| `complete` | Finished successfully (issue closed) |
| `error` | Execution failed |
| `@gpu`, `@mac` | Route to a specific box |

## Task routing

- `--target gpu` adds the `@gpu` label. Only the GPU watcher picks it up.
- Without `--target`, any watcher can claim it.
- Dependencies: `--after 42` blocks until issue #42 is closed with `complete`.

## As a Claude Code skill

Copy `SKILL.md` to use `/hive` commands in Claude Code conversations.
The skill translates `/hive submit @gpu Train model` into the appropriate
`python hive.py` calls.

## Compared to git task files

The previous version used git-tracked markdown files with optimistic locking
via `git push`. This version uses GitHub Issues instead:

| | Git task files | GitHub Issues |
|---|---|---|
| State transitions | Race-prone (git push) | Atomic (API) |
| UI | Custom web server | GitHub.com / mobile app |
| Notifications | Custom file-based | GitHub email/push |
| Filtering | grep | Labels + search |
| History | git log | Issue timeline |
| Dependencies | Custom parsing | Issue references |

## License

MIT
