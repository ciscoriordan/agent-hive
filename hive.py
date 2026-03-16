#!/usr/bin/env python3
"""agent-hive - distributed agent teams via GitHub Issues.

Submit tasks from one machine, execute them on another via Claude Code CLI.
Uses GitHub Issues as the task queue - no git task files, no web server,
no optimistic locking. The GitHub API is the single source of truth.

Usage:
    python hive.py submit "Train model" --target gpu --cwd ~/Documents/iliad-align
    python hive.py watch
    python hive.py status [task-id]
    python hive.py box [name]
    python hive.py register [name]

Requires: gh CLI (authenticated)
"""

import argparse
import json
import os
import platform
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SETTINGS_FILE = Path.home() / ".claude" / "settings.json"
PID_FILE = Path.home() / ".hive-watcher.pid"
LOG_FILE = Path.home() / ".hive-watcher.log"
LAST_TASK_FILE = Path.home() / ".hive-last-task"
NOTIFICATIONS_FILE = Path.home() / ".hive-notifications"

POLL_INTERVAL = 15  # seconds between issue checks
MAX_RETRIES = 3
RETRY_DELAY = 60


# ---------------------------------------------------------------------------
# Box identity
# ---------------------------------------------------------------------------

def get_box_name():
    """Return this machine's box name from settings.json or hostname fallback."""
    name = os.environ.get("HIVE_BOX_NAME", "")
    if name:
        return name
    if SETTINGS_FILE.exists():
        try:
            settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            name = settings.get("env", {}).get("HIVE_BOX_NAME", "")
            if name:
                return name
        except (json.JSONDecodeError, KeyError):
            pass
    return os.environ.get("COMPUTERNAME",
                          os.environ.get("HOSTNAME", "unknown"))


def set_box_name(name):
    """Set box name in ~/.claude/settings.json."""
    settings = {}
    if SETTINGS_FILE.exists():
        try:
            settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    if "env" not in settings:
        settings["env"] = {}
    settings["env"]["HIVE_BOX_NAME"] = name
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2) + "\n",
                             encoding="utf-8")


# ---------------------------------------------------------------------------
# GitHub CLI helpers
# ---------------------------------------------------------------------------

def get_repo():
    """Get the GitHub repo (owner/name) for the current directory."""
    result = subprocess.run(
        ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
        capture_output=True, text=True
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    # Fallback: parse from git remote
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        capture_output=True, text=True
    )
    url = result.stdout.strip()
    # https://github.com/owner/repo.git or git@github.com:owner/repo.git
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def gh_run(args, check=True):
    """Run a gh CLI command and return the result."""
    result = subprocess.run(
        ["gh"] + args,
        capture_output=True, text=True
    )
    if check and result.returncode != 0:
        print(f"gh error: {result.stderr.strip()}", file=sys.stderr)
    return result


def ensure_labels(repo):
    """Create hive labels if they don't exist."""
    labels = {
        "hive": "Agent hive task",
        "pending": "Task waiting to be claimed",
        "in-progress": "Task being executed",
        "complete": "Task finished successfully",
        "error": "Task failed",
    }
    existing = gh_run(
        ["label", "list", "--repo", repo, "--json", "name", "-q", ".[].name"],
    )
    existing_names = set(existing.stdout.strip().split("\n")) if existing.stdout.strip() else set()

    for name, desc in labels.items():
        if name not in existing_names:
            gh_run(["label", "create", name, "--description", desc,
                    "--repo", repo], check=False)


# ---------------------------------------------------------------------------
# Task body format
# ---------------------------------------------------------------------------

def build_body(cwd=None, target=None, after=None, submitter=None):
    """Build issue body with structured metadata."""
    lines = []
    if cwd:
        lines.append(f"**cwd:** `{cwd}`")
    if target:
        lines.append(f"**target:** @{target}")
    if after:
        lines.append(f"**after:** #{after}")
    if submitter:
        lines.append(f"**submitted by:** {submitter}")
    lines.append(f"**submitted:** {datetime.now(timezone.utc).isoformat()}")
    return "\n".join(lines)


def parse_body(body):
    """Parse structured metadata from issue body."""
    meta = {}
    for line in body.split("\n"):
        m = re.match(r"\*\*(\w+):\*\*\s*(.+)", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key == "after":
                val = val.lstrip("#")
            elif key == "cwd":
                val = val.strip("`")
            elif key == "target":
                val = val.lstrip("@")
            meta[key] = val
    return meta


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_submit(args, repo):
    """Submit a new task as a GitHub issue."""
    labels = ["hive", "pending"]
    if args.target:
        # Create target label if needed
        target_label = f"@{args.target}"
        gh_run(["label", "create", target_label, "--description",
                f"Tasks for {args.target}", "--repo", repo], check=False)
        labels.append(target_label)

    body = build_body(
        cwd=args.cwd,
        target=args.target,
        after=args.after,
        submitter=get_box_name(),
    )

    result = gh_run([
        "issue", "create",
        "--repo", repo,
        "--title", args.description,
        "--body", body,
        "--label", ",".join(labels),
    ])

    if result.returncode == 0:
        url = result.stdout.strip()
        issue_num = url.split("/")[-1]
        print(f"Task #{issue_num}: {args.description}")
        if args.target:
            print(f"  Target: @{args.target}")
        if args.cwd:
            print(f"  CWD: {args.cwd}")
        if args.after:
            print(f"  After: #{args.after}")

        # Save for auto-chaining
        LAST_TASK_FILE.write_text(issue_num)
        return issue_num
    return None


def cmd_status(args, repo):
    """Show task status."""
    gh_args = [
        "issue", "list",
        "--repo", repo,
        "--label", "hive",
        "--json", "number,title,labels,state,createdAt",
        "--limit", "50",
    ]
    if args.filter == "open":
        gh_args.extend(["--state", "open"])
    elif args.filter == "closed":
        gh_args.extend(["--state", "closed"])
    else:
        gh_args.extend(["--state", "all"])

    result = gh_run(gh_args)
    if result.returncode != 0:
        return

    issues = json.loads(result.stdout) if result.stdout.strip() else []
    if not issues:
        print("No hive tasks found.")
        return

    for issue in issues:
        num = issue["number"]
        title = issue["title"]
        label_names = [l["name"] for l in issue["labels"]]

        # Determine status from labels
        if "error" in label_names:
            status = "ERROR"
        elif "complete" in label_names:
            status = "DONE"
        elif "in-progress" in label_names:
            status = "RUNNING"
        elif "pending" in label_names:
            status = "PENDING"
        else:
            status = "UNKNOWN"

        target = ""
        for l in label_names:
            if l.startswith("@"):
                target = f" [{l}]"
                break

        print(f"  #{num:4d}  {status:8s}{target}  {title}")


def cmd_watch(args, repo):
    """Watch for and execute tasks assigned to this box."""
    box = get_box_name()
    target_label = f"@{box}"

    if args.daemon:
        _daemonize()

    print(f"Watching for tasks as @{box} on {repo}...")
    print(f"Poll interval: {POLL_INTERVAL}s")

    # Create target label if needed
    gh_run(["label", "create", target_label, "--description",
            f"Tasks for {box}", "--repo", repo], check=False)

    while True:
        try:
            _poll_and_execute(repo, box, target_label)
        except KeyboardInterrupt:
            print("\nWatcher stopped.")
            break
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
        time.sleep(POLL_INTERVAL)


def _poll_and_execute(repo, box, target_label):
    """Check for pending tasks and execute one."""
    # Find pending tasks for this box (targeted or untargeted)
    result = gh_run([
        "issue", "list",
        "--repo", repo,
        "--label", "hive,pending",
        "--state", "open",
        "--json", "number,title,body,labels",
        "--limit", "20",
    ])
    if result.returncode != 0 or not result.stdout.strip():
        return

    issues = json.loads(result.stdout)
    if not issues:
        return

    for issue in issues:
        label_names = [l["name"] for l in issue["labels"]]

        # Check targeting: pick up tasks for this box or untargeted
        targets = [l for l in label_names if l.startswith("@")]
        if targets and target_label not in targets:
            continue  # targeted at a different box

        meta = parse_body(issue["body"])

        # Check dependencies
        after = meta.get("after")
        if after:
            dep_result = gh_run([
                "issue", "view", after,
                "--repo", repo,
                "--json", "state,labels",
            ])
            if dep_result.returncode == 0:
                dep = json.loads(dep_result.stdout)
                dep_labels = [l["name"] for l in dep["labels"]]
                if dep["state"] != "CLOSED" or "complete" not in dep_labels:
                    continue  # dependency not met

        # Claim the task
        num = issue["number"]
        title = issue["title"]
        print(f"\nClaiming #{num}: {title}")

        gh_run([
            "issue", "edit", str(num),
            "--repo", repo,
            "--remove-label", "pending",
            "--add-label", "in-progress",
        ])
        gh_run([
            "issue", "comment", str(num),
            "--repo", repo,
            "--body", f"Claimed by **@{box}** at {datetime.now(timezone.utc).isoformat()}",
        ])

        # Execute
        cwd = meta.get("cwd", ".")
        cwd = os.path.expanduser(cwd)
        success = _execute_task(num, title, cwd, repo)

        if success:
            gh_run([
                "issue", "edit", str(num),
                "--repo", repo,
                "--remove-label", "in-progress",
                "--add-label", "complete",
            ])
            gh_run(["issue", "close", str(num), "--repo", repo])
            _notify(f"Task #{num} complete: {title}")
        else:
            gh_run([
                "issue", "edit", str(num),
                "--repo", repo,
                "--remove-label", "in-progress",
                "--add-label", "error",
            ])
            _notify(f"Task #{num} FAILED: {title}")

        return  # one task per poll cycle


def _execute_task(num, title, cwd, repo):
    """Execute a task via Claude Code CLI."""
    print(f"Executing in {cwd}: {title}")

    try:
        result = subprocess.run(
            ["claude", "-p", title, "--output-format", "text"],
            capture_output=True, text=True, cwd=cwd,
            timeout=3600,  # 1 hour max
        )

        output = result.stdout[-4000:] if len(result.stdout) > 4000 else result.stdout
        if result.stderr:
            output += f"\n\n**stderr:**\n{result.stderr[-1000:]}"

        # Post output as comment
        gh_run([
            "issue", "comment", str(num),
            "--repo", repo,
            "--body", f"**Output from @{get_box_name()}:**\n```\n{output}\n```",
        ])

        return result.returncode == 0

    except subprocess.TimeoutExpired:
        gh_run([
            "issue", "comment", str(num),
            "--repo", repo,
            "--body", f"**Timeout** after 3600s on @{get_box_name()}",
        ])
        return False
    except Exception as e:
        gh_run([
            "issue", "comment", str(num),
            "--repo", repo,
            "--body", f"**Error** on @{get_box_name()}: {e}",
        ])
        return False


def cmd_reset(args, repo):
    """Reset a task back to pending."""
    num = args.task_id
    gh_run([
        "issue", "edit", str(num),
        "--repo", repo,
        "--remove-label", "in-progress,error,complete",
        "--add-label", "pending",
    ])
    gh_run(["issue", "reopen", str(num), "--repo", repo])
    print(f"Task #{num} reset to pending.")


def cmd_box(args, repo):
    """Show or set box name."""
    if args.name:
        set_box_name(args.name)
        print(f"Box name set to: {args.name}")
    else:
        print(f"Box name: {get_box_name()}")


def cmd_register(args, repo):
    """Register this box with the hive."""
    name = args.name or get_box_name()
    target_label = f"@{name}"
    gh_run(["label", "create", target_label, "--description",
            f"Tasks for {name}", "--repo", repo], check=False)
    print(f"Registered @{name} with {repo}")


def cmd_notifications(args, repo):
    """Show and clear notifications."""
    if NOTIFICATIONS_FILE.exists():
        content = NOTIFICATIONS_FILE.read_text(encoding="utf-8").strip()
        if content:
            print(content)
            NOTIFICATIONS_FILE.write_text("", encoding="utf-8")
        else:
            print("No notifications.")
    else:
        print("No notifications.")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _notify(message):
    """Write a notification for the next /hive check."""
    with open(NOTIFICATIONS_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().strftime('%H:%M')}] {message}\n")


def _daemonize():
    """Fork into background (Unix) or spawn detached (Windows)."""
    if platform.system() == "Windows":
        import subprocess as sp
        script = Path(__file__).resolve()
        args = sys.argv[1:]
        args = [a for a in args if a != "--daemon"]
        proc = sp.Popen(
            [sys.executable, str(script)] + args,
            creationflags=sp.DETACHED_PROCESS | sp.CREATE_NEW_PROCESS_GROUP,
            stdout=open(str(LOG_FILE), "w"),
            stderr=subprocess.STDOUT,
        )
        PID_FILE.write_text(str(proc.pid))
        print(f"Watcher started (PID {proc.pid})")
        print(f"Log: {LOG_FILE}")
        sys.exit(0)
    else:
        pid = os.fork()
        if pid > 0:
            PID_FILE.write_text(str(pid))
            print(f"Watcher started (PID {pid})")
            print(f"Log: {LOG_FILE}")
            sys.exit(0)
        # Child
        os.setsid()
        sys.stdout = open(str(LOG_FILE), "w")
        sys.stderr = sys.stdout
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="agent-hive via GitHub Issues")
    parser.add_argument("--repo", help="GitHub repo (owner/name)")
    sub = parser.add_subparsers(dest="command")

    # submit
    p_submit = sub.add_parser("submit")
    p_submit.add_argument("description")
    p_submit.add_argument("--target", "-t")
    p_submit.add_argument("--cwd", default=os.getcwd())
    p_submit.add_argument("--after", "-a")
    p_submit.add_argument("--wait", action="store_true")
    p_submit.add_argument("--no-chain", action="store_true")

    # status
    p_status = sub.add_parser("status")
    p_status.add_argument("filter", nargs="?", default="open")

    # watch
    p_watch = sub.add_parser("watch")
    p_watch.add_argument("--daemon", action="store_true")

    # reset
    p_reset = sub.add_parser("reset")
    p_reset.add_argument("task_id")

    # box
    p_box = sub.add_parser("box")
    p_box.add_argument("name", nargs="?")

    # register
    p_reg = sub.add_parser("register")
    p_reg.add_argument("name", nargs="?")

    # notifications
    sub.add_parser("notifications")

    args = parser.parse_args()
    repo = args.repo or get_repo()
    if not repo:
        print("Could not determine GitHub repo. Use --repo or run from a git directory.",
              file=sys.stderr)
        sys.exit(1)

    ensure_labels(repo)

    commands = {
        "submit": cmd_submit,
        "status": cmd_status,
        "watch": cmd_watch,
        "reset": cmd_reset,
        "box": cmd_box,
        "register": cmd_register,
        "notifications": cmd_notifications,
    }

    if args.command in commands:
        commands[args.command](args, repo)
    else:
        # Default: show status
        args.filter = "open"
        cmd_status(args, repo)


if __name__ == "__main__":
    main()
