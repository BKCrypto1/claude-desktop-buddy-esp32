#!/usr/bin/env python3
"""
Buddy Manager — tabbed control panel for Claude Buddy devices.

  Simulator  tab — drive the desktop sim over TCP (live state, prompts, species)
  Characters tab — convert, manage, and install character packs (sim / USB / BLE)
  Firmware   tab — flash firmware and filesystem to real hardware via USB

Usage:
    python3 tools/sim_driver.py

    Simulator tab requires:  cd sim && make run
    BLE upload requires:     pip install bleak
"""
import base64
import configparser
import glob
import json
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext

HOST = "127.0.0.1"
PORT = 31415
CHUNK_BYTES = 256

SPECIES_NAMES = [
    "capybara", "duck", "goose", "blob",
    "cat", "dragon", "octopus", "owl",
    "penguin", "turtle", "snail", "ghost",
    "axolotl", "cactus", "robot", "rabbit",
    "mushroom", "chonk", "dog",
]

REPO_ROOT     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHARS_DIR     = os.path.join(REPO_ROOT, "characters")
TOOLS_DIR     = os.path.join(REPO_ROOT, "tools")
TARGET_FILE   = os.path.expanduser("~/.buddy_target")
STATE_FILE    = os.path.expanduser("~/.buddy_state")
KEEPALIVE_PID = os.path.expanduser("~/.buddy_keepalive.pid")
KEEPALIVE_PY  = os.path.join(TOOLS_DIR, "buddy_keepalive.py")


# ─────────────────────────────────────────────────────────────────────────────
# TCP bridge to simulator
# ─────────────────────────────────────────────────────────────────────────────

class Bridge:
    """Background TCP socket; reconnects until cancelled. Can be paused."""

    def __init__(self, on_line, on_state):
        self._on_line  = on_line
        self._on_state = on_state
        self._sock      = None
        self._stop      = threading.Event()
        self._pause     = threading.Event()   # set = paused, clear = active
        self._connected = threading.Event()
        self._tx        = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def wait_connected(self, timeout=10.0):
        return self._connected.wait(timeout=timeout)

    def send(self, obj):
        line = json.dumps(obj, separators=(",", ":")) + "\n"
        self._tx.put(line.encode())
        return line.strip()

    def pause(self):
        """Stop trying to connect (e.g. when keepalive owns the slot)."""
        self._pause.set()
        self._connected.clear()
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass

    def resume(self):
        """Resume connecting."""
        self._pause.clear()

    def stop(self):
        self._stop.set()
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass

    def _run(self):
        while not self._stop.is_set():
            if self._pause.is_set():
                time.sleep(0.5)
                continue
            try:
                self._sock = socket.create_connection((HOST, PORT), timeout=1.5)
                self._sock.settimeout(0.1)
                self._connected.set()
                self._on_state(True)
                self._pump()
            except (ConnectionRefusedError, OSError):
                self._connected.clear()
                self._on_state(False)
                time.sleep(0.5)
            finally:
                self._connected.clear()
                try:
                    if self._sock:
                        self._sock.close()
                except Exception:
                    pass
                self._sock = None

    def _pump(self):
        buf = b""
        while not self._stop.is_set():
            try:
                while True:
                    self._sock.sendall(self._tx.get_nowait())
            except queue.Empty:
                pass
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


# ─────────────────────────────────────────────────────────────────────────────
# Main app
# ─────────────────────────────────────────────────────────────────────────────

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Buddy Manager")
        self.geometry("1020x960")
        self.minsize(900, 780)
        self.bridge      = Bridge(self._enqueue_line, self._enqueue_state)
        self._inq        = queue.Queue()
        self._ack_waiters = {}
        self._ack_lock   = threading.Lock()
        self._sim_upload_lock = threading.Lock()   # only one upload to sim at a time
        self._upload_thread = None
        self._celebrate_timer = None
        self._build_ui()
        # Pause bridge and disable sim controls if target isn't sim
        initial_target = self._read_hook_target()
        if initial_target != "sim":
            self.bridge.pause()
        self.after(100, lambda: self._set_sim_controls(initial_target))
        self.after(50, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        pad = {"padx": 6, "pady": 3}

        # ── status bar (always visible, above tabs) ──
        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)

        # Connection label — prefix changes with target
        self._conn_label = ttk.Label(bar, text="Connection:")
        self._conn_label.pack(side="left")
        self.sim_status = tk.StringVar(value="disconnected")
        self._sim_status_label = ttk.Label(bar, textvariable=self.sim_status,
                                           foreground="red")
        self._sim_status_label.pack(side="left", padx=4)

        # ── Target toggle ──
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        ttk.Label(bar, text="Target:", foreground="#888").pack(side="left")
        self._hook_target = tk.StringVar(value=self._read_hook_target())
        for tgt, label in [("desktop", "Desktop"), ("sim", "Sim"), ("hardware", "Hardware"), ("off", "Off")]:
            rb = ttk.Radiobutton(
                bar, text=label, variable=self._hook_target, value=tgt,
                command=self._on_hook_target_change,
            )
            rb.pack(side="left", padx=4)
        self.after(2000, self._poll_keepalive)

        # ── notebook ──
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, **pad)

        sim_tab  = ttk.Frame(nb)
        char_tab = ttk.Frame(nb)
        fw_tab   = ttk.Frame(nb)
        nb.add(sim_tab,  text="  Simulator  ")
        nb.add(char_tab, text="  Characters  ")
        nb.add(fw_tab,   text="  Firmware  ")

        self._build_simulator_tab(sim_tab,  pad)
        self._build_characters_tab(char_tab, pad)
        self._build_firmware_tab(fw_tab,    pad)

        # ── shared log (always visible below tabs) ──
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=False, **pad)
        self.log = scrolledtext.ScrolledText(logf, height=10, font=("Menlo", 10))
        self.log.pack(fill="both", expand=True)
        self.log.tag_config("tx",  foreground="#0066cc")
        self.log.tag_config("rx",  foreground="#006600")
        self.log.tag_config("sys", foreground="#888888")

    # ── Simulator tab ─────────────────────────────────────────────────────────

    def _build_simulator_tab(self, parent, pad):
        self._sim_widgets = []      # enabled only in Sim mode
        self._ble_widgets = []      # enabled only in Hardware mode

        # ── Claude state ──────────────────────────────────────────────────────
        live = ttk.LabelFrame(parent, text="Claude state")
        live.pack(fill="x", **pad)
        live.columnconfigure(1, weight=1)

        # Sessions + tokens row
        counters = ttk.Frame(live)
        counters.grid(row=0, column=0, columnspan=2, sticky="we", **pad)
        self.total        = tk.IntVar(value=0)
        self.running      = tk.IntVar(value=0)
        self.waiting      = tk.IntVar(value=0)
        self.tokens       = tk.IntVar(value=0)
        self.tokens_today = tk.IntVar(value=0)
        fields = [
            ("sessions", None), ("total", self.total), ("running", self.running),
            ("waiting", self.waiting), ("  tokens", None),
            ("total", self.tokens, 1000, 8), ("today", self.tokens_today, 1000, 8),
        ]
        col = 0
        for item in fields:
            if item[1] is None:
                ttk.Label(counters, text=item[0], foreground="#888"
                          ).grid(row=0, column=col, padx=(10, 4))
                col += 1
            else:
                lbl  = item[0]
                var  = item[1]
                inc  = item[2] if len(item) > 2 else 1
                w    = item[3] if len(item) > 3 else 4
                ttk.Label(counters, text=lbl).grid(row=0, column=col, sticky="e", padx=(4, 2))
                sb = ttk.Spinbox(counters, from_=0, to=10**7, increment=inc,
                                 textvariable=var, width=w)
                sb.grid(row=0, column=col+1, sticky="w")
                self._sim_widgets.append(sb)
                col += 2

        # Quick state presets — two rows of buttons, one per buddy state
        presets = ttk.Frame(live)
        presets.grid(row=1, column=0, columnspan=2, sticky="w", **pad)
        ttk.Label(presets, text="Quick set:", foreground="#888").grid(
            row=0, column=0, padx=(4, 8), rowspan=2, sticky="w")
        for col, (lbl, fn) in enumerate([
            ("Sleep",     self._preset_sleep),
            ("Idle",      self._preset_idle),
            ("Busy",      self._preset_busy),
            ("Attention", self._preset_attention),
        ]):
            b = ttk.Button(presets, text=lbl, command=fn, width=9)
            b.grid(row=0, column=col + 1, padx=2, pady=1)
            self._sim_widgets.append(b)
        for col, (lbl, fn) in enumerate([
            ("Celebrate", self._preset_celebrate),
            ("Dizzy",     self._preset_dizzy),
            ("Heart",     self._preset_heart),
        ]):
            b = ttk.Button(presets, text=lbl, command=fn, width=9)
            b.grid(row=1, column=col + 1, padx=2, pady=1)
            self._sim_widgets.append(b)

        # Message + entries
        ttk.Label(live, text="msg").grid(row=2, column=0, sticky="e", **pad)
        self.msg = tk.StringVar()
        _e = ttk.Entry(live, textvariable=self.msg)
        _e.grid(row=2, column=1, sticky="we", **pad)
        self._sim_widgets.append(_e)

        ttk.Label(live, text="entries").grid(row=3, column=0, sticky="ne", **pad)
        self.entries = tk.Text(live, height=2, width=44)
        self.entries.grid(row=3, column=1, sticky="we", **pad)
        self._sim_widgets.append(self.entries)

        _b = ttk.Button(live, text="Send live update", command=self._send_live)
        _b.grid(row=4, column=1, sticky="e", **pad)
        self._sim_widgets.append(_b)

        # ── Approval prompt ───────────────────────────────────────────────────
        apv = ttk.LabelFrame(parent, text="Approval prompt")
        apv.pack(fill="x", **pad)
        apv.columnconfigure(3, weight=1)

        self.tool = tk.StringVar(value="Bash")
        self.hint = tk.StringVar(value="rm -rf /")
        ttk.Label(apv, text="tool").grid(row=0, column=0, sticky="e", **pad)
        _et = ttk.Entry(apv, textvariable=self.tool, width=14)
        _et.grid(row=0, column=1, sticky="w", **pad)
        self._sim_widgets.append(_et)
        ttk.Label(apv, text="hint").grid(row=0, column=2, sticky="e", **pad)
        _eh = ttk.Entry(apv, textvariable=self.hint)
        _eh.grid(row=0, column=3, sticky="we", **pad)
        self._sim_widgets.append(_eh)
        _bp = ttk.Button(apv, text="Send prompt", command=self._send_prompt)
        _bp.grid(row=0, column=4, **pad)
        self._sim_widgets.append(_bp)
        _bc = ttk.Button(apv, text="Clear", command=lambda: self._send({"prompt": None}))
        _bc.grid(row=0, column=5, **pad)
        self._sim_widgets.append(_bc)

        # ── Device settings ───────────────────────────────────────────────────
        dev = ttk.LabelFrame(parent, text="Device")
        dev.pack(fill="x", **pad)
        dev.columnconfigure(1, weight=1)
        dev.columnconfigure(4, weight=1)

        # Owner / pet name
        self.owner = tk.StringVar(value="Bryan")
        self.pet   = tk.StringVar(value="Buddy")
        _eo = ttk.Entry(dev, textvariable=self.owner, width=14)
        _eo.grid(row=0, column=0, columnspan=2, sticky="we", **pad)
        ttk.Label(dev, text="Owner").grid(row=0, column=0, sticky="e", **pad)
        _eo2 = ttk.Entry(dev, textvariable=self.owner, width=14)
        _eo2.grid(row=0, column=1, sticky="we", **pad)
        _bso = ttk.Button(dev, text="Set",
                          command=lambda: self._send_cmd_any({"cmd": "owner", "name": self.owner.get()}))
        _bso.grid(row=0, column=2, **pad)
        ttk.Label(dev, text="Pet name").grid(row=0, column=3, sticky="e", **pad)
        _ep = ttk.Entry(dev, textvariable=self.pet, width=14)
        _ep.grid(row=0, column=4, sticky="we", **pad)
        _bsp = ttk.Button(dev, text="Set",
                          command=lambda: self._send_cmd_any({"cmd": "name", "name": self.pet.get()}))
        _bsp.grid(row=0, column=5, **pad)
        # Entry fields disabled in Desktop (read-only there); buttons work in all modes
        self._sim_widgets.append(_ep)

        # Utility buttons — Time sync and Status work in all connected modes
        util = ttk.Frame(dev)
        util.grid(row=2, column=0, columnspan=6, sticky="w", **pad)
        ttk.Button(util, text="Time sync", command=self._send_time).pack(side="left", padx=4)
        _sb = ttk.Button(util, text="Status", command=lambda: self._send({"cmd": "status"}))
        _sb.pack(side="left", padx=4)
        self._sim_widgets.append(_sb)  # Status only meaningful in Sim mode

        # ── Upload character to sim ───────────────────────────────────────────
        chf = ttk.LabelFrame(parent, text="Upload character to sim")
        chf.pack(fill="x", **pad)
        chf.columnconfigure(1, weight=1)

        self.char_name   = tk.StringVar(value="")
        self.char_folder = tk.StringVar(value="")
        _bcf = ttk.Button(chf, text="Choose folder…", command=self._pick_char_folder)
        _bcf.grid(row=0, column=0, **pad)
        ttk.Label(chf, textvariable=self.char_folder, foreground="#888",
                  anchor="w").grid(row=0, column=1, sticky="we", **pad)
        self.upload_btn = ttk.Button(chf, text="Upload to sim", command=self._start_upload)
        self.upload_btn.grid(row=0, column=2, **pad)
        self.char_progress = ttk.Progressbar(chf, mode="determinate")
        self.char_progress.grid(row=1, column=0, columnspan=2, sticky="we", **pad)
        self.char_status = tk.StringVar(value="idle")
        ttk.Label(chf, textvariable=self.char_status, foreground="#888"
                  ).grid(row=1, column=2, sticky="w", **pad)
        self._sim_widgets.extend([_bcf, self.upload_btn])

    # ── Characters tab ────────────────────────────────────────────────────────

    def _build_characters_tab(self, parent, pad):
        # ── My Characters list ──
        mf = ttk.LabelFrame(parent, text="My Characters")
        mf.pack(fill="x", **pad)
        mf.columnconfigure(0, weight=1)

        cols = ("name", "files", "size")
        self.char_tree = ttk.Treeview(mf, columns=cols, show="headings", height=5,
                                      selectmode="browse")
        self.char_tree.heading("name",  text="Name")
        self.char_tree.heading("files", text="Files")
        self.char_tree.heading("size",  text="Size")
        self.char_tree.column("name",  width=180)
        self.char_tree.column("files", width=50,  anchor="center")
        self.char_tree.column("size",  width=80,  anchor="e")
        self.char_tree.grid(row=0, column=0, sticky="nswe", **pad)

        vsb = ttk.Scrollbar(mf, orient="vertical", command=self.char_tree.yview)
        vsb.grid(row=0, column=1, sticky="ns", pady=3)
        self.char_tree.configure(yscrollcommand=vsb.set)

        btns = ttk.Frame(mf)
        btns.grid(row=1, column=0, sticky="we", **pad)
        _bcts = ttk.Button(btns, text="Upload to sim", command=self._char_upload_sim_any)
        _bcts.pack(side="left", padx=3)
        self._sim_widgets.append(_bcts)
        ttk.Button(btns, text="Flash USB",  command=self._char_flash_usb).pack(side="left", padx=3)
        _bble = ttk.Button(btns, text="Upload BLE", command=self._char_upload_ble)
        _bble.pack(side="left", padx=3)
        self._ble_widgets.append(_bble)
        # Set active — works in all connected modes
        ttk.Button(btns, text="Set active", command=self._char_set_active).pack(side="left", padx=3)
        ttk.Button(btns, text="Refresh", command=self._refresh_chars).pack(side="right", padx=3)

        self._char_action_progress = ttk.Progressbar(mf, mode="indeterminate")
        self._char_action_progress.grid(row=2, column=0, sticky="we", padx=6, pady=2)

        self._refresh_chars()

        # ── Active character / species ────────────────────────────────────────
        act = ttk.LabelFrame(parent, text="Active character")
        act.pack(fill="x", **pad)
        act.columnconfigure(1, weight=1)

        ttk.Label(act, text="Species").grid(row=0, column=0, sticky="e", **pad)
        self.species_choice = tk.StringVar(value="GIF (uploaded character)")
        self._species_combo = ttk.Combobox(
            act, textvariable=self.species_choice, state="readonly", width=28,
            values=["GIF (uploaded character)"] + [
                f"{i}: {n}" for i, n in enumerate(SPECIES_NAMES)]
        )
        self._species_combo.grid(row=0, column=1, sticky="we", **pad)
        ttk.Button(act, text="Set on device",
                   command=self._set_species_any).grid(row=0, column=2, **pad)

        # ── Petdex import ──
        pdx = ttk.LabelFrame(parent, text="Petdex import  (download → convert → upload to sim)")
        pdx.pack(fill="x", **pad)
        pdx.columnconfigure(1, weight=1)
        ttk.Label(pdx, text="URL or name").grid(row=0, column=0, sticky="e", **pad)
        self.petdex_url = tk.StringVar(value="https://petdex.crafter.run/pets/mallow")
        ttk.Entry(pdx, textvariable=self.petdex_url).grid(row=0, column=1, sticky="we", **pad)
        self.petdex_pixel_art = tk.BooleanVar(value=False)
        ttk.Checkbutton(pdx, text="Pixel art",
                        variable=self.petdex_pixel_art).grid(row=0, column=2, **pad)
        self.petdex_btn = ttk.Button(pdx, text="Import",
                                     command=self._start_petdex_import)
        self.petdex_btn.grid(row=0, column=3, **pad)
        self.petdex_progress = ttk.Progressbar(pdx, mode="determinate", maximum=100)
        self.petdex_progress.grid(row=1, column=0, columnspan=2, sticky="we", **pad)
        self.petdex_status = tk.StringVar(value="idle")
        ttk.Label(pdx, textvariable=self.petdex_status, foreground="#888",
                  width=28).grid(row=1, column=2, sticky="w", **pad)

        # ── Strip import ──
        STATES = ["sleep", "idle", "busy", "attention", "celebrate", "dizzy", "heart"]
        self._strip_hints = {
            "idle":      ["idle"],
            "busy":      ["run", "walk"],
            "celebrate": ["attack", "jump", "skill"],
            "attention": ["hit", "hurt"],
            "sleep":     ["sit", "sleep", "rest"],
            "dizzy":     ["stun", "roll", "die", "dizzy"],
            "heart":     ["wave"],
        }
        spx = ttk.LabelFrame(parent, text="Strip import  (itch.io sprite pack → convert → upload to sim)")
        spx.pack(fill="x", **pad)
        spx.columnconfigure(1, weight=1)
        spx.columnconfigure(5, weight=1)
        spx.columnconfigure(0, minsize=65)
        spx.columnconfigure(4, minsize=65)

        ttk.Label(spx, text="Directory").grid(row=0, column=0, sticky="e", **pad)
        self.strip_dir = tk.StringVar()
        ttk.Entry(spx, textvariable=self.strip_dir, width=30
                  ).grid(row=0, column=1, columnspan=2, sticky="we", **pad)
        ttk.Button(spx, text="Browse…", command=self._pick_strip_dir
                   ).grid(row=0, column=3, **pad)
        ttk.Label(spx, text="Name").grid(row=0, column=4, sticky="e", **pad)
        self.strip_name = tk.StringVar(value="character")
        ttk.Entry(spx, textvariable=self.strip_name, width=12
                  ).grid(row=0, column=5, **pad)
        ttk.Label(spx, text="BG").grid(row=0, column=6, sticky="e", **pad)
        self.strip_bg = tk.StringVar(value="000000")
        ttk.Entry(spx, textvariable=self.strip_bg, width=7
                  ).grid(row=0, column=7, **pad)

        self.strip_state_vars   = {}
        self.strip_state_combos = {}
        for i, s in enumerate(STATES[:4]):
            ttk.Label(spx, text=s).grid(row=1+i, column=0, sticky="e", **pad)
            v  = tk.StringVar(value="—")
            cb = ttk.Combobox(spx, textvariable=v, width=26, state="readonly")
            cb.grid(row=1+i, column=1, columnspan=2, sticky="we", **pad)
            self.strip_state_vars[s] = v;  self.strip_state_combos[s] = cb
        for i, s in enumerate(STATES[4:]):
            ttk.Label(spx, text=s).grid(row=1+i, column=4, sticky="e", **pad)
            v  = tk.StringVar(value="—")
            cb = ttk.Combobox(spx, textvariable=v, width=26, state="readonly")
            cb.grid(row=1+i, column=5, columnspan=2, sticky="we", **pad)
            self.strip_state_vars[s] = v;  self.strip_state_combos[s] = cb

        self.strip_pixel_art = tk.BooleanVar(value=False)
        ttk.Checkbutton(spx, text="Pixel art",
                        variable=self.strip_pixel_art).grid(row=5, column=0, **pad)
        self.strip_btn = ttk.Button(spx, text="Import", command=self._start_strip_import)
        self.strip_btn.grid(row=5, column=1, sticky="w", **pad)
        self.strip_progress = ttk.Progressbar(spx, mode="determinate", maximum=100)
        self.strip_progress.grid(row=6, column=0, columnspan=6, sticky="we", **pad)
        self.strip_status = tk.StringVar(value="idle")
        ttk.Label(spx, textvariable=self.strip_status, foreground="#888",
                  width=28).grid(row=6, column=6, columnspan=2, sticky="w", **pad)

    # ── Firmware tab ──────────────────────────────────────────────────────────

    def _build_firmware_tab(self, parent, pad):
        # Read env names from platformio.ini
        ini_path = os.path.join(REPO_ROOT, "platformio.ini")
        cfg = configparser.ConfigParser()
        cfg.read(ini_path)
        envs = [s[4:] for s in cfg.sections() if s.startswith("env:") and s != "env:"]
        if not envs:
            envs = ["waveshare-esp32s3-touch-amoled-2-16"]

        fw = ttk.LabelFrame(parent, text="Flash hardware via USB  (requires PlatformIO)")
        fw.pack(fill="x", **pad)
        fw.columnconfigure(1, weight=1)

        ttk.Label(fw, text="Board").grid(row=0, column=0, sticky="e", **pad)
        self.fw_env = tk.StringVar(value=envs[-1])   # default to 2.16
        ttk.Combobox(fw, textvariable=self.fw_env, values=envs,
                     state="readonly", width=42
                     ).grid(row=0, column=1, sticky="we", **pad)

        btn_row = ttk.Frame(fw)
        btn_row.grid(row=1, column=0, columnspan=2, sticky="we", **pad)
        self.fw_btn = ttk.Button(btn_row, text="Flash Firmware",
                                 command=self._flash_firmware)
        self.fw_btn.pack(side="left", padx=4)
        self.fs_btn = ttk.Button(btn_row, text="Flash Filesystem",
                                 command=self._flash_filesystem)
        self.fs_btn.pack(side="left", padx=4)
        ttk.Label(btn_row, text="(connect USB before flashing)",
                  foreground="#888").pack(side="left", padx=12)

        self.fw_progress = ttk.Progressbar(fw, mode="indeterminate")
        self.fw_progress.grid(row=2, column=0, columnspan=2, sticky="we", **pad)
        self.fw_status = tk.StringVar(value="idle")
        ttk.Label(fw, textvariable=self.fw_status, foreground="#888"
                  ).grid(row=3, column=0, columnspan=2, sticky="w", **pad)

        # Board guide
        guide = ttk.LabelFrame(parent, text="Board → env reference")
        guide.pack(fill="x", **pad)
        rows = [
            ("ESP32-S3-Touch-AMOLED-2.16",  "waveshare-esp32s3-touch-amoled-2-16"),
            ("ESP32-C6-Touch-AMOLED-2.16",  "waveshare-esp32c6-touch-amoled-2-16"),
            ("ESP32-S3-Touch-AMOLED-1.8",   "waveshare-esp32s3-touch-amoled-1-8"),
            ("ESP32-S3-Touch-AMOLED-1.75C", "waveshare-esp32s3-touch-amoled-1-75c"),
        ]
        for r, (board, env) in enumerate(rows):
            ttk.Label(guide, text=board, width=32).grid(row=r, column=0, sticky="w", **pad)
            ttk.Label(guide, text=env, foreground="#555",
                      font=("Menlo", 10)).grid(row=r, column=1, sticky="w", **pad)

    # ─── hook target helpers ──────────────────────────────────────────────────

    def _read_hook_target(self) -> str:
        try:
            with open(TARGET_FILE) as f:
                return f.read().strip().lower()
        except FileNotFoundError:
            return "sim"

    def _on_hook_target_change(self):
        tgt = self._hook_target.get()
        try:
            with open(TARGET_FILE, "w") as f:
                f.write(tgt)
        except OSError as e:
            self._log("sys", f"[hook] could not write target: {e}")
            return

        if tgt == "desktop":
            self.bridge.pause()        # keepalive owns the TCP slot
            self._start_keepalive()
            self.sim_status.set("disconnected")
        elif tgt == "hardware":
            self.bridge.pause()
            self._stop_keepalive()
            self.sim_status.set("not paired")
        elif tgt == "off":
            self.bridge.pause()
            self._stop_keepalive()
            self.sim_status.set("off")
        else:  # sim
            self._stop_keepalive()
            self.bridge.resume()       # sim_driver owns the TCP slot
            self.sim_status.set("disconnected")

        self._refresh_status()
        self._set_sim_controls(tgt)
        self._log("sys", f"[hook] target → {tgt}")

    def _keepalive_running(self) -> bool:
        try:
            with open(KEEPALIVE_PID) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            return True
        except (FileNotFoundError, ValueError, OSError, ProcessLookupError):
            return False

    def _start_keepalive(self):
        if self._keepalive_running():
            return
        proc = subprocess.Popen(
            [sys.executable, KEEPALIVE_PY],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            with open(KEEPALIVE_PID, "w") as f:
                f.write(str(proc.pid))
        except OSError:
            pass
        self._log("sys", f"[hook] keepalive started (pid {proc.pid})")

    def _stop_keepalive(self):
        try:
            with open(KEEPALIVE_PID) as f:
                pid = int(f.read().strip())
            os.kill(pid, 15)  # SIGTERM
            os.remove(KEEPALIVE_PID)
            self._log("sys", f"[hook] keepalive stopped (pid {pid})")
        except (FileNotFoundError, ValueError, OSError, ProcessLookupError):
            pass

    def _set_sim_controls(self, target: str):
        """Enable/disable controls based on active target."""
        for w in getattr(self, "_sim_widgets", []):
            try:
                w.configure(state="normal" if target in ("sim", "desktop") else "disabled")
            except tk.TclError:
                pass
        for w in getattr(self, "_ble_widgets", []):
            try:
                w.configure(state="normal" if target == "hardware" else "disabled")
            except tk.TclError:
                pass

    def _refresh_status(self):
        """Update the connection label and status for the current target."""
        tgt = self._hook_target.get()

        if tgt == "desktop":
            alive = self._keepalive_running()
            self._conn_label.config(text="Desktop:")
            self.sim_status.set("connected" if alive else "disconnected")
            self._sim_status_label.config(foreground="green" if alive else "red")

        elif tgt == "sim":
            connected = self.sim_status.get() == "connected"
            self._conn_label.config(text="Sim:")
            self._sim_status_label.config(foreground="green" if connected else "red")

        elif tgt == "hardware":
            self._conn_label.config(text="Hardware:")
            self.sim_status.set("not paired")
            self._sim_status_label.config(foreground="#888")

        else:  # off
            self._conn_label.config(text="Connection:")
            self.sim_status.set("off")
            self._sim_status_label.config(foreground="#888")

    def _poll_keepalive(self):
        """Poll connection status every 2 seconds."""
        tgt = self._hook_target.get()
        if tgt == "desktop" and not self._keepalive_running():
            self._start_keepalive()
        self._refresh_status()
        self.after(2000, self._poll_keepalive)

    # ─── socket → UI ─────────────────────────────────────────────────────────

    def _enqueue_line(self, s):
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
        self.after(0, self._refresh_status)

    def _drain(self):
        try:
            while True:
                kind, payload = self._inq.get_nowait()
                if kind == "rx":
                    self._log("rx", payload)
                elif kind == "log":
                    self._log(*payload)
                elif kind == "state":
                    self.sim_status.set("connected" if payload else "disconnected")
                    self._sim_status_label.configure(
                        foreground="green" if payload else "red")
                    self._refresh_status()
                elif kind == "pdx":
                    txt, pct = payload
                    self.petdex_status.set(txt)
                    if pct is not None:
                        self.petdex_progress["value"] = pct
                elif kind == "strip":
                    txt, pct = payload
                    self.strip_status.set(txt)
                    if pct is not None:
                        self.strip_progress["value"] = pct
                elif kind == "fw":
                    txt, running = payload
                    self.fw_status.set(txt)
                    if running:
                        self.fw_progress.start(10)
                    else:
                        self.fw_progress.stop()
                elif kind == "char_status":
                    txt, pct = payload
                    self.char_status.set(txt)
                    if pct is not None:
                        self.char_progress["value"] = pct
        except queue.Empty:
            pass
        self.after(50, self._drain)

    # ─── outgoing helpers ─────────────────────────────────────────────────────

    def _send(self, obj):
        line = self.bridge.send(obj)
        self._inq.put(("log", ("tx", line)))

    def _qlog(self, kind, line):
        self._inq.put(("log", (kind, line)))

    def _send_live(self):
        entries = [s for s in self.entries.get("1.0", "end").splitlines() if s.strip()]
        self._send({
            "total": self.total.get(), "running": self.running.get(),
            "waiting": self.waiting.get(), "tokens": self.tokens.get(),
            "tokens_today": self.tokens_today.get(),
            "msg": self.msg.get(), "entries": entries,
        })

    def _cancel_celebrate(self):
        if self._celebrate_timer is not None:
            self.after_cancel(self._celebrate_timer)
            self._celebrate_timer = None

    def _preset_idle(self):
        self._cancel_celebrate()
        self.total.set(1); self.running.set(0); self.waiting.set(0)
        self._send_live()

    def _preset_busy(self):
        self._cancel_celebrate()
        self.total.set(1); self.running.set(3); self.waiting.set(0)
        self._send_live()

    def _preset_attention(self):
        self._cancel_celebrate()
        self.total.set(1); self.running.set(0); self.waiting.set(1)
        self._send_live()

    def _preset_sleep(self):
        self._cancel_celebrate()
        self._send({"cmd": "oneshot", "state": "sleep"})

    def _preset_dizzy(self):
        self._cancel_celebrate()
        self._send({"cmd": "oneshot", "state": "dizzy"})

    def _preset_heart(self):
        self._cancel_celebrate()
        self._send({"cmd": "oneshot", "state": "heart"})

    def _preset_celebrate(self):
        # Celebrate is triggered by the "completed" flag in the live payload,
        # not a cmd. Cancel any pending clear, send completed:true, schedule clear.
        self._cancel_celebrate()
        self.total.set(1); self.running.set(0); self.waiting.set(0)
        self._send({
            "total": 1, "running": 0, "waiting": 0,
            "tokens": self.tokens.get(), "tokens_today": self.tokens_today.get(),
            "msg": self.msg.get(), "completed": True,
        })
        self._celebrate_timer = self.after(3000, self._clear_completed)

    def _clear_completed(self):
        self._celebrate_timer = None
        self._send_live()

    def _send_prompt(self):
        pid = "p_%d" % int(time.time() * 1000)
        self._send({"prompt": {"id": pid, "tool": self.tool.get(),
                                "hint": self.hint.get()}})

    def _send_species(self):
        choice = self.species_choice.get()
        idx = 255 if choice.startswith("GIF") else int(choice.split(":", 1)[0])
        self._send({"cmd": "species", "idx": idx})

    # ── Unified command sender — routes to sim TCP, desktop cmds queue, or BLE ──

    def _send_cmd_any(self, cmd: dict):
        """Send a command to whatever is currently connected."""
        tgt = self._hook_target.get()
        if tgt == "sim":
            self._send(cmd)
        elif tgt in ("desktop",):
            # Route through keepalive cmds queue
            try:
                with open(STATE_FILE) as f:
                    state = json.loads(f.read())
            except Exception:
                state = {}
            cmds = state.get("cmds", [])
            cmds.append(cmd)
            state["cmds"] = cmds
            try:
                with open(STATE_FILE, "w") as f:
                    f.write(json.dumps(state))
                self._log("sys", f"[cmd] queued for desktop: {cmd}")
            except OSError as e:
                self._log("sys", f"[cmd] error: {e}")
        elif tgt == "hardware":
            self._send_ble_cmd(cmd)
        else:
            self._log("sys", "[cmd] no target connected")

    def _send_ble_cmd(self, cmd: dict):
        """Send a single JSON command to hardware over BLE in a background thread."""
        def _run():
            try:
                from bleak import BleakClient, BleakScanner
                import asyncio

                NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
                addr_file = os.path.expanduser("~/.buddy_ble_addr")

                async def _go():
                    address = None
                    try:
                        with open(addr_file) as f:
                            address = f.read().strip()
                    except FileNotFoundError:
                        pass
                    if not address:
                        device = await BleakScanner.find_device_by_filter(
                            lambda d, _: d.name and d.name.startswith("Claude-"),
                            timeout=5.0)
                        if not device:
                            self._qlog("sys", "[BLE] no Claude-* device found")
                            return
                        address = device.address
                        with open(addr_file, "w") as f:
                            f.write(address)
                    async with BleakClient(address, timeout=5.0) as client:
                        mtu  = max(20, client.mtu_size - 3)
                        line = (json.dumps(cmd, separators=(",", ":")) + "\n").encode()
                        for i in range(0, len(line), mtu):
                            await client.write_gatt_char(NUS_RX, line[i:i+mtu], response=False)
                        self._qlog("sys", f"[BLE] sent: {cmd}")

                asyncio.run(_go())
            except ImportError:
                self._qlog("sys", "[BLE] bleak not installed — pip install bleak")
            except Exception as e:
                self._qlog("sys", f"[BLE] error: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _set_species_any(self):
        """Set species on whatever is currently connected."""
        choice = self.species_choice.get()
        idx = 255 if choice.startswith("GIF") else int(choice.split(":", 1)[0])
        self._send_cmd_any({"cmd": "species", "idx": idx})

    def _char_set_active(self):
        """Upload selected character and set it active on the connected device."""
        tgt = self._hook_target.get()
        sel = self.char_tree.selection()
        if not sel:
            self._log("sys", "Select a character first.")
            return
        d = self._selected_char_dir()
        if not d:
            return
        if tgt in ("sim", "desktop"):
            self._char_upload_sim_any()
        elif tgt == "hardware":
            self._char_upload_ble()
        else:
            self._log("sys", "No target connected.")

    def _send_time(self):
        now = int(time.time())
        tz = -time.timezone if time.daylight == 0 else -time.altzone
        self._send_cmd_any({"time": [now, tz]})

    # ─── character upload (sim TCP) ───────────────────────────────────────────

    def _pick_char_folder(self):
        path = filedialog.askdirectory(
            title="Choose character folder (manifest.json + .gif files)",
            initialdir=REPO_ROOT,
        )
        if path:
            self.char_folder.set(path)
            base = os.path.basename(path.rstrip("/"))
            if base:
                self.char_name.set(base)

    def _start_upload(self):
        if self._upload_thread and self._upload_thread.is_alive():
            return
        folder = self.char_folder.get()
        name   = self.char_name.get().strip() or "pet"
        if not folder or not os.path.isdir(folder):
            self.char_status.set("pick a folder first")
            return
        self.upload_btn.configure(state="disabled")
        self._upload_thread = threading.Thread(
            target=self._upload_to_sim, args=(folder, name,
                lambda t, p=None: self._inq.put(("char_status", (t, p))),
                lambda: self.upload_btn.configure(state="normal")),
            daemon=True)
        self._upload_thread.start()

    def _upload_to_sim(self, folder, name, set_status, on_done):
        """Shared upload-to-sim worker. Calls set_status(txt, pct) and on_done() when complete."""
        if not self._sim_upload_lock.acquire(blocking=False):
            set_status("upload already in progress — wait for it to finish")
            on_done()
            return
        try:
            files = sorted(
                p for p in glob.glob(os.path.join(folder, "*"))
                if os.path.isfile(p) and not os.path.basename(p).startswith(".")
            )
            if not files:
                set_status("no files in folder"); return
            total = sum(os.path.getsize(p) for p in files)
            set_status(f"starting ({len(files)} files, {total} bytes)…", 0)

            self._send({"cmd": "char_begin", "name": name, "total": total})
            a = self._wait_ack("char_begin", timeout=10)
            if a is None:
                set_status("char_begin timed out — is sim running?"); return
            if not a.get("ok"):
                set_status(f"char_begin rejected: {a.get('error', a)}"); return

            sent = 0
            for path in files:
                fn   = os.path.basename(path)
                data = open(path, "rb").read()
                self._send({"cmd": "file", "path": fn, "size": len(data)})
                if not (self._wait_ack("file", 5) or {}).get("ok"):
                    set_status(f"file open failed: {fn}"); return
                for i in range(0, len(data), CHUNK_BYTES):
                    chunk = data[i:i + CHUNK_BYTES]
                    self._send({"cmd": "chunk", "d": base64.b64encode(chunk).decode()})
                    if not (self._wait_ack("chunk", 5) or {}).get("ok"):
                        set_status(f"chunk failed: {fn}+{i}"); return
                    sent += len(chunk)
                    set_status(f"uploading {fn}…", sent * 100.0 / total)
                self._send({"cmd": "file_end"})
                if not (self._wait_ack("file_end", 10) or {}).get("ok"):
                    set_status(f"file_end failed: {fn}"); return

            self._send({"cmd": "char_end"})
            ok = (self._wait_ack("char_end", 15) or {}).get("ok")
            set_status("done." if ok else "char_end failed", 100)
            if ok:
                self._send({"cmd": "species", "idx": 255})
        except Exception as exc:
            set_status(f"error: {exc}")
        finally:
            self._sim_upload_lock.release()
            on_done()

    # ─── My Characters list ───────────────────────────────────────────────────

    def _refresh_chars(self):
        for item in self.char_tree.get_children():
            self.char_tree.delete(item)
        if not os.path.isdir(CHARS_DIR):
            return
        for name in sorted(os.listdir(CHARS_DIR)):
            d = os.path.join(CHARS_DIR, name)
            m = os.path.join(d, "manifest.json")
            if not os.path.isdir(d) or not os.path.isfile(m):
                continue
            files = [f for f in os.listdir(d) if not f.startswith(".")]
            size  = sum(os.path.getsize(os.path.join(d, f))
                        for f in files if os.path.isfile(os.path.join(d, f)))
            self.char_tree.insert("", "end", iid=d, values=(
                name, len(files), f"{size//1024} KB"))

    def _selected_char_dir(self):
        sel = self.char_tree.selection()
        if not sel:
            self._qlog("sys", "Select a character first.")
            return None
        return sel[0]   # iid == absolute path

    def _char_upload_sim_any(self):
        """Upload selected character to sim — works in both Sim and Desktop mode."""
        d = self._selected_char_dir()
        if not d:
            return
        tgt  = self._hook_target.get()
        name = os.path.basename(d)
        self._char_action_progress.start(10)
        def done():
            self._inq.put(("log", ("sys", f"[upload] {name} done")))
            self._char_action_progress.stop()
            # Re-pause bridge in desktop mode after upload
            if tgt == "desktop":
                self.bridge.pause()
                self._start_keepalive()

        if tgt == "desktop":
            # Temporarily steal the TCP connection from keepalive
            self._stop_keepalive()
            self.bridge.resume()
            self._log("sys", "[upload] pausing keepalive for upload…")

        def _run_upload():
            if tgt == "desktop":
                if not self.bridge.wait_connected(timeout=5.0):
                    self._qlog("sys", "[upload] could not connect to sim (timeout)")
                    self.bridge.pause()
                    self._start_keepalive()
                    self._char_action_progress.stop()
                    return
            self._upload_to_sim(d, name, lambda t, p=None: self._qlog("sys", f"[sim] {t}"), done)

        threading.Thread(target=_run_upload, daemon=True).start()

    def _char_upload_sim(self):
        d = self._selected_char_dir()
        if not d:
            return
        name = os.path.basename(d)
        self._char_action_progress.start(10)
        def done():
            self._inq.put(("log", ("sys", f"[sim upload] {name} done")))
            self._char_action_progress.stop()
        threading.Thread(
            target=self._upload_to_sim,
            args=(d, name, lambda t, p=None: self._qlog("sys", f"[sim] {t}"), done),
            daemon=True).start()

    def _char_flash_usb(self):
        d = self._selected_char_dir()
        if not d:
            return
        script = os.path.join(TOOLS_DIR, "flash_character.py")
        self._run_subprocess([sys.executable, "-u", script, d],
                             label="[usb flash]",
                             progress=self._char_action_progress)

    def _char_upload_ble(self):
        d = self._selected_char_dir()
        if not d:
            return
        script = os.path.join(TOOLS_DIR, "ble_driver.py")
        self._run_subprocess([sys.executable, "-u", script, d],
                             label="[ble upload]",
                             progress=self._char_action_progress)

    def _run_subprocess(self, cmd, label, progress):
        """Run a command in a background thread, streaming stdout to the log."""
        progress.start(10)
        def worker():
            try:
                proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1)
                for line in proc.stdout:
                    self._qlog("sys", f"{label} {line.rstrip()}")
                proc.wait()
                self._qlog("sys", f"{label} exit {proc.returncode}")
            except Exception as exc:
                self._qlog("sys", f"{label} error: {exc}")
            finally:
                self._inq.put(("log", ("sys", "")))   # flush
                progress.stop()
        threading.Thread(target=worker, daemon=True).start()

    # ─── Petdex import ────────────────────────────────────────────────────────

    def _set_pdx(self, txt, pct=None):
        self._inq.put(("pdx", (txt, pct)))

    def _start_petdex_import(self):
        url = self.petdex_url.get().strip()
        if not url:
            return
        self.petdex_btn.configure(state="disabled")
        threading.Thread(target=self._petdex_worker,
                         args=(url, self.petdex_pixel_art.get()),
                         daemon=True).start()

    def _petdex_worker(self, url_or_name, pixel_art=False):
        STATES = ["sleep", "idle", "busy", "attention", "celebrate", "dizzy", "heart"]
        try:
            name    = re.split(r"[/?#]", url_or_name.rstrip("/"))[-1] or url_or_name
            out_dir = os.path.join(CHARS_DIR, name)
            manifest = os.path.join(out_dir, "manifest.json")

            if os.path.isfile(manifest):
                self._set_pdx(f"{name} already converted — uploading…", 72)
                self._qlog("sys", f"[petdex] '{name}' found, skipping download")
            else:
                self._set_pdx(f"Downloading {name}…", 2)
                r = subprocess.run(
                    ["sh", "-c", f"curl -sSf 'https://petdex.crafter.run/install/{name}' | sh"],
                    capture_output=True, text=True)
                if r.returncode != 0:
                    self._set_pdx(f"Download failed: {r.stderr.strip()[:50]}")
                    self._qlog("sys", f"[petdex] error: {r.stderr.strip()}")
                    return
                sheet = os.path.expanduser(f"~/.codex/pets/{name}/spritesheet.webp")
                if not os.path.exists(sheet):
                    self._set_pdx("spritesheet not found after install"); return
                self._set_pdx("Converting…", 18)
                script = os.path.join(TOOLS_DIR, "petdex_convert.py")
                cmd = [sys.executable, "-u", script, sheet,
                       "--name", name, "--out", out_dir]
                if pixel_art:
                    cmd.append("--pixel-art")
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1)
                done = 0
                for line in proc.stdout:
                    line = line.rstrip()
                    if not line:
                        continue
                    self._qlog("sys", f"[convert] {line}")
                    for s in STATES:
                        if f"{s}.gif" in line:
                            done += 1
                            self._set_pdx(f"Converting {s} ({done}/{len(STATES)})…",
                                          20 + done / len(STATES) * 50)
                proc.wait()
                if proc.returncode != 0:
                    self._set_pdx("Conversion failed — see log"); return

            self._set_pdx("Waiting for sim…", 72)
            if not self.bridge.wait_connected(timeout=15):
                self._set_pdx("Sim not connected"); return
            self._set_pdx("Uploading…", 73)
            self._upload_to_sim(
                out_dir, name,
                lambda t, p=None: self._set_pdx(t, p),
                lambda: None)
            self._refresh_chars()
        except Exception as exc:
            self._set_pdx(f"Error: {exc}")
            self._qlog("sys", f"[petdex] exception: {exc}")
        finally:
            self.petdex_btn.configure(state="normal")

    # ─── Strip import ─────────────────────────────────────────────────────────

    def _set_strip(self, txt, pct=None):
        self._inq.put(("strip", (txt, pct)))

    def _pick_strip_dir(self):
        path = filedialog.askdirectory(title="Choose strip sprite directory")
        if not path:
            return
        self.strip_dir.set(path)
        name = os.path.basename(path.rstrip("/")).lower().replace(" ", "_")
        if name:
            self.strip_name.set(name)
        self._scan_strip_dir(path)

    def _scan_strip_dir(self, path):
        pngs = sorted(f for f in os.listdir(path) if f.lower().endswith(".png"))
        if not pngs:
            return
        for cb in self.strip_state_combos.values():
            cb["values"] = pngs
        for s, hints in self._strip_hints.items():
            found = next(
                (fn for hint in hints for fn in pngs if hint in fn.lower()),
                None)
            self.strip_state_vars[s].set(found or pngs[0])
        idle_guess = self.strip_state_vars["idle"].get()
        for s in self.strip_state_vars:
            if self.strip_state_vars[s].get() == "—":
                self.strip_state_vars[s].set(idle_guess)

    def _start_strip_import(self):
        src_dir = self.strip_dir.get().strip()
        if not src_dir:
            return
        STATES = ["sleep", "idle", "busy", "attention", "celebrate", "dizzy", "heart"]
        mapping   = {s: self.strip_state_vars[s].get()
                     for s in STATES if self.strip_state_vars[s].get() not in ("—", "")}
        name      = self.strip_name.get().strip() or "character"
        bg        = self.strip_bg.get().strip()   or "000000"
        pixel_art = self.strip_pixel_art.get()
        self.strip_btn.configure(state="disabled")
        threading.Thread(target=self._strip_worker,
                         args=(src_dir, name, bg, mapping, pixel_art),
                         daemon=True).start()

    def _strip_worker(self, src_dir, name, bg, mapping, pixel_art):
        STATES = ["sleep", "idle", "busy", "attention", "celebrate", "dizzy", "heart"]
        try:
            out_dir  = os.path.join(CHARS_DIR, name)
            manifest = os.path.join(out_dir, "manifest.json")

            if os.path.isfile(manifest):
                self._set_strip(f"{name} already converted — uploading…", 72)
                self._qlog("sys", f"[strip] '{name}' found, skipping conversion")
            else:
                self._set_strip(f"Converting {name}…", 5)
                script = os.path.join(TOOLS_DIR, "strip_convert.py")
                cmd = [sys.executable, "-u", script, src_dir,
                       "--name", name, "--bg", bg, "--out", out_dir]
                for s, fn in mapping.items():
                    cmd += [f"--{s}", fn]
                if pixel_art:
                    cmd.append("--pixel-art")
                self._qlog("sys", f"[strip] {' '.join(cmd)}")
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, text=True, bufsize=1)
                done = 0
                for line in proc.stdout:
                    line = line.rstrip()
                    if not line:
                        continue
                    self._qlog("sys", f"[convert] {line}")
                    for s in STATES:
                        if f"{s}.gif" in line:
                            done += 1
                            self._set_strip(f"Converting {s} ({done}/{len(STATES)})…",
                                            5 + done / len(STATES) * 65)
                proc.wait()
                if proc.returncode != 0:
                    self._set_strip("Conversion failed — see log"); return

            self._set_strip("Waiting for sim…", 72)
            if not self.bridge.wait_connected(timeout=15):
                self._set_strip("Sim not connected"); return
            self._set_strip("Uploading…", 73)
            self._upload_to_sim(
                out_dir, name,
                lambda t, p=None: self._set_strip(t, p),
                lambda: None)
            self._refresh_chars()
        except Exception as exc:
            self._set_strip(f"Error: {exc}")
            self._qlog("sys", f"[strip] exception: {exc}")
        finally:
            self.strip_btn.configure(state="normal")

    # ─── Firmware flash ───────────────────────────────────────────────────────

    def _flash_firmware(self):
        self._pio_run("-t", "upload")

    def _flash_filesystem(self):
        self._pio_run("-t", "uploadfs")

    def _pio_run(self, *extra_args):
        env = self.fw_env.get()
        if not env:
            return
        self.fw_btn.configure(state="disabled")
        self.fs_btn.configure(state="disabled")
        self._inq.put(("fw", (f"Flashing {env}…", True)))
        cmd = ["pio", "run", "-e", env] + list(extra_args)

        def worker():
            try:
                proc = subprocess.Popen(
                    cmd, cwd=REPO_ROOT,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1)
                for line in proc.stdout:
                    self._qlog("sys", f"[pio] {line.rstrip()}")
                proc.wait()
                msg = "Done." if proc.returncode == 0 else f"Failed (exit {proc.returncode})"
                self._inq.put(("fw", (msg, False)))
                self._qlog("sys", f"[pio] {msg}")
            except FileNotFoundError:
                self._inq.put(("fw", ("pio not found — install PlatformIO Core", False)))
                self._qlog("sys", "[pio] not found — pip install platformio")
            except Exception as exc:
                self._inq.put(("fw", (f"Error: {exc}", False)))
            finally:
                self._inq.put(("log", ("sys", "")))
                self.fw_btn.configure(state="normal")
                self.fs_btn.configure(state="normal")

        threading.Thread(target=worker, daemon=True).start()

    # ─── log ─────────────────────────────────────────────────────────────────

    def _log(self, kind, line):
        if not line:
            return
        prefix = {"tx": "→ ", "rx": "← ", "sys": "  "}[kind]
        self.log.insert("end", prefix + line + "\n", kind)
        self.log.see("end")

    def _on_close(self):
        self.bridge.stop()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
