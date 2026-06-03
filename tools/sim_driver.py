#!/usr/bin/env python3
"""
Simulator driver — Tk panel that speaks the Stick's BLE wire protocol
over a TCP socket on 127.0.0.1:31415, instead of GATT.

Mirrors what the real Hardware Buddy desktop app pushes:
  • {"total":N, "running":N, "waiting":N, "tokens":N, "tokens_today":N, "msg":"..."}
  • {"entries": ["line1", "line2", ...]}
  • {"prompt": {"id":"...", "tool":"Bash", "hint":"rm -rf"}}
  • {"time": [epoch_sec, tz_offset_sec]}
  • {"cmd":"status"} → expects {"ack":"status", ...} reply
  • {"cmd":"celebrate"}
  • {"cmd":"owner", "name":"Bryan"}  /  {"cmd":"name", "name":"Buddy"}

Listens for replies (especially {cmd:"permission"} from approval prompts)
and prints every line in / out to a scrolling log pane.

Usage:
    python3 tools/sim_driver.py

(With the simulator built and running:
    cd sim && make run
)
"""
import base64
import glob
import json
import os
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext

HOST = "127.0.0.1"
PORT = 31415
CHUNK_BYTES = 256   # matches tools/test_xfer.py — keeps {cmd,d:b64} under ~400 bytes

# ASCII species names in the same order as src/buddy.cpp:94-99 SPECIES_TABLE.
# Index ↔ name mapping: send {"cmd":"species","idx":N}.
SPECIES_NAMES = [
    "capybara", "duck", "goose", "blob",
    "cat", "dragon", "octopus", "owl",
    "penguin", "turtle", "snail", "ghost",
    "axolotl", "cactus", "robot", "rabbit",
    "mushroom", "chonk",
]


class Bridge:
    """Background TCP socket; reconnects until cancelled."""

    def __init__(self, on_line, on_state):
        self._on_line = on_line          # callback(str) — incoming JSON line
        self._on_state = on_state        # callback(bool connected)
        self._sock = None
        self._stop = threading.Event()
        self._tx = queue.Queue()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def send(self, obj):
        line = json.dumps(obj, separators=(",", ":")) + "\n"
        self._tx.put(line.encode())
        return line.strip()

    def stop(self):
        self._stop.set()
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass

    def _run(self):
        while not self._stop.is_set():
            try:
                self._sock = socket.create_connection((HOST, PORT), timeout=1.5)
                self._sock.settimeout(0.1)
                self._on_state(True)
                self._pump()
            except (ConnectionRefusedError, OSError):
                self._on_state(False)
                time.sleep(0.5)
            finally:
                try:
                    if self._sock:
                        self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def _pump(self):
        buf = b""
        while not self._stop.is_set():
            # TX
            try:
                while True:
                    out = self._tx.get_nowait()
                    self._sock.sendall(out)
            except queue.Empty:
                pass
            # RX
            try:
                chunk = self._sock.recv(1024)
                if not chunk:
                    raise ConnectionResetError("eof")
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    s = line.decode("utf-8", errors="replace").strip()
                    if s:
                        self._on_line(s)
            except socket.timeout:
                pass
            except (OSError, ConnectionResetError):
                self._on_state(False)
                return


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Buddy Sim Driver")
        self.geometry("900x820")
        self.minsize(820, 700)
        self.bridge = Bridge(self._enqueue_line, self._enqueue_state)
        self._inq = queue.Queue()
        # ack waiters: ack-name → queue of decoded-JSON dicts. Populated in
        # _drain when an incoming RX line is an ack the upload worker is
        # waiting on. Lets us pump UI updates from the main thread while a
        # background thread sequences a multi-step transfer.
        self._ack_waiters = {}        # name → queue.Queue
        self._ack_lock = threading.Lock()
        self._upload_thread = None
        self._build_ui()
        self.after(50, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        pad = {"padx": 6, "pady": 3}

        # Connection status
        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        self.status = tk.StringVar(value="disconnected")
        ttk.Label(top, text="Sim:").pack(side="left")
        ttk.Label(top, textvariable=self.status, foreground="red").pack(side="left", padx=4)

        # Live data. Sessions: total/running/waiting are small ints — the
        # state machine in src/main.cpp:478-484 only cares about
        # `waiting>0` (→ attention) and `running>=3` (→ busy), so a 0..8
        # spinbox is plenty and lets the whole row collapse to one line.
        live = ttk.LabelFrame(self, text="Live Claude state")
        live.pack(fill="x", **pad)
        self.total = tk.IntVar(value=0)
        self.running = tk.IntVar(value=0)
        self.waiting = tk.IntVar(value=0)
        sessions = ttk.Frame(live)
        sessions.grid(row=0, column=0, columnspan=2, sticky="w", **pad)
        for col, (lbl, var) in enumerate([
                ("total", self.total),
                ("running", self.running),
                ("waiting", self.waiting)]):
            ttk.Label(sessions, text=lbl).grid(row=0, column=col * 2, sticky="e", padx=(8, 2))
            ttk.Spinbox(sessions, from_=0, to=99, textvariable=var, width=4
                        ).grid(row=0, column=col * 2 + 1, sticky="w")

        self.tokens = tk.IntVar(value=0)
        self.tokens_today = tk.IntVar(value=0)
        tokens_row = ttk.Frame(live)
        tokens_row.grid(row=1, column=0, columnspan=2, sticky="w", **pad)
        ttk.Label(tokens_row, text="tokens").grid(row=0, column=0, sticky="e", padx=(8, 2))
        ttk.Spinbox(tokens_row, from_=0, to=10**7, increment=1000,
                    textvariable=self.tokens, width=10).grid(row=0, column=1, sticky="w")
        ttk.Label(tokens_row, text="today").grid(row=0, column=2, sticky="e", padx=(16, 2))
        ttk.Spinbox(tokens_row, from_=0, to=10**7, increment=1000,
                    textvariable=self.tokens_today, width=10).grid(row=0, column=3, sticky="w")

        ttk.Label(live, text="msg").grid(row=2, column=0, sticky="e", **pad)
        self.msg = tk.StringVar()
        ttk.Entry(live, textvariable=self.msg).grid(row=2, column=1, sticky="we", **pad)

        ttk.Label(live, text="entries (one per line)").grid(row=3, column=0, sticky="ne", **pad)
        self.entries = tk.Text(live, height=4, width=44)
        self.entries.grid(row=3, column=1, sticky="we", **pad)

        ttk.Button(live, text="Send live update", command=self._send_live).grid(
            row=4, column=1, sticky="e", **pad)
        live.columnconfigure(1, weight=1)

        # Approvals + commands
        ctl = ttk.LabelFrame(self, text="Commands")
        ctl.pack(fill="x", **pad)
        ctl.columnconfigure(3, weight=1)

        self.tool = tk.StringVar(value="Bash")
        self.hint = tk.StringVar(value="rm -rf /")
        ttk.Label(ctl, text="tool").grid(row=0, column=0, sticky="e", **pad)
        ttk.Entry(ctl, textvariable=self.tool, width=14).grid(row=0, column=1, sticky="w")
        ttk.Label(ctl, text="hint").grid(row=0, column=2, sticky="e", **pad)
        ttk.Entry(ctl, textvariable=self.hint).grid(row=0, column=3, sticky="we", **pad)
        ttk.Button(ctl, text="Send approval prompt",
                   command=self._send_prompt).grid(row=0, column=4, columnspan=2, sticky="we", **pad)

        action_row = ttk.Frame(ctl)
        action_row.grid(row=1, column=0, columnspan=6, sticky="we", **pad)
        for i, (lbl, fn) in enumerate([
                ("Time sync now", self._send_time),
                ("Trigger celebrate", lambda: self._send({"cmd": "celebrate"})),
                ("Status",       lambda: self._send({"cmd": "status"})),
                ("Clear prompt", lambda: self._send({"prompt": None}))]):
            ttk.Button(action_row, text=lbl, command=fn).grid(row=0, column=i, padx=4)

        ttk.Label(ctl, text="owner").grid(row=2, column=0, sticky="e", **pad)
        self.owner = tk.StringVar(value="Bryan")
        ttk.Entry(ctl, textvariable=self.owner, width=14).grid(row=2, column=1, sticky="w")
        ttk.Button(ctl, text="Set owner",
                   command=lambda: self._send({"cmd": "owner", "name": self.owner.get()})
                   ).grid(row=2, column=2, sticky="w", **pad)
        ttk.Label(ctl, text="pet").grid(row=2, column=3, sticky="e", **pad)
        self.pet = tk.StringVar(value="Buddy")
        ttk.Entry(ctl, textvariable=self.pet, width=14).grid(row=2, column=4, sticky="w")
        ttk.Button(ctl, text="Set name",
                   command=lambda: self._send({"cmd": "name", "name": self.pet.get()})
                   ).grid(row=2, column=5, sticky="w", **pad)

        # Species pick — dropdown of named ASCII species, or "GIF" to use
        # the uploaded character. Mirrors the Settings → "ascii pet" cycle
        # on the device. Sends {"cmd":"species","idx":N} where idx=255 (0xFF)
        # means "use uploaded GIF".
        ttk.Label(ctl, text="species").grid(row=3, column=0, sticky="e", **pad)
        self.species_choice = tk.StringVar(value="GIF (uploaded character)")
        species_options = ["GIF (uploaded character)"] + [
            f"{i}: {n}" for i, n in enumerate(SPECIES_NAMES)
        ]
        ttk.Combobox(ctl, textvariable=self.species_choice,
                     values=species_options, state="readonly", width=24
                     ).grid(row=3, column=1, columnspan=3, sticky="we", **pad)
        ttk.Button(ctl, text="Set species",
                   command=self._send_species).grid(row=3, column=4, columnspan=2, sticky="we", **pad)

        # Character upload
        chf = ttk.LabelFrame(self, text="Character upload")
        chf.pack(fill="x", **pad)
        chf.columnconfigure(3, weight=1)
        ttk.Label(chf, text="name").grid(row=0, column=0, sticky="e", **pad)
        self.char_name = tk.StringVar(value="bufo")
        ttk.Entry(chf, textvariable=self.char_name, width=14).grid(row=0, column=1, sticky="w")
        ttk.Button(chf, text="Choose folder…",
                   command=self._pick_char_folder).grid(row=0, column=2, **pad)
        self.char_folder = tk.StringVar(value="")
        ttk.Label(chf, textvariable=self.char_folder, foreground="#888"
                  ).grid(row=0, column=3, sticky="we", **pad)
        self.upload_btn = ttk.Button(chf, text="Upload character",
                                     command=self._start_upload)
        self.upload_btn.grid(row=0, column=4, sticky="e", **pad)
        self.char_progress = ttk.Progressbar(chf, mode="determinate")
        self.char_progress.grid(row=1, column=0, columnspan=4, sticky="we", **pad)
        self.char_status = tk.StringVar(value="idle")
        ttk.Label(chf, textvariable=self.char_status, foreground="#888"
                  ).grid(row=1, column=4, sticky="w", **pad)

        # Log
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=True, **pad)
        self.log = scrolledtext.ScrolledText(logf, height=14, font=("Menlo", 10))
        self.log.pack(fill="both", expand=True)
        self.log.tag_config("tx", foreground="#0066cc")
        self.log.tag_config("rx", foreground="#006600")
        self.log.tag_config("sys", foreground="#888888")

    # ─── socket → UI ───
    def _enqueue_line(self, s):
        # Route acks to any blocked upload worker BEFORE logging — the worker
        # runs on its own thread and will wake on the matching ack queue.
        try:
            obj = json.loads(s)
            ack = obj.get("ack")
            if ack:
                with self._ack_lock:
                    q = self._ack_waiters.get(ack)
                if q is not None:
                    q.put(obj)
        except (ValueError, AttributeError):
            pass
        self._inq.put(("rx", s))

    def _wait_ack(self, name, timeout=5.0):
        """Block the calling thread until the firmware acks `name` (or timeout)."""
        q = queue.Queue()
        with self._ack_lock:
            self._ack_waiters[name] = q
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            return None
        finally:
            with self._ack_lock:
                self._ack_waiters.pop(name, None)

    def _enqueue_state(self, connected):
        self._inq.put(("state", connected))

    def _drain(self):
        try:
            while True:
                kind, payload = self._inq.get_nowait()
                if kind == "rx":
                    self._log("rx", payload)
                elif kind == "state":
                    self.status.set("connected" if payload else "disconnected")
                    self.tk.call(self.children["!frame"].children["!label2"], "configure",
                                 "-foreground", "green" if payload else "red")
        except queue.Empty:
            pass
        self.after(50, self._drain)

    # ─── outgoing helpers ───
    def _send(self, obj):
        line = self.bridge.send(obj)
        self._log("tx", line)

    def _send_live(self):
        entries = [s for s in self.entries.get("1.0", "end").splitlines() if s.strip()]
        self._send({
            "total":   self.total.get(),
            "running": self.running.get(),
            "waiting": self.waiting.get(),
            "tokens":  self.tokens.get(),
            "tokens_today": self.tokens_today.get(),
            "msg":     self.msg.get(),
            "entries": entries,
        })

    def _send_prompt(self):
        pid = "p_%d" % int(time.time() * 1000)
        self._send({"prompt": {"id": pid, "tool": self.tool.get(), "hint": self.hint.get()}})

    def _send_species(self):
        choice = self.species_choice.get()
        # "GIF (uploaded character)" → 0xFF; "12: axolotl" → 12.
        idx = 255 if choice.startswith("GIF") else int(choice.split(":", 1)[0])
        self._send({"cmd": "species", "idx": idx})

    # ─── character upload ───
    def _pick_char_folder(self):
        path = filedialog.askdirectory(
            title="Choose character folder (must contain manifest.json + .gif files)",
            initialdir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        if path:
            self.char_folder.set(path)
            base = os.path.basename(path.rstrip("/"))
            if base and self.char_name.get() == "bufo":
                self.char_name.set(base)

    def _start_upload(self):
        if self._upload_thread and self._upload_thread.is_alive():
            return
        folder = self.char_folder.get()
        name = self.char_name.get().strip() or "pet"
        if not folder or not os.path.isdir(folder):
            self.char_status.set("pick a folder first")
            return
        self.upload_btn.configure(state="disabled")
        self._upload_thread = threading.Thread(
            target=self._upload_worker, args=(folder, name), daemon=True)
        self._upload_thread.start()

    def _set_status(self, txt, pct=None):
        # tk vars are thread-safe enough for short strings; if this gets flaky,
        # switch to scheduling on the inq.
        self.char_status.set(txt)
        if pct is not None:
            self.char_progress["value"] = pct

    def _upload_worker(self, folder, name):
        try:
            files = sorted(
                p for p in glob.glob(os.path.join(folder, "*"))
                if os.path.isfile(p) and not os.path.basename(p).startswith(".")
            )
            if not files:
                self._set_status("no files in folder")
                return
            total = sum(os.path.getsize(p) for p in files)
            self._set_status(f"begin {name} ({len(files)} files, {total} bytes)…", 0)

            self._send({"cmd": "char_begin", "name": name, "total": total})
            a = self._wait_ack("char_begin", timeout=10)
            if not a or not a.get("ok"):
                self._set_status(f"char_begin failed: {a}")
                return

            sent = 0
            for path in files:
                fn = os.path.basename(path)
                data = open(path, "rb").read()
                self._send({"cmd": "file", "path": fn, "size": len(data)})
                a = self._wait_ack("file", timeout=5)
                if not a or not a.get("ok"):
                    self._set_status(f"file open failed: {fn}")
                    return
                for i in range(0, len(data), CHUNK_BYTES):
                    chunk = data[i:i + CHUNK_BYTES]
                    self._send({"cmd": "chunk",
                                "d": base64.b64encode(chunk).decode()})
                    a = self._wait_ack("chunk", timeout=5)
                    if not a or not a.get("ok"):
                        self._set_status(f"chunk failed at {fn}+{i}")
                        return
                    sent += len(chunk)
                    self._set_status(f"{fn} ({sent}/{total})", sent * 100.0 / total)
                self._send({"cmd": "file_end"})
                a = self._wait_ack("file_end", timeout=10)
                if not a or not a.get("ok"):
                    self._set_status(f"file_end failed: {fn}")
                    return

            self._send({"cmd": "char_end"})
            a = self._wait_ack("char_end", timeout=15)
            if a and a.get("ok"):
                self._set_status("done.", 100)
            else:
                self._set_status(f"char_end failed: {a}")
        finally:
            self.upload_btn.configure(state="normal")

    def _send_time(self):
        now = int(time.time())
        # Local TZ offset in seconds.
        tz = -time.timezone if time.daylight == 0 else -time.altzone
        self._send({"time": [now, tz]})

    # ─── log ───
    def _log(self, kind, line):
        prefix = {"tx": "→ ", "rx": "← ", "sys": "  "}[kind]
        self.log.insert("end", prefix + line + "\n", kind)
        self.log.see("end")

    def _on_close(self):
        self.bridge.stop()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
