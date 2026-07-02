#!/usr/bin/env python3
"""
buddy_ble_keepalive.py — Persistent BLE connection manager for real hardware.

Hardware-mode counterpart to buddy_keepalive.py: instead of a TCP socket to
the simulator, this holds a single BLE GATT connection (Nordic UART Service)
to the paired Buddy device and pushes the current state every 0.5 seconds.
State is driven by buddy_hook.py via ~/.buddy_state — same wire protocol as
the TCP path (newline-delimited JSON), since main.cpp's dataPoll() feeds
both USB serial and BLE bytes into the same parser.

Requires the device address to already be cached at ~/.buddy_ble_addr
(written by tools/ble_driver.py on first successful pair/upload).

Run automatically by sim_driver.py in hardware mode, or manually:
  python3 tools/buddy_ble_keepalive.py
"""

import asyncio
import json
import os
import signal
import sys
import time

TARGET_FILE = os.path.expanduser("~/.buddy_target")
STATE_FILE  = os.path.expanduser("~/.buddy_state")
ADDR_FILE   = os.path.expanduser("~/.buddy_ble_addr")
TICK_S      = 0.5
TIME_SYNC_INTERVAL = 3600   # re-sync time every hour
RECONNECT_DELAY_S  = 5.0

NUS_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # write: host -> device
NUS_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # notify: device -> host


def get_target() -> str:
    try:
        with open(TARGET_FILE) as f:
            return f.read().strip().lower()
    except FileNotFoundError:
        return "sim"


def get_address():
    try:
        with open(ADDR_FILE) as f:
            addr = f.read().strip()
            return addr or None
    except FileNotFoundError:
        return None


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
    try:
        current = read_state()
        current[key] = value
        with open(STATE_FILE, "w") as f:
            f.write(json.dumps(current))
    except OSError:
        pass


def clear_fields(updates: dict):
    try:
        current = read_state()
        current.update(updates)
        with open(STATE_FILE, "w") as f:
            f.write(json.dumps(current))
    except OSError:
        pass


def build_payload(s: dict) -> dict:
    """Build the JSON payload the firmware expects from the state dict.
    Identical shape to buddy_keepalive.py's build_payload — the firmware
    parses the same wire format regardless of transport."""
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


def handle_incoming(raw: str):
    """Process a message notified FROM the device (e.g. permission decisions)."""
    try:
        obj = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return
    cmd = obj.get("cmd")
    if cmd == "permission":
        decision = obj.get("decision", "")
        perm = "allow" if decision in ("once", "always") else "deny"
        clear_field("decision", perm)
        print(f"[buddy_ble_keepalive] permission decision: {decision} → {perm}")


def state_mtime() -> float:
    try:
        return os.stat(STATE_FILE).st_mtime
    except OSError:
        return 0.0


class _LineAssembler:
    """Reassembles newline-delimited JSON lines from chunked BLE notifies."""
    def __init__(self, on_line):
        self._buf = ""
        self._on_line = on_line

    def feed(self, data: bytes):
        self._buf += data.decode("utf-8", errors="replace")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line:
                self._on_line(line)


async def _write_line(client, mtu_chunk: int, obj: dict):
    line = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
    for i in range(0, len(line), mtu_chunk):
        await client.write_gatt_char(NUS_RX_UUID, line[i:i + mtu_chunk], response=False)


async def run_ble():
    from bleak import BleakClient
    from bleak.exc import BleakError

    print("[buddy_ble_keepalive] starting")
    celebrate_until = 0.0
    approved_sent   = False
    last_mtime      = 0.0

    while True:
        target = get_target()
        if target != "hardware":
            print(f"[buddy_ble_keepalive] target={target}, exiting")
            return

        address = get_address()
        if not address:
            print("[buddy_ble_keepalive] no cached device address "
                  f"({ADDR_FILE}) — pair via ble_driver.py first, retrying in 5s")
            await asyncio.sleep(RECONNECT_DELAY_S)
            continue

        try:
            async with BleakClient(address, timeout=10.0) as client:
                print(f"[buddy_ble_keepalive] connected to {address}")

                assembler = _LineAssembler(handle_incoming)

                def _notify_cb(_char, data: bytearray):
                    assembler.feed(bytes(data))

                await client.start_notify(NUS_TX_UUID, _notify_cb)

                mtu_chunk = max(20, min(180, client.mtu_size - 3))

                # Auto time sync on connect
                await _write_line(client, mtu_chunk, make_time_payload())
                last_time_sync = time.time()
                last_send      = 0.0

                while True:
                    if get_target() != "hardware":
                        print("[buddy_ble_keepalive] target changed, disconnecting")
                        return

                    if not client.is_connected:
                        raise BleakError("disconnected")

                    now = time.time()

                    if now - last_time_sync > TIME_SYNC_INTERVAL:
                        await _write_line(client, mtu_chunk, make_time_payload())
                        last_time_sync = now

                    # Send immediately on state file change, otherwise every
                    # TICK_S — the periodic heartbeat keeps the device's
                    # dataConnected() (data.h) alive even when idle.
                    mtime = state_mtime()
                    if mtime == last_mtime and (now - last_send) < TICK_S:
                        await asyncio.sleep(0.05)
                        continue
                    last_mtime = mtime
                    last_send  = now

                    state_obj = read_state()
                    state     = state_obj.get("state", "idle")

                    # ── Drain queued commands first ──────────────────────
                    cmds = state_obj.get("cmds", [])
                    if cmds:
                        for cmd in cmds:
                            await _write_line(client, mtu_chunk, cmd)
                            await asyncio.sleep(0.05)
                        clear_field("cmds", [])
                        state_obj = read_state()
                        state     = state_obj.get("state", "idle")

                    # ── Drain pending denied_add ──────────────────────────
                    denied_add = state_obj.get("denied_add", 0)
                    if denied_add > 0:
                        await _write_line(client, mtu_chunk, {"denied_add": denied_add})
                        clear_field("denied_add", 0)

                    # ── Celebrate auto-reverts to idle after 3 seconds ────
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

                    # ── Oneshots send once then revert ────────────────────
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
                                if state_obj.get("send_approved_add"):
                                    clear_field("send_approved_add", False)

                    await _write_line(client, mtu_chunk, payload)
                    await asyncio.sleep(TICK_S)

        except (BleakError, OSError, asyncio.TimeoutError) as e:
            print(f"[buddy_ble_keepalive] connection error: {e}, "
                  f"retrying in {RECONNECT_DELAY_S:.0f}s...")
            await asyncio.sleep(RECONNECT_DELAY_S)


def main():
    signal.signal(signal.SIGINT,  lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    target = get_target()
    if target != "hardware":
        print(f"[buddy_ble_keepalive] target={target}, exiting")
        sys.exit(0)

    try:
        asyncio.run(run_ble())
    except ImportError:
        sys.exit("[buddy_ble_keepalive] bleak not installed — run: pip install bleak")


if __name__ == "__main__":
    main()
