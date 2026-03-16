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

## Box names

Each machine gets a short name used for task routing. Pick something
descriptive - `mac`, `gpu`, `desktop`, `server`, etc. The name becomes a
GitHub label (`@mac`, `@gpu`) so tasks can target specific machines.

Box names are stored in `~/.claude/settings.json` under `HIVE_BOX_NAME`
and persist across sessions. You set the name once during setup.

## Setup

On each machine, run `/hive setup` in Claude Code. It will prompt for a box
name and start watching for tasks.

```
/hive setup
```

That's it. On subsequent sessions, `/hive watch` resumes the watcher.

## Which repo?

The hive uses whichever GitHub repo you're in when you run commands. Issues
are created on that repo. If you want a single task queue across projects,
pick one repo as the hub and always submit from there. If you want per-project
queues, submit from each repo separately.

The `--cwd` flag tells the watcher which directory to execute in, so tasks
can target any local path regardless of which repo hosts the issue.

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

## Restricting watcher permissions

By default, watchers run with full Claude Code access. To restrict what tools
a watcher can use:

```
/hive watch --allowedTools Bash,Read,Write,Grep
```

This passes `--allowedTools` to the `claude` CLI for every task the watcher
executes. Useful for limiting a box to read-only operations or preventing
file writes on a shared machine.

## Security

agent-hive is designed for small, trusted teams where you control all the
machines. Anyone who can create issues on your repo can submit tasks that
execute code on your watchers. Do not run watchers on repos with untrusted
collaborators.

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
