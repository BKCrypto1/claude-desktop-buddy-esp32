#!/usr/bin/env python3
"""
buddy_keepalive.py — Persistent Buddy sim connection manager.

Holds the single TCP connection to the simulator and pushes the current
state every 2 seconds. State is driven by buddy_hook.py via ~/.buddy_state.

Also drains any queued commands (state["cmds"]) immediately on each tick.

Run automatically by buddy_hook.py, or manually:
  python3 tools/buddy_keepalive.py
"""

import json
import os
import signal
import socket
import sys
import time

TARGET_FILE = os.path.expanduser("~/.buddy_target")
STATE_FILE  = os.path.expanduser("~/.buddy_state")
SIM_HOST    = "127.0.0.1"
SIM_PORT    = 31415
TICK_S      = 0.5


def get_target() -> str:
    try:
        with open(TARGET_FILE) as f:
            return f.read().strip().lower()
    except FileNotFoundError:
        return "sim"


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


def clear_field(key: str, value):
    """Atomically update one field in the state file."""
    try:
        current = read_state()
        current[key] = value
        with open(STATE_FILE, "w") as f:
            f.write(json.dumps(current))
    except OSError:
        pass


def build_payload(s: dict) -> dict:
    """Build the JSON payload the sim firmware expects from the state dict."""
    state        = s.get("state", "idle")
    tokens       = s.get("tokens", 0)
    tokens_today = s.get("tokens_today", 0)
    tool         = s.get("tool", "")
    hint         = s.get("hint", "")
    prompt_id    = s.get("prompt_id", "")
    entries      = s.get("entries", [])

    base = {
        "total":        1,
        "tokens":       tokens,
        "tokens_today": tokens_today,
        "entries":      entries[-8:],
    }

    if state == "busy":
        base.update({"running": 3, "waiting": 0, "msg": tool})

    elif state == "attention":
        base.update({"running": 0, "waiting": 1, "msg": ""})
        if prompt_id:
            base["prompt"] = {"id": prompt_id, "tool": tool, "hint": hint}

    elif state == "celebrate":
        base.update({"running": 0, "waiting": 0, "msg": "", "completed": True,
                     "approved_add": 1})

    elif state.startswith("oneshot:"):
        # Oneshot bypasses the normal payload
        return {"cmd": "oneshot", "state": state.split(":", 1)[1]}

    else:  # idle
        base.update({"running": 0, "waiting": 0, "msg": ""})

    return base


def send_line(sock, obj: dict):
    line = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
    sock.sendall(line)


def handle_incoming(raw: str):
    """Process a message sent FROM the sim to us (e.g. permission decisions)."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return
    cmd = obj.get("cmd")
    if cmd == "permission":
        decision = obj.get("decision", "")
        # Map device decisions to Claude Code permission decisions
        # "once" or "always" → allow, "deny" → deny
        perm = "allow" if decision in ("once", "always") else "deny"
        clear_field("decision", perm)
        print(f"[buddy_keepalive] permission decision: {decision} → {perm}")


def state_mtime() -> float:
    try:
        return os.stat(STATE_FILE).st_mtime
    except OSError:
        return 0.0


def run_sim():
    print(f"[buddy_keepalive] connecting to sim {SIM_HOST}:{SIM_PORT}")
    celebrate_until  = 0.0
    approved_sent    = False
    last_mtime       = 0.0   # track state file changes for instant sends

    while True:
        try:
            with socket.create_connection((SIM_HOST, SIM_PORT), timeout=5.0) as s:
                print("[buddy_keepalive] connected")
                s.settimeout(0.05)   # non-blocking reads
                last_send = 0.0
                rx_buf    = ""
                while True:
                    now   = time.time()
                    mtime = state_mtime()

                    # Read any incoming data from sim (permission decisions, acks)
                    try:
                        chunk = s.recv(1024).decode("utf-8", errors="replace")
                        if chunk:
                            rx_buf += chunk
                            while "\n" in rx_buf:
                                line, rx_buf = rx_buf.split("\n", 1)
                                line = line.strip()
                                if line:
                                    handle_incoming(line)
                    except socket.timeout:
                        pass
                    except (OSError, ConnectionResetError):
                        raise

                    # Send immediately on state file change, otherwise every TICK_S
                    if mtime == last_mtime and (now - last_send) < TICK_S:
                        continue

                    last_mtime = mtime
                    last_send  = now
                    state_obj  = read_state()
                    state      = state_obj.get("state", "idle")

                    # ── Drain queued commands first ───────────────────────────
                    cmds = state_obj.get("cmds", [])
                    if cmds:
                        for cmd in cmds:
                            send_line(s, cmd)
                            time.sleep(0.05)
                        clear_field("cmds", [])
                        state_obj = read_state()
                        state     = state_obj.get("state", "idle")

                    # ── Celebrate auto-reverts to idle after 3 seconds ────────
                    if state == "celebrate":
                        if celebrate_until == 0.0:
                            celebrate_until = now + 3.0
                    else:
                        celebrate_until  = 0.0
                        approved_sent    = False

                    if celebrate_until > 0.0 and now > celebrate_until:
                        celebrate_until = 0.0
                        approved_sent   = False
                        clear_field("state", "idle")
                        state_obj["state"] = "idle"
                        state = "idle"

                    # ── Oneshots send once then revert ────────────────────────
                    if state.startswith("oneshot:"):
                        payload = build_payload(state_obj)
                        clear_field("state", "idle")
                    else:
                        payload = build_payload(state_obj)
                        # Only send approved_add on the first celebrate tick
                        if state == "celebrate" and approved_sent:
                            payload.pop("approved_add", None)
                        elif state == "celebrate" and not approved_sent:
                            approved_sent = True

                    send_line(s, payload)
                    time.sleep(TICK_S)

        except (ConnectionRefusedError, OSError):
            print("[buddy_keepalive] sim not running, retrying in 5s...")
            time.sleep(5)
        except Exception as e:
            print(f"[buddy_keepalive] error: {e}, reconnecting in 3s...")
            time.sleep(3)


def main():
    signal.signal(signal.SIGINT,  lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    target = get_target()
    if target in ("off", "hardware"):
        print(f"[buddy_keepalive] target={target}, exiting")
        sys.exit(0)

    run_sim()


if __name__ == "__main__":
    main()
