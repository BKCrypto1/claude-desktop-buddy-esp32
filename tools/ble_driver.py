#!/usr/bin/env python3
"""
Upload a character pack to a Claude Buddy device over BLE (Nordic UART Service).

Scans for devices advertising as "Claude-*", connects (the OS handles the
6-digit passkey pairing on first connect — just follow the system dialog and
enter the passkey shown on the device screen), then transfers the character
pack using the same char_begin / file / chunk / file_end / char_end protocol
as the simulator's Import buttons.

Requirements:
  pip install bleak

Usage:
  python3 tools/ble_driver.py characters/bufo
  python3 tools/ble_driver.py characters/mushroom --device "Claude-AB12"
  python3 tools/ble_driver.py --list          # scan and list nearby Claude devices
"""
import argparse
import asyncio
import base64
import glob
import json
import os
import sys

try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakError
except ImportError:
    sys.exit("bleak not installed — run:  pip install bleak")

NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX      = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # desktop → device (write)
NUS_TX      = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # device → desktop (notify)

# File data bytes per chunk. Base64 expands 3:4, plus ~20 bytes JSON framing.
# 192 bytes → ~276-byte JSON line, sent in multiple MTU-sized BLE writes;
# the firmware reassembles until '\n' so line length > MTU is fine.
CHUNK_BYTES = 192


class BuddyBLE:
    def __init__(self, client: BleakClient):
        self._client = client
        self._rx: asyncio.Queue = asyncio.Queue()
        self._buf = ""

    def _on_notify(self, _sender, data: bytearray):
        self._buf += data.decode("utf-8", errors="replace")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line:
                try:
                    self._rx.put_nowait(json.loads(line))
                except ValueError:
                    pass

    async def start_notify(self):
        await self._client.start_notify(NUS_TX, self._on_notify)

    async def send(self, obj: dict):
        line = (json.dumps(obj, separators=(",", ":")) + "\n").encode()
        # Split line into MTU-sized writes; firmware accumulates until '\n'.
        mtu = max(20, self._client.mtu_size - 3)
        for i in range(0, len(line), mtu):
            await self._client.write_gatt_char(NUS_RX, line[i:i + mtu], response=False)

    async def wait_ack(self, name: str, timeout: float = 10.0) -> dict | None:
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return None
            try:
                obj = await asyncio.wait_for(self._rx.get(), timeout=remaining)
                if obj.get("ack") == name:
                    return obj
                # Discard non-matching messages (heartbeats, etc.)
            except asyncio.TimeoutError:
                return None


async def scan_devices(timeout: float = 6.0) -> list:
    """Return BLE devices whose name starts with 'Claude'."""
    print(f"Scanning for Claude Buddy devices ({timeout:.0f}s)…")
    found = await BleakScanner.discover(timeout=timeout)
    return [d for d in found if d.name and d.name.startswith("Claude")]


async def pick_device(name_filter: str | None) -> str:
    devices = await scan_devices()
    if not devices:
        sys.exit(
            "No Claude Buddy devices found.\n"
            "  • Make sure the device is powered on and within range.\n"
            "  • Bluetooth must be enabled on this Mac."
        )

    if name_filter:
        matches = [d for d in devices if name_filter.lower() in d.name.lower()]
        if not matches:
            print("Device not found. Nearby Claude devices:")
            for d in devices:
                print(f"  {d.name}  {d.address}")
            sys.exit(1)
        return matches[0].address

    if len(devices) == 1:
        d = devices[0]
        print(f"Found: {d.name}  ({d.address})")
        return d.address

    print("Multiple Claude devices found:")
    for i, d in enumerate(devices):
        print(f"  {i + 1}.  {d.name}  ({d.address})")
    while True:
        try:
            choice = int(input("Select device number: ")) - 1
            if 0 <= choice < len(devices):
                return devices[choice].address
        except (ValueError, EOFError):
            pass


async def upload(buddy: BuddyBLE, char_dir: str) -> bool:
    manifest_path = os.path.join(char_dir, "manifest.json")
    name = json.loads(open(manifest_path).read())["name"]

    files = sorted(
        p for p in glob.glob(os.path.join(char_dir, "*"))
        if os.path.isfile(p) and not os.path.basename(p).startswith(".")
    )
    total = sum(os.path.getsize(p) for p in files)
    print(f"Uploading '{name}'  ({total:,} bytes, {len(files)} files)")

    await buddy.send({"cmd": "char_begin", "name": name, "total": total})
    a = await buddy.wait_ack("char_begin", timeout=10)
    if not a:
        print("char_begin timed out — is the device awake?"); return False
    if not a.get("ok"):
        print(f"char_begin rejected: {a.get('error', a)}"); return False

    sent = 0
    for path in files:
        fn   = os.path.basename(path)
        data = open(path, "rb").read()

        await buddy.send({"cmd": "file", "path": fn, "size": len(data)})
        a = await buddy.wait_ack("file", timeout=5)
        if not a or not a.get("ok"):
            print(f"\nfile open failed: {fn}"); return False

        for i in range(0, len(data), CHUNK_BYTES):
            chunk = data[i:i + CHUNK_BYTES]
            await buddy.send({"cmd": "chunk", "d": base64.b64encode(chunk).decode()})
            a = await buddy.wait_ack("chunk", timeout=5)
            if not a or not a.get("ok"):
                print(f"\nchunk failed: {fn}+{i}"); return False
            sent += len(chunk)
            pct  = sent / total * 100
            bar  = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            print(f"\r  [{bar}] {pct:5.1f}%  {fn:<20}", end="", flush=True)

        await buddy.send({"cmd": "file_end"})
        a = await buddy.wait_ack("file_end", timeout=10)
        if not a or not a.get("ok"):
            print(f"\nfile_end failed: {fn}"); return False

    print()
    await buddy.send({"cmd": "char_end"})
    a = await buddy.wait_ack("char_end", timeout=15)
    if a and a.get("ok"):
        print(f"Done. '{name}' is now active.")
        await buddy.send({"cmd": "species", "idx": 255})   # switch to GIF mode
        return True
    else:
        print(f"char_end failed: {a}"); return False


async def main():
    parser = argparse.ArgumentParser(
        description="Upload a Claude Buddy character pack over BLE"
    )
    parser.add_argument("char_dir", nargs="?",
                        help="Character directory (contains manifest.json + .gif files)")
    parser.add_argument("--device", "-d", default=None,
                        help="Device name filter, e.g. 'Claude-AB12' (partial match)")
    parser.add_argument("--list", "-l", action="store_true",
                        help="Scan and list nearby Claude devices, then exit")
    args = parser.parse_args()

    if args.list:
        devices = await scan_devices()
        if not devices:
            print("No Claude Buddy devices found.")
        else:
            print(f"Found {len(devices)} device(s):")
            for d in devices:
                print(f"  {d.name:<20}  {d.address}")
        return

    if not args.char_dir:
        parser.error("char_dir is required unless --list is used")

    manifest = os.path.join(args.char_dir, "manifest.json")
    if not os.path.isfile(manifest):
        sys.exit(f"No manifest.json in {args.char_dir} — run the converter first")

    address = await pick_device(args.device)
    print(f"Connecting to {address}…")
    print("  (First connect triggers BLE pairing — enter the passkey shown on the device.)")

    async with BleakClient(address) as client:
        print(f"Connected  (MTU {client.mtu_size} bytes)")
        buddy = BuddyBLE(client)
        await buddy.start_notify()
        await asyncio.sleep(0.3)   # let the notification subscription settle
        success = await upload(buddy, args.char_dir)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nCancelled.")
    except BleakError as e:
        sys.exit(f"BLE error: {e}")
