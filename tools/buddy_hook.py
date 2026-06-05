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
    "entries":      ["tool1", "tool2", ...],   # last 8 tool uses
    "cmds":         [{"cmd": "..."}, ...]      # one-shot commands for keepalive to drain
  }

Usage (called automatically by Claude Code hooks):
    python3 /path/to/buddy_hook.py <EventType>
"""

import json
import os
import subprocess
import sys
import time

TARGET_FILE   = os.path.expanduser("~/.buddy_target")
STATE_FILE    = os.path.expanduser("~/.buddy_state")
KEEPALIVE_PID = os.path.expanduser("~/.buddy_keepalive.pid")

TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
KEEPALIVE = os.path.join(TOOLS_DIR, "buddy_keepalive.py")


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
            "tool": "", "hint": "", "prompt_id": "",
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


# ── Entries (rolling tool list) ───────────────────────────────────────────────

def push_entry(entries: list, tool_name: str) -> list:
    """Add tool_name to entries, keep last 8."""
    if tool_name:
        entries = list(entries)
        entries.append(tool_name)
        entries = entries[-8:]
    return entries


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

    # Read real token count from transcript if available
    if transcript_path:
        tokens_today = read_session_tokens(transcript_path)
    else:
        tokens_today = current.get("tokens_today", 0)

    et = event_type.lower()

    if et == "pretooluse":
        entries = push_entry(entries, tool_name)
        # Extract a human-readable hint from tool_input for the approval prompt
        tool_input = payload.get("tool_input", {}) or {}
        if isinstance(tool_input, dict):
            # Bash: show the command; others: show key=value pairs
            if "command" in tool_input:
                hint = tool_input["command"][:43]
            elif "file_path" in tool_input:
                hint = os.path.basename(tool_input.get("file_path", ""))[:43]
            else:
                pairs = ", ".join(f"{k}={v}" for k, v in list(tool_input.items())[:2])
                hint = pairs[:43]
        else:
            hint = str(tool_input)[:43]

        write_state({
            "state":        "busy",
            "tokens":       tokens_today,
            "tokens_today": tokens_today,
            "tool":         tool_name,
            "hint":         hint,
            "entries":      entries,
        })

    elif et == "posttooluse":
        entries = push_entry(entries, tool_name)
        write_state({
            "state":        "celebrate",
            "tokens":       tokens_today,
            "tokens_today": tokens_today,
            "tool":         tool_name,
            "entries":      entries,
        })

    elif et == "stop":
        write_state({
            "state":        "celebrate",
            "tokens":       tokens_today,
            "tokens_today": tokens_today,
            "entries":      entries,
        })

    elif et == "notification":
        # Use hint already stored from the PreToolUse (actual command/path)
        # Fall back to notification message if no prior hint
        prior_hint = current.get("hint", "")
        prior_tool = current.get("tool", "") or tool_name
        message    = payload.get("message", "")
        hint       = prior_hint or message[:43] or prior_tool
        pid        = "desk_%d" % int(time.time() * 1000)
        write_state({
            "state":        "attention",
            "tokens":       tokens_today,
            "tokens_today": tokens_today,
            "tool":         prior_tool,
            "hint":         hint,
            "prompt_id":    pid,
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
