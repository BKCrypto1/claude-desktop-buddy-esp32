#!/usr/bin/env python3
"""
buddy_hook.py — Claude Code hook bridge for Buddy devices.

Reads a Claude Code hook event from stdin (JSON), updates the shared
state file (~/.buddy_state), and ensures the keepalive is running.

State file format:
  {
    "state":        "idle"|"busy"|"attention"|"celebrate"|"oneshot:<name>",
    "tokens":       <session output tokens — sent as cumulative bridge total>,
    "tokens_today": <same value, displayed as today's count>,
    "tool":         "<current tool name>",
    "hint":         "<hint text for prompt>",
    "prompt_id":    "<pending prompt id>",
    "decision":     "allow"|"deny"|"",
    "approved":     <bool — true if buddy approved something this session>,
    "denied_add":   <int — pending denied count increment for keepalive to drain>,
    "entries":      ["Bash:rm -rf", "Edit:foo.py", ...],  # last 8 with hint suffix
    "cmds":         [{"cmd": "..."}, ...]      # one-shot commands for keepalive to drain
  }

Usage (called automatically by Claude Code hooks):
    python3 /path/to/buddy_hook.py <EventType>
"""

import json
import os
import re
import subprocess
import sys
import time

TARGET_FILE   = os.path.expanduser("~/.buddy_target")
STATE_FILE    = os.path.expanduser("~/.buddy_state")
KEEPALIVE_PID = os.path.expanduser("~/.buddy_keepalive.pid")

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
KEEPALIVE = os.path.join(TOOLS_DIR, "buddy_keepalive.py")

APPROVAL_TIMEOUT = 30   # seconds before auto-allow

# Only these tools block for approval — everything else is informational only
APPROVAL_GATE = {"Bash", "Agent"}

# Bash commands that are read-only/safe — skip approval, auto-allow instantly
SAFE_BASH_PREFIXES = (
    "grep", "rg", "find", "ls", "cat", "head", "tail", "wc", "diff",
    "sed -n", "awk", "sort", "uniq", "echo", "pwd", "which", "file",
    "git log", "git status", "git diff", "git show", "git branch",
    "python3 -c", "node -e", "jq",
)


# ── Target ────────────────────────────────────────────────────────────────────

def get_target() -> str:
    try:
        with open(TARGET_FILE) as f:
            return f.read().strip().lower()
    except FileNotFoundError:
        return "sim"


# ── State file ────────────────────────────────────────────────────────────────

def read_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.loads(f.read().strip())
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return {
            "state": "idle", "tokens": 0, "tokens_today": 0,
            "tool": "", "hint": "", "prompt_id": "", "decision": "",
            "approved": False, "denied_add": 0,
            "entries": [], "cmds": [],
        }


def write_state(update: dict):
    current = read_state()
    current.update(update)
    try:
        with open(STATE_FILE, "w") as f:
            f.write(json.dumps(current))
    except OSError as e:
        print(f"[buddy_hook] could not write state: {e}", file=sys.stderr)


# ── Keepalive ─────────────────────────────────────────────────────────────────

def ensure_keepalive():
    pid = None
    try:
        with open(KEEPALIVE_PID) as f:
            pid = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        pass

    if pid:
        try:
            os.kill(pid, 0)
            return
        except (ProcessLookupError, OSError):
            pass

    proc = subprocess.Popen(
        [sys.executable, KEEPALIVE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    with open(KEEPALIVE_PID, "w") as f:
        f.write(str(proc.pid))


# ── Token counting ────────────────────────────────────────────────────────────

def read_session_tokens(transcript_path: str) -> int:
    """Sum output_tokens from all assistant messages in this session's transcript."""
    total = 0
    try:
        with open(transcript_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    usage = entry.get("message", {}).get("usage", {})
                    if isinstance(usage, dict):
                        total += usage.get("output_tokens", 0)
                except (json.JSONDecodeError, AttributeError):
                    pass
    except (FileNotFoundError, OSError):
        pass
    return total


# ── Entries (rolling tool list with hint suffix) ──────────────────────────────

def push_entry(entries: list, tool_name: str, hint: str = "") -> list:
    """Add 'Tool:hint' to entries, keep last 8."""
    if not tool_name:
        return entries
    entries = list(entries)
    if hint:
        # Normalize hint: strip comments, collapse whitespace, keep first line
        first_line = hint.split("\n")[0].strip()
        first_line = re.sub(r"^#+\s*", "", first_line)   # strip leading # comments
        first_line = re.sub(r"\s+", " ", first_line)
        label = f"{tool_name}:{first_line}"[:22]
    else:
        label = tool_name[:22]
    entries.append(label)
    return entries[-8:]


# ── Safe bash check ───────────────────────────────────────────────────────────

def is_safe_bash(raw_cmd: str) -> bool:
    """Return True if the bash command is read-only and needs no approval."""
    # Strip comment lines and blank lines, find first real command token
    for line in raw_cmd.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            # Check against the first token / prefix of the first real line
            return any(stripped.startswith(p) for p in SAFE_BASH_PREFIXES)
    return True  # all lines were comments — safe


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <EventType>", file=sys.stderr)
        sys.exit(1)

    event_type = sys.argv[1]

    try:
        raw     = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, ValueError):
        payload = {}

    target = get_target()
    if target == "off":
        sys.exit(0)

    if target in ("sim", "desktop"):
        ensure_keepalive()

    current         = read_state()
    entries         = current.get("entries", [])
    transcript_path = payload.get("transcript_path", "")
    tool_name       = payload.get("tool_name", "") or payload.get("tool", "")

    if transcript_path:
        tokens_today = read_session_tokens(transcript_path)
    else:
        tokens_today = current.get("tokens_today", 0)

    et = event_type.lower()

    if et == "pretooluse":
        tool_input = payload.get("tool_input", {}) or {}
        if isinstance(tool_input, dict):
            if "command" in tool_input:
                hint = tool_input["command"][:80]   # longer for safe-check accuracy
            elif "file_path" in tool_input:
                hint = os.path.basename(tool_input.get("file_path", ""))[:43]
            else:
                pairs = ", ".join(f"{k}={v}" for k, v in list(tool_input.items())[:2])
                hint = pairs[:43]
        else:
            hint = str(tool_input)[:43]

        entries = push_entry(entries, tool_name, hint)
        hint_short = hint[:43]   # firmware limit

        needs_approval = (
            tool_name in APPROVAL_GATE and
            not (tool_name == "Bash" and is_safe_bash(hint))
        )

        if needs_approval:
            pid = "desk_%d" % int(time.time() * 1000)

            write_state({
                "state":        "attention",
                "tokens":       tokens_today,
                "tokens_today": tokens_today,
                "tool":         tool_name,
                "hint":         hint_short,
                "prompt_id":    pid,
                "decision":     "",
                "entries":      entries,
            })

            # Wait for buddy decision (up to APPROVAL_TIMEOUT seconds).
            deadline = time.time() + APPROVAL_TIMEOUT
            decision = ""
            while time.time() < deadline:
                time.sleep(0.1)
                s = read_state()
                if s.get("prompt_id") == pid and s.get("decision"):
                    decision = s["decision"]
                    break

            if decision == "deny":
                # Signal denied count increment and dizzy oneshot to keepalive
                write_state({
                    "denied_add": current.get("denied_add", 0) + 1,
                    "state":      "oneshot:dizzy",
                    "prompt_id":  "",
                })
                print(json.dumps({"hookSpecificOutput": {"permissionDecision": "deny"}}))
            elif decision == "allow":
                # Mark that a real buddy approval happened this session
                write_state({"approved": True, "prompt_id": ""})
                print(json.dumps({"hookSpecificOutput": {"permissionDecision": "allow"}}))
            else:
                # Timeout — signal with dizzy, default to allow
                write_state({
                    "state":     "oneshot:dizzy",
                    "prompt_id": "",
                })
                print(json.dumps({"hookSpecificOutput": {"permissionDecision": "allow"}}))
        else:
            write_state({
                "state":        "busy",
                "tokens":       tokens_today,
                "tokens_today": tokens_today,
                "tool":         tool_name,
                "hint":         hint_short,
                "entries":      entries,
            })
            # Return allow for Bash so Claude's own permission dialog never fires
            if tool_name == "Bash":
                print(json.dumps({"hookSpecificOutput": {"permissionDecision": "allow"}}))

    elif et == "posttooluse":
        write_state({
            "state":        "busy",
            "tokens":       tokens_today,
            "tokens_today": tokens_today,
            "tool":         tool_name,
            "hint":         "",
            "prompt_id":    "",
            "entries":      entries,
        })

    elif et == "stop":
        # Only send approved_add if a real buddy approval happened this session
        was_approved = current.get("approved", False)
        write_state({
            "state":        "celebrate",
            "tokens":       tokens_today,
            "tokens_today": tokens_today,
            "entries":      entries,
            "approved":     False,   # reset for next session
            "send_approved_add": was_approved,
        })

    elif et == "notification":
        # Show attention animation but NO prompt_id — notifications don't block
        # and the approval screen should never show for them.
        message    = payload.get("message", "")
        prior_tool = current.get("tool", "") or tool_name or "Claude"
        hint       = message[:43] or prior_tool
        write_state({
            "state":        "attention",
            "tokens":       tokens_today,
            "tokens_today": tokens_today,
            "tool":         prior_tool,
            "hint":         hint,
            "prompt_id":    "",   # no approval screen for notifications
            "entries":      entries,
        })

    else:
        write_state({
            "state":        "idle",
            "tokens":       tokens_today,
            "tokens_today": tokens_today,
            "entries":      entries,
        })


if __name__ == "__main__":
    main()
