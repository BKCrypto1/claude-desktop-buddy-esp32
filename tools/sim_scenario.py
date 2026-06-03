#!/usr/bin/env python3
"""
Scripted scenario player for the desktop sim.

Reads a `.jsonl` file where each line is one of:
  {"send":   <obj>}       — send obj as a JSON line over the wire
  {"sleep":  <seconds>}   — wait before the next step
  {"expect": "<ack-name>"} — wait (up to 5s) for {ack:<name>}; warn if missing
  {"echo":   "..."}       — print a comment to the console

Connects to the same TCP socket the Tk driver uses (127.0.0.1:31415).
Useful for repeatable demos: drive the buddy through busy → attention →
celebrate → idle without clicking.

Usage:
    python3 tools/sim_scenario.py demos/busy.jsonl
"""
import json
import socket
import sys
import time

HOST, PORT = "127.0.0.1", 31415


def main(path: str) -> int:
    s = socket.create_connection((HOST, PORT), timeout=3)
    s.settimeout(0.2)
    inbuf = b""

    def drain(deadline=None, want_ack=None):
        nonlocal inbuf
        while True:
            now = time.time()
            if deadline and now > deadline:
                return None
            try:
                chunk = s.recv(2048)
                if not chunk:
                    return None
                inbuf += chunk
            except socket.timeout:
                if not deadline:
                    return None
                continue
            while b"\n" in inbuf:
                line, inbuf = inbuf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                print(f"  ← {line.decode(errors='replace')}")
                if want_ack:
                    try:
                        if json.loads(line).get("ack") == want_ack:
                            return True
                    except ValueError:
                        pass

    with open(path) as f:
        steps = [json.loads(ln) for ln in f if ln.strip() and not ln.startswith("#")]

    for step in steps:
        if "echo" in step:
            print(f"# {step['echo']}")
        elif "sleep" in step:
            time.sleep(float(step["sleep"]))
            drain()
        elif "send" in step:
            line = json.dumps(step["send"], separators=(",", ":")) + "\n"
            print(f"  → {line.strip()}")
            s.sendall(line.encode())
            drain()
        elif "expect" in step:
            ok = drain(deadline=time.time() + 5.0, want_ack=step["expect"])
            if not ok:
                print(f"  !! expected ack '{step['expect']}' not seen")
        else:
            print(f"  ?? unknown step: {step}")

    s.close()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
