#!/usr/bin/env python3
"""
buddy_keepalive.py — Persistent Buddy sim connection manager.

Holds the single TCP connection to the simulator and pushes the current
state every 0.5 seconds. State is driven by buddy_hook.py via ~/.buddy_state.

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
TIME_SYNC_INTERVAL = 3600   # re-sync time every hour


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
            "tool": "", "hint": "", "prompt_id": "", "decision": "",
            "approved": False, "denied_add": 0, "send_approved_add": False,
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


def clear_fields(updates: dict):
    """Atomically update multiple fields in the state file."""
    try:
        current = read_state()
        current.update(updates)
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
        base.update({"running": 1, "waiting": 0, "msg": tool})

    elif state == "attention":
        base.update({"running": 0, "waiting": 1, "msg": ""})
        if prompt_id:
            base["prompt"] = {"id": prompt_id, "tool": tool, "hint": hint}

    elif state == "celebrate":
        base.update({"running": 0, "waiting": 0, "msg": "", "completed": True})
        # Only include approved_add if hook flagged a real buddy approval
        if s.get("send_approved_add"):
            base["approved_add"] = 1

    elif state.startswith("oneshot:"):
        return {"cmd": "oneshot", "state": state.split(":", 1)[1]}

    else:  # idle
        base.update({"running": 0, "waiting": 0, "msg": ""})

    return base


def make_time_payload() -> dict:
    now = int(time.time())
    tz  = -time.timezone if time.daylight == 0 else -time.altzone
    return {"time": [now, tz]}


def send_line(sock, obj: dict):
    line = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
    sock.sendall(line)


def handle_incoming(raw: str):
    """Process a message sent FROM the sim (e.g. permission decisions)."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return
    cmd = obj.get("cmd")
    if cmd == "permission":
        decision = obj.get("decision", "")
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
    last_mtime       = 0.0
    last_time_sync   = 0.0

    while True:
        try:
            with socket.create_connection((SIM_HOST, SIM_PORT), timeout=5.0) as s:
                print("[buddy_keepalive] connected")
                s.settimeout(0.05)
                last_send = 0.0
                rx_buf    = ""

                # Auto time sync on connect
                send_line(s, make_time_payload())
                last_time_sync = time.time()

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

                    # Hourly time re-sync
                    if now - last_time_sync > TIME_SYNC_INTERVAL:
                        send_line(s, make_time_payload())
                        last_time_sync = now

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

                    # ── Drain pending denied_add ──────────────────────────────
                    denied_add = state_obj.get("denied_add", 0)
                    if denied_add > 0:
                        send_line(s, {"denied_add": denied_add})
                        clear_field("denied_add", 0)

                    # ── Celebrate auto-reverts to idle after 3 seconds ────────
                    if state == "celebrate":
                        if celebrate_until == 0.0:
                            celebrate_until = now + 3.0
                    else:
                        celebrate_until = 0.0
                        approved_sent   = False

                    if celebrate_until > 0.0 and now > celebrate_until:
                        celebrate_until = 0.0
                        approved_sent   = False
                        clear_fields({"state": "idle", "send_approved_add": False})
                        state_obj["state"] = "idle"
                        state = "idle"

                    # ── Oneshots send once then revert ────────────────────────
                    if state.startswith("oneshot:"):
                        payload = build_payload(state_obj)
                        clear_field("state", "idle")
                    else:
                        payload = build_payload(state_obj)
                        if state == "celebrate":
                            if approved_sent:
                                payload.pop("approved_add", None)
                            else:
                                approved_sent = True
                                # Clear the flag after sending once
                                if state_obj.get("send_approved_add"):
                                    clear_field("send_approved_add", False)

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
