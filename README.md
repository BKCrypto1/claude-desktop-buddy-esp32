# claude-desktop-buddy — ESP32 AMOLED port

<img src="image.jpg" width="400" />

Claude for macOS and Windows can connect Claude Cowork and Claude Code to
maker devices over BLE, so developers and makers can build hardware that
displays permission prompts, recent messages, and other interactions.

This is a port of [anthropics/claude-desktop-buddy](https://github.com/anthropics/claude-desktop-buddy)
(originally targeting M5StickC Plus) to four Waveshare ESP32 AMOLED
boards. The BLE wire protocol is unchanged — same pairing, same desktop
apps, just a larger screen.

> **Building your own device?** You don't need any of the code here. See
> **[REFERENCE.md](REFERENCE.md)** for the wire protocol: Nordic UART
> Service UUIDs, JSON schemas, and the folder push transport.

## Supported boards

All four run the **same main.cpp / UI** — board-specific wiring, drivers and
canvas→panel scaling are isolated in `src/hw/` + one header per board
under `src/boards/`.

| | [ESP32-S3-Touch-AMOLED-1.8](https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-1.8) | [ESP32-S3-Touch-AMOLED-1.75C](https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-1.75C) | [ESP32-C6-Touch-AMOLED-2.16](https://docs.waveshare.com/ESP32-C6-Touch-AMOLED-2.16) | [ESP32-S3-Touch-AMOLED-2.16](https://docs.waveshare.com/ESP32-S3-Touch-AMOLED-2.16) |
| --- | --- | --- | --- | --- |
| MCU | ESP32-S3R8 (8 MB OPI PSRAM, 8 MB flash) | same | ESP32-C6FH8 (160 MHz RISC-V single-core, 8 MB flash, **no PSRAM**) | ESP32-S3R8 (8 MB OPI PSRAM, 8 MB flash) |
| Panel | 1.8" **rectangular** 368×448 AMOLED | 1.75" **round** 466×466 AMOLED | 2.16" **rounded-square** 480×480 AMOLED | 2.16" **rounded-square** 480×480 AMOLED (**rotated 90°**) |
| Display driver | SH8601 (QSPI) | CO5300 (QSPI) | SH8601 (QSPI) | CO5300 (QSPI) |
| Touch | FT3168 @ 0x38 | CST92xx @ 0x5A | CST9217 @ 0x5A | CST9217 @ 0x5A |
| GPIO expander | TCA9554 (LCD/TP resets routed through it) | none — resets are direct GPIOs | none — resets are direct GPIOs | none — resets are direct GPIOs |
| RTC | PCF85063 (I²C) | none — software clock synced from desktop | PCF85063 (I²C) | PCF85063 (I²C) |
| IMU | QMI8658 | same | same | same |
| PMU | AXP2101 | same | same | same |
| Audio | ES8311 + amp + speaker | same | ES8311 + ES7210 (output + mic codec) | same |
| Buttons | Key1 (GPIO0 BOOT) + AXP PEK | same (physical layout swapped; corrected in firmware) | three: PWR/IO10/BOOT; PWR is active-HIGH via MOSFET inverter + AXP PWRON | three: PWR/IO18/BOOT; PWR is active-HIGH via BSS138 inverter |
| Canvas → panel | 184×224 canvas → **2× nearest-neighbor** → 368×448 | 184×224 canvas → **1.5× bilinear** → 276×336 centred in 466×466 (black border) | 184×224 canvas → **2× nearest-neighbor** → 368×448 centred at (56, 16) in 480×480 (56 px L/R / 16 px T/B black border) | 184×224 canvas → **2× nearest-neighbor** → 368×448 centred at (56, 16) in 480×480 (56 px L/R / 16 px T/B black border) |

Internal canvas is **184×224** on all four. The 1.75C rounds the content
inside its circular bezel; keeping the logical canvas identical means
UI code, fonts and all buddy rendering are completely board-agnostic.

The firmware targets ESP32-S3 and ESP32-C6 with Arduino framework 3.x via the
[pioarduino](https://github.com/pioarduino/platform-espressif32) platform.

## Flashing

Install
[PlatformIO Core](https://docs.platformio.org/en/latest/core/installation/),
then pick the env that matches your board:

```bash
# 1.8" rectangular AMOLED (ESP32-S3)
pio run -e waveshare-esp32s3-touch-amoled-1-8 -t upload

# 1.75C round AMOLED (ESP32-S3)
pio run -e waveshare-esp32s3-touch-amoled-1-75c -t upload

# 2.16" rounded-square AMOLED (ESP32-C6)
pio run -e waveshare-esp32c6-touch-amoled-2-16 -t upload

# 2.16" rounded-square AMOLED (ESP32-S3)
pio run -e waveshare-esp32s3-touch-amoled-2-16 -t upload
```

If you're starting from a previously-flashed device (e.g. the factory
Xiaozhi firmware), wipe it first:

```bash
pio run -e <env> -t erase && pio run -e <env> -t upload
```

LittleFS auto-formats on first boot if the partition isn't recognised.

### Adding another board

1. Add a new header at `src/boards/board_<name>.h` declaring all
   `PIN_*`, `BOARD_HW_W/H`, `BOARD_SAFE_INSET`, and capability flags —
   the existing headers cover ~16 flags between them
   (`BOARD_HAS_PSRAM`, `BOARD_HAS_TCA9554`, `BOARD_HAS_PCF85063`,
   `BOARD_HAS_AXP2101`, `BOARD_HAS_PA_CTRL`, `BOARD_HAS_KEY2`,
   `BOARD_DISPLAY_CO5300`, `BOARD_DISPLAY_LETTERBOX`,
   `BOARD_DISPLAY_OFFSET_X/Y`, `BOARD_DISPLAY_SCALE`,
   `BOARD_DISPLAY_PUSH_STREAMED`, `BOARD_DISPLAY_SH8601_VENDOR_INIT`,
   `BOARD_CO5300_COL_OFFSET`, `BOARD_CO5300_MADCTL`,
   `BOARD_LCD_RST_VIA_PMU`, `BOARD_AXP_PWRON_4S_OFF`,
   `BOARD_AXP_ENABLE_AUX_LDOS`, `BOARD_KEY1_ACTIVE_HIGH`,
   `BOARD_BTN_THIRD`, `BOARD_BTN_SWAP_AB`, `BOARD_TOUCH_CST92XX`).
   Pick the values that match your board.
2. Add a `#elif defined(BOARD_<NAME>)` branch in `src/hw/pins.h`.
3. Add a matching `[env:<name>]` block in `platformio.ini` with the
   `-DBOARD_<NAME>` build flag.

`main.cpp` and `buddies/` stay untouched.

Once running you can also wipe everything from the device itself:
**hold the A button (Key1 on 1.8/1.75C, PWR on the 2.16 boards) →
settings → reset → factory reset → tap twice**.

## Pairing

To pair your device with Claude, first enable developer mode (**Help →
Troubleshooting → Enable Developer Mode**). Then open the Hardware Buddy
window in **Developer → Open Hardware Buddy…**, click **Connect**, and pick
your device from the list (advertised as `Claude-XXXX`). macOS will prompt
for Bluetooth permission on first connect; grant it.

The device shows a 6-digit passkey on screen — type it on the desktop to
complete LE Secure Connections bonding. Once paired, the bridge
auto-reconnects whenever both sides are awake.

## Controls

### ESP32-S3 boards (1.8 & 1.75C)

The board has two physical keys. **Key1** is the BOOT button (acts as
"A" in the table). **Key3** is the AXP power key — short-press is "B",
long-press toggles screen off, very-long-press hardware-shuts-down.

|                          | Normal               | Pet         | Info        | Approval    |
| ------------------------ | -------------------- | ----------- | ----------- | ----------- |
| **Key1** (BOOT)          | next screen          | next screen | next screen | **approve** |
| **Key3** (PWR, short)    | scroll transcript    | next page   | next page   | **deny**    |
| **Hold Key1**            | menu                 | menu        | menu        | menu        |
| **Key3** (PWR, ~1s long) | toggle screen off    |             |             |             |
| **Key3** (PWR, ~6s)      | hard power off       |             |             |             |
| **Shake**                | dizzy                |             |             | —           |
| **Face-down**            | nap (energy refills) |             |             |             |

### ESP32-C6-Touch-AMOLED-2.16 controls

The board has three physical keys:
- **PWR** (middle) — primary action / confirm (= A button)
- **IO10** (left) — secondary / back / scroll (= B button)
- **BOOT** (right) — open menu shortcut

|                          | Normal               | Pet         | Info        | Approval    |
| ------------------------ | -------------------- | ----------- | ----------- | ----------- |
| **PWR** (middle)         | next screen          | next screen | next screen | **approve** |
| **IO10** (left, short)   | scroll transcript    | next page   | next page   | **deny**    |
| **Hold PWR**             | menu                 | menu        | menu        | menu        |
| **BOOT** (right)         | open menu (shortcut) | open menu   | open menu   | open menu   |
| **PWR held 4 s**         | power off (AXP cuts ALDO3; press again to wake) |             |             |             |
| **Shake**                | dizzy                |             |             | —           |
| **Face-down**            | nap (energy refills) |             |             |             |

### ESP32-S3-Touch-AMOLED-2.16 controls

The board has three physical keys:
- **PWR** (middle) — primary action / confirm (= A button)
- **IO18** (left) — secondary / back / scroll (= B button)
- **BOOT** (right) — open menu shortcut

|                          | Normal               | Pet         | Info        | Approval    |
| ------------------------ | -------------------- | ----------- | ----------- | ----------- |
| **PWR** (middle)         | next screen          | next screen | next screen | **approve** |
| **IO18** (left, short)   | scroll transcript    | next page   | next page   | **deny**    |
| **Hold PWR**             | menu                 | menu        | menu        | menu        |
| **BOOT** (right)         | open menu (shortcut) | open menu   | open menu   | open menu   |
| **PWR held 4 s**         | power off (AXP cuts ALDO3; press again to wake) |             |             |             |
| **Shake**                | dizzy                |             |             | —           |
| **Face-down**            | nap (energy refills) |             |             |             |

### Touch (all boards)

Touch is supplemental — keys remain primary:

- **Swipe up / down** — cycle through all 9 pages (Normal → Pet ×2 → Info ×6). The A button (Key1 on S3 1.8/1.75C, PWR on the 2.16 boards) short-press remains a coarser 3-mode jumper.
- **Swipe left / right** (clock home screen) — cycle ASCII species
- **Approval screen** — tap upper half = approve, lower half = deny
- **Menu / Settings / Reset** — tap a row to select+confirm in one go
- **Info / Pet pages** — tap top-right corner to cycle pages
- **Normal HUD** — tap buddy = heart, bottom 32 px = scroll transcript

### Sleep & wake

- **USB plugged** — never auto-offs; the clock face stays visible
- **Battery + clock visible** — auto-off after **5 minutes**
- **Battery + other screens** — auto-off after **30 seconds**
- **Approval prompt up** — never auto-offs

Any key press or screen tap wakes the panel.

## Notable differences from the M5StickC original

- **Display layer** — Arduino_GFX + PSRAM Canvas (was M5.Lcd / TFT_eSprite)
- **Attention indicator** — small red pill at top of screen
  (M5 used a GPIO red LED; the AMOLED board has none)
- **Landscape clock removed** — 368×448 is near-square; rotation pointless
- **Battery current not exposed** — XPowersLib / AXP2101 only reports
  voltage, %, and isCharging. The info-page "current" reads 0 mA
- **Transcript supports CJK** — uses `chill7_h_cjk` font for the HUD lines
  so Chinese / Japanese log entries render legibly
- **Other UI strings stay ASCII** — non-ASCII bytes in `msg`, `promptTool`
  and `promptHint` are replaced with random Matrix-rain symbols rather
  than rendering as garbage glyphs
- **ESP32-S3 2.16" rotation** — the Waveshare ESP32-S3-Touch-AMOLED-2.16 panel is physically mounted 90° rotated from its natural orientation; this is handled in firmware via MADCTL=0xA0 and is transparent to the UI code

## Per-state animations

| State       | Trigger                                              | Feel                          |
| ----------- | ---------------------------------------------------- | ----------------------------- |
| `sleep`     | time-of-day 22:00–7:00 (idle); clock face ambient   | eyes closed, slow breathing   |
| `idle`      | connected, nothing running                           | blinking, looking around      |
| `busy`      | tool running / sessions active                       | sweating, working             |
| `attention` | approval pending (Bash/Agent gate)                   | alert, **red top-bar pulses** |
| `celebrate` | level up (every 50K tokens); slow approval (≥ 5 s)  | confetti, bouncing            |
| `dizzy`     | shake device; denial via buddy                       | spiral eyes, wobbling         |
| `heart`     | fast approval (< 5 s); tap buddy on home screen      | floating hearts               |

Nineteen ASCII species, each with all seven animations. **Settings →
ascii pet** cycles them; choice persists in NVS.

## Custom GIF characters

A character pack is a folder containing `manifest.json` and one GIF per
state. GIFs are 96 px wide; up to ~140 px tall keeps the character above
the HUD. The whole pack must fit under 1.8 MB.

```json
{
  "name": "bufo",
  "colors": {
    "body": "#6B8E23",
    "bg": "#000000",
    "text": "#FFFFFF",
    "textDim": "#808080",
    "ink": "#000000"
  },
  "states": {
    "sleep": "sleep.gif",
    "idle": ["idle_0.gif", "idle_1.gif", "idle_2.gif"],
    "busy": "busy.gif",
    "attention": "attention.gif",
    "celebrate": "celebrate.gif",
    "dizzy": "dizzy.gif",
    "heart": "heart.gif"
  }
}
```

State values can be a single filename or an array. Arrays rotate
loop-by-loop, useful for an idle activity carousel.

**Settings → reset → delete char** reverts to ASCII mode.

### Installing a character pack

Three ways, in order of convenience:

**1. Buddy Manager (GUI)** — open the **Characters** tab, select a pack
from the list, and click **Flash USB** or **Upload BLE** (see
[Desktop simulator](#desktop-simulator)).

**2. BLE (wireless, no GUI needed)**

```bash
pip install bleak   # once

python3 tools/ble_driver.py --list              # find nearby devices
python3 tools/ble_driver.py characters/bufo     # upload to first device found
python3 tools/ble_driver.py characters/bufo --device "Claude-AB12"
```

First connect triggers BLE pairing — a 6-digit passkey appears on the
device screen; enter it in the macOS system dialog. Subsequent connects
auto-bond. The device switches to GIF mode immediately after upload.

**3. USB (fastest for iteration)**

```bash
python3 tools/flash_character.py characters/bufo
```

Stages the pack into `data/` and runs `pio run -t uploadfs` over USB.

### Importing from Petdex

[Petdex](https://petdex.crafter.run) is a catalog of animated sprite characters.
`tools/petdex_convert.py` slices a Petdex spritesheet (1536×1872, ARGB WebP)
into the seven Claude Buddy GIF states at 96×104 px.

```bash
# Download the spritesheet (drops it in ~/.codex/pets/<name>/)
curl -sSf https://petdex.crafter.run/install/mallow | sh

# Convert — illustrated/smooth characters (default)
python3 tools/petdex_convert.py ~/.codex/pets/mallow/spritesheet.webp \
    --name mallow --bg 000000 --out characters/mallow

# Convert — pixel-art characters (chunky sprites, crisp edges)
python3 tools/petdex_convert.py ~/.codex/pets/boba/spritesheet.webp \
    --name boba --bg 000000 --pixel-art --out characters/boba
```

| flag | when to use |
| --- | --- |
| *(none)* | illustrated / smooth characters — Lanczos resize + RGB565-snapped palette |
| `--pixel-art` | chunky pixel-art sprites — nearest-neighbor resize + exact palette |

The Buddy Manager's **Characters → Petdex import** field does the download +
convert + upload in one step. Already-converted packs skip the
download+convert on re-import.

### Importing from itch.io / horizontal-strip packs

Many sprite packs from itch.io use a **horizontal strip** format — one PNG
per animation, frames laid out left to right in a single row.
`tools/strip_convert.py` handles these:

```bash
python3 tools/strip_convert.py /path/to/sprites/ \
    --name mushroom --bg 000000 --pixel-art \
    --idle   Mushroom-Idle.png \
    --busy   Mushroom-Run.png \
    --celebrate Mushroom-Attack.png \
    --attention Mushroom-Hit.png \
    --sleep  Mushroom-Stun.png \
    --dizzy  Mushroom-Stun.png \
    --heart  Mushroom-Idle.png
```

Frame width is auto-detected from the GCD of all specified files' widths.
Multiple Claude states can share the same source file (e.g. `--sleep` and
`--dizzy` both pointing at the same stun animation). Unspecified states fall
back to `--idle`.

The Buddy Manager's **Characters → Strip import** panel provides a directory
browser and seven dropdowns that auto-populate and keyword-guess the mapping
when you pick a folder.

## Desktop simulator & Buddy Manager

`tools/sim_driver.py` is a tabbed **Buddy Manager** app that covers the
full development workflow — simulator control, character management, and
firmware flashing — in one window.

Requires SDL2 and Python 3 with Tkinter:

```bash
brew install sdl2
brew install python-tk@3.14   # or whichever Python version you have
```

```bash
cd sim && make           # build sim/build/buddy-sim
sim/build/buddy-sim      # run the firmware in an SDL window

# in another terminal:
python3 tools/sim_driver.py
```

### Target modes

The Buddy Manager has four target modes (toggle via `tools/buddy_target.sh` or the radio buttons):

| Mode | Who owns TCP | Hook behaviour | Use when |
| --- | --- | --- | --- |
| **Desktop** | keepalive | Hooks drive state; approval prompts block Claude | Actively using Claude Code |
| **Sim** | bridge (sim_driver) | Manual controls only; keepalive stopped | Testing animations manually |
| **Hardware** | BLE | BLE-only; both bridge and keepalive stopped | Real device connected |
| **Off** | — | Everything paused | |

### Desktop mode (Claude Code hooks)

In **Desktop** mode the buddy reacts to live Claude Code activity via hooks wired in
`~/.claude/settings.json`. A keepalive process owns the TCP connection and translates
the shared state file (`~/.buddy_state`) into bridge payloads every 50 ms (or
instantly on change).

**Hook → animation mapping:**

| Hook event | Buddy state | Notes |
| --- | --- | --- |
| PreToolUse (safe read-only) | busy | grep, cat, git log, etc. — auto-approved |
| PreToolUse (Bash / Agent) | attention | Blocks Claude up to 60 s for your decision |
| PostToolUse | busy → idle | Clears approval screen |
| Stop | celebrate | Claude finished responding |
| Notification | attention | Something needs your attention |

**Approval flow (Desktop mode):**

1. Claude wants to run a Bash command or spawn an Agent
2. Buddy shows approval screen — tap **upper half** to approve, **lower half** to deny
3. Buddy sends decision back; Claude proceeds or is blocked
4. Fast approval (< 5 s) triggers a heart animation; denial triggers dizzy

**Clock & sleep in Desktop mode:**

The clock face appears automatically when Claude is idle and the RTC has been synced
(time is sent from the desktop on connect). Between 22:00–7:00 the character plays
its sleep animation on top of the clock. Any Claude activity (tool use, sessions
running) hides the clock immediately.

### Simulator tab

Drives the desktop sim over TCP (`127.0.0.1:31415`) instead of BLE GATT,
mirroring what the Hardware Buddy app pushes to real hardware:

- Spinboxes for `total` / `running` / `waiting` and token counters
- **Quick-set buttons** for all 7 buddy states (Sleep / Idle / Busy / Attention
  top row; Celebrate / Dizzy / Heart bottom row) — one click sets counters and
  fires the matching animation
- Transcript box for `entries[]`
- Approval prompt sender (tool + hint) — log shows the device's reply
- Time sync, status, owner/pet name commands
- Species dropdown (19 ASCII species + GIF mode)
- Character upload: pick a folder and stream it to the sim via the
  `char_begin` / `file` / `chunk` / `file_end` / `char_end` protocol

### Characters tab

- **My Characters** — lists every pack in `characters/` with file count
  and size. Select one and click:
  - **Upload to sim** — stream over TCP to the running simulator (works in both Sim and Desktop mode)
  - **Flash USB** — stage into `data/` and run `uploadfs` via PlatformIO
  - **Upload BLE** — send wirelessly to real hardware via `ble_driver.py`
  - **Set active** — upload and switch to the selected character
- **Active character** — species dropdown + **Set on device** button to switch without re-uploading
- **Petdex import** — paste a URL or pet name, tick Pixel art if needed,
  click Import. Downloads, converts, and uploads to the sim in one step.
- **Strip import** — pick a directory of strip PNGs, assign each Claude
  state to a source file (auto-guessed from filenames), click Import.

### Firmware tab

- Board dropdown populated from `platformio.ini` envs
- **Flash Firmware** — runs `pio run -e <env> -t upload`
- **Flash Filesystem** — runs `pio run -e <env> -t uploadfs`
- All PlatformIO output streams to the shared log panel

### Sim window keys

| key | mapped to |
| --- | --- |
| Space / Enter | KEY1 (BtnA — primary / approve) |
| `B` / → | KEY2 (BtnB — secondary / deny) |
| `M` | synthesized BtnA long-press (BOOT key) |
| `S` | IMU shake spike (drives dizzy state) |
| `F` | toggle face-down (drives nap) |
| `U` | toggle USB-present (changes screen-off timeout) |
| Esc | quit |

For repeatable demos, `sim_scenario.py` plays a `.jsonl` script:

```bash
python3 tools/sim_scenario.py tools/demos/busy_session.jsonl
```

The simulator's LittleFS lives in `~/.cache/buddy-sim/fs/` and NVS in
`~/.cache/buddy-sim/nvs.json` — delete those to factory-reset.

## Project layout

```
src/
  main.cpp           — loop, state machine, UI screens (board-agnostic)
  buddy.{cpp,h}      — ASCII species dispatch + render helpers
  buddies/           — one file per species (19 total), seven anim functions each
  character.{cpp,h}  — GIF decode + render
  ble_bridge.{cpp,h} — Nordic UART service, line-buffered TX/RX
  data.h             — wire protocol, JSON parse, CJK matrixifier
  xfer.h             — folder push receiver
  stats.h            — NVS-backed stats, settings, owner, species choice
  boards/            — one .h per supported board (pins + capability flags)
  hw/                — board HAL (display, input, power, imu, rtc,
                       audio, expander, border). pins.h dispatches on
                       the BOARD_* build flag
lib/
  ES8311/            — vendored Espressif codec driver
  Arduino_DriveBus/  — vendored FT3168 touch driver (1.8)
  Adafruit_XCA9554/  — vendored TCA9554 expander driver (1.8)
characters/          — converted GIF character packs (gitignored)
tools/
  sim_driver.py      — Buddy Manager: tabbed app (Simulator / Characters / Firmware)
  sim_scenario.py    — replay .jsonl demo scripts against the simulator
  petdex_convert.py  — Petdex spritesheet → 7-state GIF character pack
  strip_convert.py   — itch.io horizontal-strip PNG → 7-state GIF character pack
  ble_driver.py      — BLE character upload to real hardware (pip install bleak)
  flash_character.py — USB LittleFS staging (pio uploadfs, skip BLE round-trip)
  prep_character.py  — normalise third-party GIF packs for the Hardware Buddy app
sim/                 — desktop simulator (SDL2; see Desktop simulator)
docs/superpowers/    — design specs + implementation plans
```

CST92xx touch (1.75C, both 2.16 boards) and PCF85063 RTC (1.8, both
2.16 boards) come in through `SensorLib` via `platformio.ini` lib_deps
rather than being vendored.

## Availability

The BLE API is only available when the Claude desktop apps are in
developer mode (**Help → Troubleshooting → Enable Developer Mode**).
It's intended for makers and developers and isn't an officially
supported product feature.
