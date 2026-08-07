#!/usr/bin/env python3
"""
MAC Address Spoofer — Premium Terminal Edition
==============================================
A beautiful terminal toolkit for Windows to view, randomize, spoof and
restore network adapter MAC addresses. Pure standard library (no pip
dependencies required).

Requires Administrator privileges for spoofing operations.

LEGAL DISCLAIMER: This tool is provided for educational purposes and
legitimate privacy/testing use only. Use responsibly and in accordance
with your local laws and terms of service.
"""

import ctypes
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
import platform

VERSION = "4.0"

# ── UTF-8 output (so box-drawing & emoji render in any modern console) ──────
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── ANSI colors ──────────────────────────────────────────────────────────────
class C:
    RESET   = "\x1b[0m"
    BOLD    = "\x1b[1m"
    DIM     = "\x1b[2m"
    ITALIC  = "\x1b[3m"
    UNDER   = "\x1b[4m"
    BLACK   = "\x1b[30m"
    RED     = "\x1b[31m"
    GREEN   = "\x1b[32m"
    YELLOW  = "\x1b[33m"
    BLUE    = "\x1b[34m"
    MAGENTA = "\x1b[35m"
    CYAN    = "\x1b[36m"
    WHITE   = "\x1b[37m"
    B_RED    = "\x1b[91m"
    B_GREEN  = "\x1b[92m"
    B_YELLOW = "\x1b[93m"
    B_BLUE   = "\x1b[94m"
    B_MAGENTA = "\x1b[95m"
    B_CYAN   = "\x1b[96m"
    B_WHITE  = "\x1b[97m"
    BG_BLACK  = "\x1b[40m"
    BG_RED    = "\x1b[41m"
    BG_GREEN  = "\x1b[42m"
    BG_YELLOW = "\x1b[43m"
    BG_BLUE   = "\x1b[44m"
    BG_MAGENTA = "\x1b[45m"
    BG_CYAN   = "\x1b[46m"
    BG_WHITE  = "\x1b[47m"

# ── Enable ANSI colors on Windows (proper VT processing) ────────────────────
def enable_ansi_colors():
    """Enable VT escape sequences on Windows 10+ consoles.
    The 'os.system("")' trick + ctypes OR of ENABLE_VIRTUAL_TERMINAL_PROCESSING.
    """
    if os.name != "nt":
        return
    try:
        os.system("")
    except Exception:
        pass
    try:
        k32 = ctypes.windll.kernel32
        handle = k32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32(0)
        if k32.GetConsoleMode(handle, ctypes.byref(mode)):
            k32.SetConsoleMode(handle, mode.value | 0x0004)  # VT processing
    except Exception:
        pass

# ── Accent color (theme) ────────────────────────────────────────────────────
ACCENT = C.CYAN

# ── Text helpers (ANSI-aware) ───────────────────────────────────────────────
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

def vlen(s):
    """Visible length of a (possibly ANSI-colored) string.
    Emojis count as 2 cells, variation selectors / combining marks as 0,
    matching how Windows Terminal & VS Code render them."""
    s = ANSI_RE.sub("", s)
    total = 0
    for ch in s:
        cp = ord(ch)
        cat = unicodedata.category(ch)
        if cp in (0xFE0E, 0xFE0F) or cat in ("Mn", "Me", "Cf"):
            continue  # zero-width: variation selectors, combining, ZWJ
        if cp >= 0x1F000 or 0x2600 <= cp <= 0x27BF or \
           unicodedata.east_asian_width(ch) in ("W", "F"):
            total += 2
        else:
            total += 1
    return total

def pad(s, width, right=False):
    diff = width - vlen(s)
    if diff <= 0:
        return s
    return (" " * diff + s) if right else (s + " " * diff)

def center_text(s, width):
    diff = width - vlen(s)
    if diff <= 0:
        return s
    left = diff // 2
    return " " * left + s + " " * (diff - left)

def cprint(text, color=C.WHITE, end="\n"):
    print(f"{color}{text}{C.RESET}", end=end)

def panel(title, lines, border=None, title_center=False):
    """Draw a boxed panel. lines = list of colored strings."""
    border = ACCENT if border is None else border
    w = max([vlen(l) for l in lines] + [0])
    out = [f"  {border}┌─{'─' * (w + 2)}─┐{C.RESET}"]
    if title:
        t = center_text(title, w + 2) if title_center else title
        out.append(f"  {border}│ {pad(t, w + 2)} │{C.RESET}")
        out.append(f"  {border}├─{'─' * (w + 2)}─┤{C.RESET}")
    for l in lines:
        out.append(f"  {border}│ {pad(l, w + 2)} │{C.RESET}")
    out.append(f"  {border}└─{'─' * (w + 2)}─┘{C.RESET}")
    return "\n".join(out)

def print_table(headers, rows):
    """Print a box-drawn table. Cells may contain ANSI colors."""
    widths = [vlen(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], vlen(cell))
    hdr = [f"{C.BOLD}{ACCENT}{h}{C.RESET}" for h in headers]
    border = lambda l, s, r: "  " + l + s.join("─" * (w + 2) for w in widths) + r
    print(f"{ACCENT}{border('┌', '┬', '┐')}{C.RESET}")
    print("  │" + "│".join(f" {pad(h, widths[i])} " for i, h in enumerate(hdr)) + "│")
    print(f"{ACCENT}{border('├', '┼', '┤')}{C.RESET}")
    for row in rows:
        print("  │" + "│".join(f" {pad(cell, widths[i])} " for i, cell in enumerate(row)) + "│")
    print(f"{ACCENT}{border('└', '┴', '┘')}{C.RESET}")

# ── Spinner ─────────────────────────────────────────────────────────────────
class Spinner:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    def __init__(self, msg, color=C.CYAN):
        self._msg = msg
        self._color = color
        self._stop = threading.Event()
        self._t = None
    def __enter__(self):
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self
    def __exit__(self, *args):
        self._stop.set()
        if self._t:
            self._t.join(timeout=2)
        sys.stdout.write("\r\x1b[K")
        sys.stdout.flush()
    def _run(self):
        i = 0
        while not self._stop.is_set():
            f = self.FRAMES[i % len(self.FRAMES)]
            sys.stdout.write(f"\r  {self._color}{f} {self._msg}...{C.RESET}")
            sys.stdout.flush()
            i += 1
            time.sleep(0.1)

# ── Clipboard (via Win32 API — no dependencies) ─────────────────────────────
def copy_clipboard(text):
    try:
        CF_UNICODETEXT = 13
        GMEM_MOVEABLE = 0x0002
        k32 = ctypes.windll.kernel32
        u32 = ctypes.windll.user32
        data = (text + "\0").encode("utf-16-le")
        u32.OpenClipboard(0)
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        ptr = k32.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        k32.GlobalUnlock(h)
        u32.SetClipboardData(CF_UNICODETEXT, h)
        u32.CloseClipboard()
        return True
    except Exception:
        return False

# ── Storage: backup of originals + spoof history ────────────────────────────
# EXE mode: portable — the app creates its own data folder NEXT TO the exe and
# needs nothing else (no .py, no images). Script mode keeps the classic APPDATA
# location so existing backups keep working.
_FROZEN = getattr(sys, "frozen", False)
_APPDATA_DIR = Path(os.environ.get("APPDATA", "."))

if _FROZEN:
    APP_DIR = Path(sys.executable).resolve().parent / "MACSpooferData"
else:
    APP_DIR = _APPDATA_DIR

_writable = False
try:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    _writable = os.access(APP_DIR, os.W_OK)
except Exception:
    pass

# If the exe sits in a read-only location, fall back to APPDATA so data still saves
if _FROZEN and not _writable:
    APP_DIR = _APPDATA_DIR

# One-time migration: bring any data saved by the script version into the EXE folder
if _FROZEN and _writable and APP_DIR != _APPDATA_DIR:
    for _name in ("mac_spoofer_backup.json", "mac_spoofer_history.json",
                  "mac_spoofer_config.json", "mac_spoofer.log"):
        _src = _APPDATA_DIR / _name
        _dst = APP_DIR / _name
        if _src.exists() and not _dst.exists():
            try:
                _dst.write_bytes(_src.read_bytes())
            except Exception:
                pass

BACKUP_FILE = APP_DIR / "mac_spoofer_backup.json"
HISTORY_FILE = APP_DIR / "mac_spoofer_history.json"
HWID_BACKUP_FILE = APP_DIR / "mac_spoofer_hwid_backup.json"

# Friendly note inside the data folder (EXE mode only)
if _FROZEN:
    _info = APP_DIR / "LEEME.txt"
    if not _info.exists():
        try:
            _info.write_text(
                "MACSpooferData — carpeta de datos de MAC Spoofer (creada por el EXE).\n"
                "----------------------------------------------------------------------\n"
                "mac_spoofer_backup.json   -> MACs originales (para restaurar)\n"
                "mac_spoofer_history.json  -> historial de spoofs\n"
                "mac_spoofer_config.json   -> tu tema de color\n"
                "mac_spoofer_hwid_backup.json -> MachineGuid / serial originales\n"
                "mac_spoofer.log           -> registro de actividades\n\n"
                "No borres estos archivos mientras tengas MACs que restaurar.\n",
                encoding="utf-8")
        except Exception:
            pass

def load_json(path, default):
    try:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def load_backup():
    return load_json(BACKUP_FILE, {})

def save_backup(data):
    save_json(BACKUP_FILE, data)

def load_history():
    return load_json(HISTORY_FILE, [])

def save_history(data):
    save_json(HISTORY_FILE, data)

def add_history(adapter, mac):
    hist = load_history()
    hist.insert(0, {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "adapter": adapter,
        "mac": mac,
        "vendor": vendor_of(mac),
    })
    save_history(hist[:20])

# ── Config, theme & activity log ────────────────────────────────────────────
CONFIG_FILE = APP_DIR / "mac_spoofer_config.json"
LOG_FILE = APP_DIR / "mac_spoofer.log"
THEMES = {
    "1": ("Cyan (default)", C.CYAN),
    "2": ("Green", C.GREEN),
    "3": ("Magenta", C.MAGENTA),
    "4": ("Blue", C.BLUE),
    "5": ("Yellow", C.YELLOW),
    "6": ("Red", C.RED),
    "7": ("Bright Cyan", C.B_CYAN),
    "8": ("Bright Green", C.B_GREEN),
}
VPN_KEYWORDS = ("tap", "tun", "vpn", "wireguard", "nordvpn", "expressvpn",
                "surfshark", "openvpn", "proton", "windscribe", "tunnel")

# Privacy mode: sensitive values (IPs, MACs, PC name...) render as #### by
# default. Press P in the menu to reveal them (toggle) — great for demos,
# screenshots or when sharing your screen.
PRIVACY_MODE = True

_PLACEHOLDERS = {"n/a", "-", "unavailable", "unknown", "error", "no response", "?"}

def mask_val(s):
    """Replace every visible letter/digit with '#', keep separators like
    ':' '.' '-' so the length/shape stays readable (9839 -> ####).
    Placeholder tokens (N/A, unavailable...) pass through untouched."""
    if not s:
        return s
    if str(s).strip().lower() in _PLACEHOLDERS:
        return s
    return re.sub(r"[0-9A-Za-z]", "#", str(s))

def pv(s):
    """Privacy view — returns the masked value while privacy mode is ON."""
    if not PRIVACY_MODE:
        return s
    return mask_val(s)

def toggle_privacy():
    global PRIVACY_MODE
    PRIVACY_MODE = not PRIVACY_MODE
    save_config()
    if PRIVACY_MODE:
        print(f"\n  {C.YELLOW}🔒 Privacy ON — sensitive data hidden as ####{C.RESET}")
    else:
        print(f"\n  {C.RED}👁 Privacy OFF — sensitive data revealed (careful if sharing the screen){C.RESET}")

def load_config():
    global ACCENT, PRIVACY_MODE
    cfg = load_json(CONFIG_FILE, {})
    t = cfg.get("theme")
    if t and t.startswith("\x1b["):
        ACCENT = t
    PRIVACY_MODE = bool(cfg.get("privacy", True))

def save_config():
    save_json(CONFIG_FILE, {"theme": ACCENT, "privacy": PRIVACY_MODE})

def log_action(action, adapter, mac, result):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {action} | {adapter} | {mac} | {result}\n")
    except Exception:
        pass

def detect_vpn(adapters):
    for a in adapters:
        desc = (a.get("InterfaceDescription") or "").lower()
        if any(k in desc for k in VPN_KEYWORDS):
            return True
    return False

# ── Admin helpers ───────────────────────────────────────────────────────────
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def run_as_admin():
    """Re-launch the script (or the frozen EXE) elevated via UAC."""
    try:
        if getattr(sys, "frozen", False):
            # PyInstaller EXE: sys.executable IS the program, and __file__
            # would point to a temp extraction dir that no longer exists.
            target, args = sys.executable, ""
        else:
            target, args = sys.executable, f'"{os.path.abspath(__file__)}"'
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", target, args, None, 1)
        sys.exit(0)
    except Exception:
        cprint("  ✗ Could not get admin privileges. Run as Administrator manually.", C.B_RED)
        sys.exit(1)

# ── PowerShell runner ───────────────────────────────────────────────────────
def run_ps(script, timeout=25):
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return None

def ps_sq(s):
    """PowerShell-safe single-quoted literal (embedded quotes are doubled)."""
    return "'" + s.replace("'", "''") + "'"

# ── MAC address utilities ───────────────────────────────────────────────────
def is_valid_mac(mac_str):
    return bool(re.match(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$", mac_str))

def normalize_mac(mac_str):
    raw = re.sub(r"[^0-9A-Fa-f]", "", mac_str)
    if len(raw) == 12:
        return ":".join(raw[i:i+2] for i in range(0, 12, 2)).upper()
    return mac_str.replace("-", ":").upper()

def generate_random_mac(vendor_specific=False):
    """Random MAC with the Locally Administered (LAA) bit always set so every
    driver accepts it (WiFiCx, NDIS, Qualcomm, Intel...)."""
    if vendor_specific:
        suffixes = [
            [0x1A, 0x2B], [0x50, 0x56], [0x0C, 0x29], [0x15, 0x5D],
            [0x1E, 0x67], [0x1B, 0x21], [0x24, 0xD7], [0x26, 0xB9],
            [0x1F, 0x3A], [0xE0, 0x4C], [0x23, 0x54], [0x0E, 0x8E],
            [0xA0, 0xC6], [0x13, 0x02], [0x25, 0x22],
        ]
        mac = [random.choice([0x02, 0x06, 0x0A, 0x0E])] + random.choice(suffixes) \
              + [random.randint(0, 255) for _ in range(3)]
    else:
        mac = [random.randint(0, 255) for _ in range(6)]
        mac[0] = (mac[0] | 0x02) & 0xFE
    return ":".join(f"{b:02X}" for b in mac)

# Best-effort OUI → vendor lookup (only the most common, well-known prefixes)
VENDOR_OUI = {
    "00000C": "Cisco", "001B0C": "Cisco", "000FF7": "Cisco",
    "000C29": "VMware", "005056": "VMware", "000569": "VMware",
    "00155D": "Microsoft (Hyper-V)", "0003FF": "Microsoft", "281878": "Microsoft",
    "001B21": "Intel", "3C970E": "Intel", "A434D9": "Intel",
    "5CE0C5": "Intel", "00216A": "Intel", "8CEC4B": "Intel", "0016EA": "Intel",
    "00E04C": "Realtek", "74DA38": "Realtek", "001F3A": "Realtek", "B46D83": "Realtek",
    "000AF0": "Qualcomm", "9C3DCF": "Qualcomm", "E4029B": "Qualcomm",
    "00037F": "Qualcomm Atheros",
    "001018": "Broadcom", "001F8B": "Broadcom",
    "000393": "Apple", "3C22FB": "Apple", "A483E7": "Apple", "F01898": "Apple",
    "001599": "Samsung", "5C0A5B": "Samsung", "083E8E": "Samsung",
    "00259E": "Huawei",
    "001B11": "D-Link", "28107B": "D-Link",
    "24A43C": "Ubiquiti", "44D9E7": "Ubiquiti", "802AA8": "Ubiquiti",
    "50C7BF": "TP-Link", "98DAC4": "TP-Link", "001D0F": "TP-Link",
    "000FB5": "Netgear", "204E7F": "Netgear", "A040A0": "Netgear",
    "6045CB": "ASUS", "049226": "ASUS", "ACCF85": "ASUS",
    "001422": "Dell", "3417EB": "Dell", "001EC9": "Dell",
    "3C7D0A": "Lenovo",
    "B827EB": "Raspberry Pi", "DCA632": "Raspberry Pi", "E45F01": "Raspberry Pi",
    "240AC4": "Espressif (ESP)", "30AEA4": "Espressif (ESP)", "246F28": "Espressif (ESP)",
    "74C246": "Amazon", "6837E9": "Amazon",
    "F4F5D8": "Google", "A47733": "Google",
    "005043": "Marvell", "0026BD": "Sony", "000F9F": "LG",
}

# 2-byte prefixes used by generate_random_mac(vendor_specific=True) → "X-like" labels
SPOOF_SUFFIX_VENDOR = {
    "1A2B": "Cisco", "5056": "VMware", "0C29": "VMware", "155D": "Microsoft",
    "1E67": "Intel", "1B21": "Intel", "24D7": "Intel", "26B9": "Netgear",
    "1F3A": "Realtek", "E04C": "Realtek", "2354": "Qualcomm", "0E8E": "Qualcomm",
    "A0C6": "Qualcomm", "1302": "Broadcom", "2522": "TP-Link",
}

def vendor_of(mac):
    key = normalize_mac(mac).replace(":", "")
    if len(key) >= 6 and key[:6] in VENDOR_OUI:
        return VENDOR_OUI[key[:6]]
    if len(key) >= 6 and key[2:6] in SPOOF_SUFFIX_VENDOR:
        return f"{SPOOF_SUFFIX_VENDOR[key[2:6]]}-like"
    return "Unknown / Generic"

def is_laa(mac):
    """True if the MAC is locally administered (bit 1 of first byte set)."""
    try:
        return bool(int(mac.replace(":", "")[:2], 16) & 0x02)
    except Exception:
        return False

def mac_color(mac, reveal=False):
    """First 3 pairs cyan, last 3 yellow — easier to read.
    In privacy mode MACs render as ##:##:##:##:##:## so demos/screenshots
    never leak real addresses; pass reveal=True for freshly generated MACs
    (random candidates are not personal data)."""
    if PRIVACY_MODE and not reveal:
        mac = mask_val(mac)
    parts = mac.split(":")
    if len(parts) != 6:
        return mac
    return f"{C.CYAN}{':'.join(parts[:3])}{C.DIM}:{C.RESET}{C.YELLOW}{':'.join(parts[3:])}{C.RESET}"

def mac_disp(mac):
    """Normalize (Windows may report dash format) and colorize a MAC for display."""
    if not mac or mac in ("N/A", "-", ""):
        return mac or "N/A"
    n = normalize_mac(mac)
    return mac_color(n) if is_valid_mac(n) else mac

def mac_badge(mac):
    """Badges shown next to a MAC: vendor + LAA flag."""
    v = vendor_of(mac)
    flag = "LAA" if is_laa(mac) else "UAA"
    return f"{C.DIM}· {v} · {flag}{C.RESET}"

# ── Network operations ──────────────────────────────────────────────────────
def get_network_adapters():
    script = (
        "Get-NetAdapter | Select-Object Name, InterfaceDescription, "
        "MacAddress, Status, ifIndex | ConvertTo-Json -Compress"
    )
    r = run_ps(script)
    if r and r.returncode == 0 and r.stdout.strip():
        try:
            data = json.loads(r.stdout.strip())
            return data if isinstance(data, list) else [data]
        except Exception:
            pass
    # Fallback: netsh
    try:
        res = subprocess.run(
            ["netsh", "interface", "show", "interface"],
            capture_output=True, text=True, timeout=10)
        adapters = []
        for line in res.stdout.split("\n")[3:]:
            parts = line.split()
            if len(parts) >= 4:
                adapters.append({
                    "Name": " ".join(parts[3:]),
                    "Status": parts[1],
                    "MacAddress": "N/A",
                    "InterfaceDescription": "N/A",
                })
        return adapters
    except Exception:
        return []

def get_ip_info():
    script = (
        'Get-NetIPConfiguration | Where-Object { $_.NetAdapter.Status -eq "Up" } | '
        "ForEach-Object { [PSCustomObject]@{ "
        "InterfaceAlias = $_.NetAdapter.InterfaceAlias; "
        "IPv4Address = $_.IPv4Address.IPAddress; "
        "IPv4Gateway = $_.IPv4DefaultGateway.NextHop; "
        "DNSServer = ($_.DNSServer | Where-Object { $_.AddressFamily -eq 2 } | "
        "Select-Object -ExpandProperty ServerAddresses) -join \", \"; "
        "MacAddress = $_.NetAdapter.MacAddress } } | ConvertTo-Json -Compress"
    )
    r = run_ps(script, timeout=25)
    if r and r.returncode == 0 and r.stdout.strip():
        try:
            data = json.loads(r.stdout.strip())
            return data if isinstance(data, list) else [data]
        except Exception:
            pass
    return []

def get_public_ip():
    for url in ("https://api.ipify.org?format=json", "https://ifconfig.me/ip"):
        r = run_ps(
            f'(Invoke-RestMethod -Uri "{url}" -TimeoutSec 5).ToString().Trim()', timeout=12)
        if r and r.returncode == 0 and r.stdout.strip() and "error" not in r.stdout.lower():
            return r.stdout.strip()
    return "unavailable"

# Drivers known to ignore or silently reject the NetworkAddress registry value.
# Some just need a specific format; others need EEPROM writes (not possible
# from userspace). The spoof may appear to work but reverts on reboot.
_STUBBORN_DRIVERS = (
    "realtek",    # PCIe GbE Family, USB FE, 8821/8822 WiFi
    "broadcom",   # NetXtreme, some 802.11ac wireless
    "mediatek",   # MT7921, MT7922 WiFi
    "marvell",    # Yukon, Libertas
    "killer",     # Killer E2200/E2400/E2500 (often rebranded Atheros)
)

def detect_stubborn_driver(adapter_name):
    """Check if the adapter uses a driver known to ignore MAC address changes.
    Some chipsets silently reject the NetworkAddress registry value —
    the MAC appears to change but reverts on reboot or never applies at all.
    Returns a warning string or None if the driver looks cooperative."""
    try:
        r = run_ps(
            f'(Get-NetAdapter -Name {ps_sq(adapter_name)} '
            f'-ErrorAction SilentlyContinue).InterfaceDescription',
            timeout=10)
        if r and r.returncode == 0 and r.stdout.strip():
            desc = r.stdout.strip().lower()
            for kw in _STUBBORN_DRIVERS:
                if kw in desc:
                    # Capitalize first letter for the message
                    brand = kw[0].upper() + kw[1:]
                    return (
                        f"{brand} driver detected — some {brand} chipsets "
                        "reject NetworkAddress changes; the spoof may revert "
                        "on reboot. If it fails, try a USB-to-Ethernet dongle instead."
                    )
    except Exception:
        pass
    return None

def warn_stubborn_driver(adapter_name):
    """Check for Realtek/stubborn drivers and ask the user whether to proceed.
    Returns True if we should continue, False if the user wants to abort."""
    msg = detect_stubborn_driver(adapter_name)
    if not msg:
        return True  # no warning, continue
    print(f"\n  {C.YELLOW}⚠ {msg}{C.RESET}")
    if not ask_yes_no("Continue anyway? (spoof may silently fail)", False):
        cprint("  Cancelled.", C.DIM)
        return False
    return True

def spoof_mac(adapter_name, new_mac):
    """Apply a MAC override. Method 1: Set-NetAdapterAdvancedProperty.
    Method 2: direct registry write via DriverDesc match.
    Returns (success: bool, message: str)."""
    mac_no_sep = new_mac.replace(":", "").replace("-", "")

    script = (
        f'Try {{ Set-NetAdapterAdvancedProperty -Name {ps_sq(adapter_name)} '
        f'-RegistryKeyword "NetworkAddress" -RegistryValue "{mac_no_sep}" -ErrorAction Stop; '
        'Write-Output "OK" }} Catch { Write-Output "FAIL" }'
    )
    r = run_ps(script, timeout=20)
    if r and "OK" in r.stdout:
        restart_adapter(adapter_name)
        return True, "Applied via Set-NetAdapterAdvancedProperty"

    script = (
        f'$a = Get-NetAdapter -Name {ps_sq(adapter_name)} -ErrorAction SilentlyContinue; '
        'if (-not $a) { Write-Output "NOT_FOUND"; exit 0 }; '
        '$desc = $a.InterfaceDescription; '
        '$base = "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4D36E972-E325-11CE-BFC1-08002BE10318}"; '
        '$found = $false; '
        'Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object { '
        '$d = (Get-ItemProperty $_.PSPath -Name "DriverDesc" -ErrorAction SilentlyContinue).DriverDesc; '
        'if ($d -eq $desc) { '
        f'Set-ItemProperty -Path $_.PSPath -Name "NetworkAddress" -Value "{mac_no_sep}" -Type String; '
        '$found = $true } }; '
        'if ($found) { Write-Output "REG_OK" } else { Write-Output "NOT_FOUND" }'
    )
    r = run_ps(script, timeout=20)
    if r and "REG_OK" in r.stdout:
        restart_adapter(adapter_name)
        return True, "Applied via direct registry write"
    return False, (r.stderr.strip()[:120] if r and r.stderr.strip() else "adapter not found in registry")

def remove_spoof(adapter_name):
    script = (
        f'Try {{ Reset-NetAdapterAdvancedProperty -Name {ps_sq(adapter_name)} '
        '-RegistryKeyword "NetworkAddress" -ErrorAction Stop; '
        'Write-Output "RESET_OK" }} Catch { Write-Output "RESET_FAIL" }'
    )
    r = run_ps(script, timeout=20)
    if r and "RESET_OK" in r.stdout:
        restart_adapter(adapter_name)
        return True, "Spoof removed via Reset-NetAdapterAdvancedProperty"

    script = (
        f'$a = Get-NetAdapter -Name {ps_sq(adapter_name)} -ErrorAction SilentlyContinue; '
        'if (-not $a) { Write-Output "NOT_FOUND"; exit 0 }; '
        '$desc = $a.InterfaceDescription; '
        '$base = "HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Class\\{4D36E972-E325-11CE-BFC1-08002BE10318}"; '
        '$found = $false; '
        'Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object { '
        '$d = (Get-ItemProperty $_.PSPath -Name "DriverDesc" -ErrorAction SilentlyContinue).DriverDesc; '
        'if ($d -eq $desc) { '
        '$v = Get-ItemProperty $_.PSPath -Name "NetworkAddress" -ErrorAction SilentlyContinue; '
        'if ($v) { Remove-ItemProperty -Path $_.PSPath -Name "NetworkAddress"; $found = $true } } }; '
        'if ($found) { Write-Output "REMOVED" } else { Write-Output "NO_SPOOF" }'
    )
    r = run_ps(script, timeout=20)
    if r and "REMOVED" in r.stdout:
        restart_adapter(adapter_name)
        return True, "Spoof removed via registry cleanup"
    return False, "No spoof found to remove"

def restart_adapter(adapter_name):
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f'Disable-NetAdapter -Name {ps_sq(adapter_name)} -Confirm:$false'],
            capture_output=True, text=True, timeout=20)
        time.sleep(1)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             f'Enable-NetAdapter -Name {ps_sq(adapter_name)} -Confirm:$false'],
            capture_output=True, text=True, timeout=20)
        time.sleep(2)
        return r.returncode == 0
    except Exception:
        return False

def flush_dns():
    try:
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=15)
        return True
    except Exception:
        return False

def release_renew_ip():
    """Release & renew the IP address with exponential backoff retry.
    ipconfig /renew can fail on busy networks or when the DHCP server is
    slow; retry up to 3 times with progressive waits: 2 s, 4 s, 8 s."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            subprocess.run(["ipconfig", "/release"], capture_output=True, timeout=20)
            time.sleep(1)
            r = subprocess.run(["ipconfig", "/renew"], capture_output=True, timeout=40)
            out = (r.stdout + r.stderr).lower()
            if r.returncode == 0 and "unable" not in out and "error" not in out:
                return True
        except Exception:
            pass
        if attempt < max_retries - 1:
            wait = 2 ** (attempt + 1)  # 2, 4, 8 seconds
            time.sleep(wait)
    return False

# ── Roblox session/cache cleanup ────────────────────────────────────────────
ROBLOX_LOCAL_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "Roblox"
ROBLOX_PROGDATA_DIR = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Roblox"
ROBLOX_PROCS = ("RobloxPlayerBeta.exe", "RobloxStudioBeta.exe",
                "RobloxCrashHandler.exe")

def clear_roblox_registry():
    r"""Remove Roblox traces from HKCU\Software\Roblox (some versions leave
    identifiers here that survive a folder wipe)."""
    try:
        r = run_ps(
            'Remove-Item -Path "HKCU:\\Software\\Roblox" -Recurse -Force '
            '-ErrorAction SilentlyContinue; Write-Output "OK"', timeout=10)
        return r and "OK" in (r.stdout or "")
    except Exception:
        return False

def clear_roblox_data():
    r"""Stop Roblox and delete EVERYTHING under %LOCALAPPDATA%\Roblox AND
    %PROGRAMDATA%\Roblox except the installed app itself (Versions folder).
    Also nukes HKCU\Software\Roblox from the registry.
    No reinstall needed. Returns True if anything was actually removed."""
    cleared = False
    if not ROBLOX_LOCAL_DIR.is_dir() and not ROBLOX_PROGDATA_DIR.is_dir():
        return False  # Roblox not installed — never touch other folders
    for proc in ROBLOX_PROCS:
        try:
            subprocess.run(["taskkill", "/f", "/im", proc],
                           capture_output=True, timeout=10)
        except Exception:
            pass
    time.sleep(1)
    # %LOCALAPPDATA%\Roblox
    if ROBLOX_LOCAL_DIR.is_dir():
        try:
            for child in list(ROBLOX_LOCAL_DIR.iterdir()):
                if child.name.lower() == "versions":
                    continue  # keep the installed app — no reinstall needed
                try:
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        child.unlink(missing_ok=True)
                    if not child.exists():
                        cleared = True
                except Exception:
                    pass
        except Exception:
            pass
    # %PROGRAMDATA%\Roblox (some versions stash logs/configs here)
    try:
        if ROBLOX_PROGDATA_DIR.is_dir():
            for child in list(ROBLOX_PROGDATA_DIR.iterdir()):
                try:
                    if child.is_dir():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        child.unlink(missing_ok=True)
                    if not child.exists():
                        cleared = True
                except Exception:
                    pass
    except Exception:
        pass
    # HKCU\Software\Roblox registry key
    if clear_roblox_registry():
        cleared = True
    return cleared

def open_browser_cookie_settings():
    """Open the browser's per-site data page (Edge/Chrome) so the user can
    delete roblox.com cookies in a couple of clicks. Returns True if a
    browser was launched."""
    candidates = [
        ("msedge", "edge://settings/content/siteData"),
        ("chrome", "chrome://settings/content/siteData"),
        (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
         "edge://settings/content/siteData"),
        (r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
         "edge://settings/content/siteData"),
        (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
         "chrome://settings/content/siteData"),
        (r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
         "chrome://settings/content/siteData"),
    ]
    for exe, page in candidates:
        try:
            subprocess.Popen([exe, "--new-window", page],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except Exception:
            continue
    return False

def roblox_cleanup_step():
    r"""Step used by Full Privacy Reset / New Account Prep: close Roblox and
    wipe EVERYTHING under %LOCALAPPDATA%\Roblox AND %PROGRAMDATA%\Roblox except
    the installed app (Versions folder), plus HKCU\Software\Roblox in the
    registry. This kills the Roblox DeviceID, sessions and caches without
    forcing a reinstall."""
    if not ask_yes_no("Wipe Roblox data & DeviceID? (closes Roblox, keeps app)", True):
        print(f"  {C.DIM}    Skipped — wipe %LOCALAPPDATA%\\Roblox and HKCU\\Software\\Roblox manually.{C.RESET}")
        return False
    with Spinner("Wiping Roblox data (keeping app version)"):
        cleared = clear_roblox_data()
    if cleared:
        print(f"  {C.GREEN}    ✓ Roblox wiped — DeviceID & sessions gone (app still installed){C.RESET}")
    else:
        print(f"  {C.YELLOW}    ⚠ Nothing to clear (Roblox not installed or already clean){C.RESET}")
    return cleared

# ── System identity & HWID tools (MachineGuid, volume serial, cookies) ─────
# The Windows identity core. Changing these makes tracking services (Roblox,
# etc.) see a brand-new PC. Originals are backed up so everything is reversible.
GUID_RE = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
CRYPTO_KEY = r"HKLM:\SOFTWARE\Microsoft\Cryptography"

def load_hwid_backup():
    return load_json(HWID_BACKUP_FILE, {})

def save_hwid_backup(data):
    save_json(HWID_BACKUP_FILE, data)

def get_machine_guid():
    """Read the MachineGuid (Windows identity heart). Roblox reads it to
    fingerprint the PC — changing it makes the OS look brand new."""
    r = run_ps(f'(Get-ItemProperty -Path {ps_sq(CRYPTO_KEY)} -Name MachineGuid '
               f'-ErrorAction SilentlyContinue).MachineGuid', timeout=15)
    if r and r.returncode == 0 and r.stdout.strip():
        v = r.stdout.strip().splitlines()[-1].strip()
        return v if GUID_RE.match(v) else None
    return None

def apply_machine_guid(new_guid, original=None):
    """Write a new MachineGuid. If original is given, back it up first so it
    can be restored later. After writing, reads it back to verify the change
    actually took effect. If the PowerShell method fails verification, falls
    back to reg.exe add as a second attempt."""
    if original:
        hw = load_hwid_backup()
        hw["MachineGuid"] = original
        save_hwid_backup(hw)

    # Method 1: PowerShell Set-ItemProperty
    r = run_ps(f'Set-ItemProperty -Path {ps_sq(CRYPTO_KEY)} -Name MachineGuid '
               f'-Value {ps_sq(new_guid)}; Write-Output "OK"', timeout=15)
    if r and "OK" in (r.stdout or ""):
        time.sleep(0.3)  # let the registry flush before reading back
        written = get_machine_guid()
        if written and written.upper() == new_guid.upper():
            log_action("MACHINE_GUID", CRYPTO_KEY, pv(new_guid), "ok")
            return True, "verified (PowerShell)"

    # Method 2: reg.exe add (fallback — sometimes more reliable with UAC)
    try:
        key = r"HKLM\SOFTWARE\Microsoft\Cryptography"
        rr = subprocess.run(
            ["reg", "add", key, "/v", "MachineGuid", "/t", "REG_SZ",
             "/d", new_guid, "/f"],
            capture_output=True, text=True, timeout=15)
        if rr.returncode == 0:
            written = get_machine_guid()
            if written and written.upper() == new_guid.upper():
                log_action("MACHINE_GUID", CRYPTO_KEY, pv(new_guid), "ok")
                return True, "verified (reg.exe fallback)"
            return False, (
                f"reg.exe wrote OK but read-back mismatch "
                f"(got {written or 'None'}, expected {new_guid})"
            )
        return False, rr.stderr.strip()[:120] or "reg.exe failed"
    except Exception as e:
        return False, f"both methods failed: {e}"[:120]

def machine_guid_step():
    """Interactive step: change (or restore) the MachineGuid."""
    print(f"  {C.DIM}    MachineGuid is the 'heart' of your Windows identity — services{C.RESET}")
    print(f"    {C.DIM}like Roblox read it to detect a 'new PC'. Original is backed up.{C.RESET}")
    hw = load_hwid_backup()
    current = get_machine_guid()
    if not current:
        print(f"  {C.YELLOW}    ⚠ Could not read the MachineGuid — skipped.{C.RESET}")
        return False
    print(f"    {C.DIM}Current: {pv(current)}{C.RESET}")
    if "MachineGuid" in hw:
        if not ask_yes_no("Restore the original MachineGuid from backup?", False):
            print(f"  {C.DIM}    Skipped.{C.RESET}")
            return False
        with Spinner("Restoring MachineGuid"):
            ok, msg = apply_machine_guid(hw["MachineGuid"])
        if ok:
            del hw["MachineGuid"]
            save_hwid_backup(hw)
            print(f"  {C.GREEN}    ✓ MachineGuid restored to the original{C.RESET}")
        else:
            print(f"  {C.RED}    ✗ Restore failed: {msg}{C.RESET}")
        return ok
    print(f"  {C.YELLOW}    ⚠ MachineGuid is tied to some software/DRM licenses (Windows,{C.RESET}")
    print(f"  {C.YELLOW}    Office...). Backup is saved, so it's fully reversible.{C.RESET}")
    if not ask_yes_no("Generate a NEW random MachineGuid?", True):
        print(f"  {C.DIM}    Skipped.{C.RESET}")
        return False
    new_guid = str(uuid.uuid4()).upper()
    with Spinner("Writing new MachineGuid"):
        ok, msg = apply_machine_guid(new_guid, original=current)
    if ok:
        print(f"  {C.GREEN}    ✓ New MachineGuid: {C.BOLD}{pv(new_guid)}{C.RESET}")
        print(f"    {C.DIM}Original saved. Some apps may need a reboot to see the change.{C.RESET}")
    else:
        print(f"  {C.RED}    ✗ Failed: {msg}{C.RESET}")
    return ok

# ── Hostname (GetComputerNameExW — Byfron reads this) ──────────────────────
def get_hostname():
    """Read the current computer name (hostname). Byfron/Roblox anti-cheat
    calls GetComputerNameExW and GetComputerNameA to fingerprint the PC."""
    return os.environ.get("COMPUTERNAME", "") or platform.node() or "?"

def apply_hostname(new_name, original=None):
    """Rename the computer via PowerShell Rename-Computer.
    The change only takes full effect after a reboot."""
    if original:
        hw = load_hwid_backup()
        hw["Hostname"] = original
        save_hwid_backup(hw)
    r = run_ps(
        f'Rename-Computer -NewName {ps_sq(new_name)} -Force '
        f'-ErrorAction Stop; Write-Output "OK"', timeout=20)
    if r and r.returncode == 0 and "OK" in (r.stdout or ""):
        log_action("HOSTNAME", "COMPUTERNAME", pv(new_name), "ok")
        return True, "ok"
    return False, (r.stderr.strip()[:120] if r and r.stderr.strip()
                    else "Rename-Computer failed")

def hostname_step():
    """Interactive step: change (or restore) the computer hostname."""
    print(f"  {C.DIM}    Byfron (Roblox anti-cheat) calls GetComputerNameExW — a{C.RESET}")
    print(f"    {C.DIM}stale hostname correlates old & new identities. Original{C.RESET}")
    print(f"    {C.DIM}is backed up — fully reversible after reboot.{C.RESET}")
    hw = load_hwid_backup()
    current = get_hostname()
    print(f"    {C.DIM}Current: {pv(current)}{C.RESET}")
    if "Hostname" in hw:
        if not ask_yes_no("Restore the original hostname from backup?", False):
            print(f"  {C.DIM}    Skipped.{C.RESET}")
            return False
        with Spinner("Restoring hostname"):
            ok, msg = apply_hostname(hw["Hostname"])
        if ok:
            del hw["Hostname"]
            save_hwid_backup(hw)
            print(f"  {C.GREEN}    ✓ Hostname restored{C.RESET}")
        else:
            print(f"  {C.RED}    ✗ Restore failed: {msg}{C.RESET}")
        return ok
    print(f"  {C.YELLOW}    ⚠ Reboot required for the new name to take full effect.{C.RESET}")
    if not ask_yes_no("Generate a NEW random hostname?", True):
        print(f"  {C.DIM}    Skipped.{C.RESET}")
        return False
    suffix = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=7))
    new_name = f"DESKTOP-{suffix}"
    with Spinner("Renaming computer"):
        ok, msg = apply_hostname(new_name, original=current)
    if ok:
        # Also update the in-process env var so the banner reflects the change
        os.environ["COMPUTERNAME"] = new_name
        print(f"  {C.GREEN}    ✓ New hostname: {C.BOLD}{pv(new_name)}{C.RESET}")
        print(f"    {C.DIM}Original saved. Reboot to fully apply.{C.RESET}")
    else:
        print(f"  {C.RED}    ✗ Failed: {msg}{C.RESET}")
    return ok

def get_volume_serial(drive="C"):
    """Read the drive's volume serial (the disk HWID Roblox fingerprints)."""
    r = run_ps(f'(Get-CimInstance Win32_LogicalDisk -Filter "DeviceID=\'{drive}:\'").VolumeSerialNumber',
               timeout=15)
    if r and r.returncode == 0 and r.stdout.strip():
        v = r.stdout.strip().splitlines()[-1].strip().upper()
        if len(v) == 8 and all(c in "0123456789ABCDEF" for c in v):
            return f"{v[:4]}-{v[4:]}"
    return None

def find_volumeid_exe():
    """Locate volumeid64.exe (Sysinternals) next to the app or in APP_DIR."""
    dirs = [APP_DIR]
    if _FROZEN:
        dirs.append(Path(sys.executable).resolve().parent)
    dirs.append(Path.cwd())
    for d in dirs:
        exe = d / "volumeid64.exe"
        if exe.is_file():
            return exe
    return None

def download_volumeid():
    """Download & extract Sysinternals VolumeId into APP_DIR. Returns the exe."""
    zip_path = APP_DIR / "VolumeId.zip"
    script = (
        "$ProgressPreference='SilentlyContinue'; "
        "Invoke-WebRequest -Uri 'https://download.sysinternals.com/files/VolumeId.zip' "
        f"-OutFile {ps_sq(str(zip_path))} -UseBasicParsing; "
        f"Expand-Archive -Path {ps_sq(str(zip_path))} -DestinationPath {ps_sq(str(APP_DIR))} -Force; "
        "Write-Output 'OK'"
    )
    r = run_ps(script, timeout=120)
    exe = APP_DIR / "volumeid64.exe"
    return exe if exe.is_file() else None

def ensure_volumeid():
    """Return a working volumeid64.exe, downloading it from Sysinternals if needed."""
    exe = find_volumeid_exe()
    if exe:
        return exe
    print(f"  {C.YELLOW}    ⚠ volumeid64.exe (Sysinternals) not found — downloading...{C.RESET}")
    with Spinner("Downloading VolumeId from Sysinternals"):
        return download_volumeid()

def apply_volume_serial(exe, serial_hex8, original=None):
    """Change the C: volume serial with volumeid64.exe — no formatting needed.
    The change is written to the boot sector; Windows reports it after reboot."""
    if original:
        hw = load_hwid_backup()
        hw["VolumeSerial"] = original.replace("-", "")
        save_hwid_backup(hw)
    # volumeid64.exe expects XXXX-XXXX format (with dash)
    raw = serial_hex8.replace("-", "")
    formatted = f"{raw[:4]}-{raw[4:]}"
    try:
        r = subprocess.run([str(exe), "-accepteula", "C:", formatted],
                           capture_output=True, text=True, timeout=60)
        out = (r.stdout + r.stderr).strip()
        if r.returncode == 0:
            log_action("VOLUME_SERIAL", "C:", pv(formatted), "ok")
            return True, out[-140:] or "ok"
        return False, out[-140:] or "volumeid failed"
    except Exception as e:
        return False, str(e)[:120]

def volume_serial_step():
    """Interactive step: change (or restore) the C: volume serial."""
    print(f"  {C.DIM}    Volume serial = the disk HWID read by GetVolumeInformationA{C.RESET}")
    print(f"    {C.DIM}(Roblox fingerprints it). Changed with Sysinternals VolumeId.{C.RESET}")
    hw = load_hwid_backup()
    current = get_volume_serial()
    if not current:
        print(f"  {C.YELLOW}    ⚠ Could not read the C: volume serial — skipped.{C.RESET}")
        return False
    print(f"    {C.DIM}Current: {pv(current)}{C.RESET}")
    if "VolumeSerial" in hw:
        if not ask_yes_no("Restore the original volume serial from backup?", False):
            print(f"  {C.DIM}    Skipped.{C.RESET}")
            return False
        exe = ensure_volumeid()
        if not exe:
            print(f"  {C.RED}    ✗ volumeid64.exe unavailable.{C.RESET}")
            return False
        with Spinner("Restoring volume serial"):
            ok, msg = apply_volume_serial(exe, hw["VolumeSerial"])
        if ok:
            del hw["VolumeSerial"]
            save_hwid_backup(hw)
            print(f"  {C.GREEN}    ✓ Volume serial restored{C.RESET}")
        else:
            print(f"  {C.RED}    ✗ Restore failed: {msg}{C.RESET}")
        return ok
    print(f"  {C.YELLOW}    ⚠ Changes the C: boot sector — reversible via backup, reboot needed.{C.RESET}")
    if not ask_yes_no("Generate a NEW random volume serial?", False):
        print(f"  {C.DIM}    Skipped.{C.RESET}")
        return False
    new_serial = f"{random.randint(0, 0xFFFFFFFF):08X}"
    exe = ensure_volumeid()
    if not exe:
        print(f"  {C.RED}    ✗ Could not get volumeid64.exe — download from:{C.RESET}")
        print(f"  {C.RED}      https://learn.microsoft.com/sysinternals/downloads/volumeid{C.RESET}")
        return False
    with Spinner("Changing volume serial"):
        ok, msg = apply_volume_serial(exe, new_serial, original=current)
    if ok:
        print(f"  {C.GREEN}    ✓ New volume serial: {C.BOLD}{pv(f'{new_serial[:4]}-{new_serial[4:]}')}{C.RESET}")
        print(f"  {C.YELLOW}    ⚠ Reboot required for Windows to report the new serial.{C.RESET}")
    else:
        print(f"  {C.RED}    ✗ Failed: {msg}{C.RESET}")
    return ok

BROWSER_PROCS = ("chrome.exe", "msedge.exe", "brave.exe", "vivaldi.exe", "opera.exe", "firefox.exe")

def find_browser_cookie_dbs():
    """Locate every browser cookie store on this PC (Chromium family + Firefox)."""
    la = Path(os.environ.get("LOCALAPPDATA", "."))
    ap = Path(os.environ.get("APPDATA", "."))
    roots = {
        "Chrome": la / "Google/Chrome/User Data",
        "Edge": la / "Microsoft/Edge/User Data",
        "Brave": la / "BraveSoftware/Brave-Browser/User Data",
        "Vivaldi": la / "Vivaldi/User Data",
        "Opera": ap / "Opera Software/Opera Stable",
        "Opera GX": ap / "Opera Software/Opera GX Stable",
    }
    dbs = []
    for browser, root in roots.items():
        try:
            for db in root.rglob("Cookies"):
                if db.is_file():
                    dbs.append((browser, db))
        except Exception:
            pass
    try:
        for db in (ap / "Mozilla/Firefox/Profiles").glob("*/cookies.sqlite"):
            if db.is_file():
                dbs.append(("Firefox", db))
    except Exception:
        pass
    return dbs

def kill_browsers():
    for p in BROWSER_PROCS:
        try:
            subprocess.run(["taskkill", "/f", "/im", p], capture_output=True, timeout=10)
        except Exception:
            pass

def purge_roblox_cookies():
    """Delete roblox.com cookies from every browser store found.
    Returns (stores_cleaned, total_deleted, stores_failed)."""
    cleaned, total, failed = [], 0, []
    for browser, db in find_browser_cookie_dbs():
        ok_store = False
        for attempt in range(3):
            try:
                con = sqlite3.connect(str(db), timeout=8)
                cur = con.cursor()
                if browser == "Firefox":
                    cur.execute("DELETE FROM moz_cookies WHERE host LIKE '%roblox.com'")
                else:
                    cur.execute("DELETE FROM cookies WHERE host_key LIKE '%roblox.com'")
                con.commit()
                n = cur.rowcount
                con.close()
                if n:
                    cleaned.append(f"{browser} · {db}")
                    total += n
                ok_store = True
                break
            except Exception:
                time.sleep(1)
        if not ok_store:
            failed.append(f"{browser} · {db}")
    return cleaned, total, failed

def browser_cookies_step():
    """Close every browser and delete roblox.com cookies (web logins live there)."""
    print(f"  {C.DIM}    Roblox web sessions live in browser cookies — they must go too.{C.RESET}")
    print(f"  {C.YELLOW}    ⚠ This closes ALL browsers (unsaved tabs are lost).{C.RESET}")
    if not ask_yes_no("Close browsers and delete roblox.com cookies?", True):
        print(f"  {C.DIM}    Skipped — delete them manually or use an incognito window.{C.RESET}")
        return False
    with Spinner("Closing browsers"):
        kill_browsers()
    time.sleep(1.5)
    with Spinner("Purging roblox.com cookies"):
        cleaned, total, failed = purge_roblox_cookies()
    if total:
        print(f"  {C.GREEN}    ✓ Deleted {total} roblox.com cookie(s) from {len(cleaned)} store(s){C.RESET}")
        for c in cleaned:
            print(f"      {C.DIM}{c}{C.RESET}")
    if failed:
        print(f"  {C.YELLOW}    ⚠ Could not open {len(failed)} store(s) (browser still locking them):{C.RESET}")
        for f in failed:
            print(f"      {C.DIM}{f}{C.RESET}")
        open_browser_cookie_settings()
    elif not total:
        print(f"  {C.YELLOW}    ⚠ No roblox.com cookies found in any browser store.{C.RESET}")
        open_browser_cookie_settings()
    return total > 0

def ping_test(host="8.8.8.8"):
    try:
        r = subprocess.run(["ping", "-n", "2", host],
                           capture_output=True, text=True, timeout=20)
        m = re.search(r"(?:Average|Promedio|平均值)\s*=\s*(\d+)", r.stdout)
        if r.returncode == 0:
            return True, (m.group(1) + " ms" if m else "connected")
        return False, "no response"
    except Exception:
        return False, "error"

def connectivity_status():
    ok, info = ping_test()
    return f"{C.GREEN}● ONLINE ({info}){C.RESET}" if ok else f"{C.RED}● OFFLINE{C.RESET}"

_banner_ping_cache = {"t": 0.0, "s": ""}

def banner_status():
    """Connectivity status for the banner, cached 15 s so the menu stays snappy."""
    now = time.time()
    if now - _banner_ping_cache["t"] < 15 and _banner_ping_cache["s"]:
        return _banner_ping_cache["s"]
    ok, info = ping_test()
    _banner_ping_cache["t"] = now
    _banner_ping_cache["s"] = (f"{C.GREEN}● ONLINE ({info}){C.RESET}" if ok
                               else f"{C.RED}● OFFLINE{C.RESET}")
    return _banner_ping_cache["s"]

# ── Banner & menu ───────────────────────────────────────────────────────────
BANNER_ART = [
    " ███╗   ███╗ █████╗  ██████╗     ███████╗██████╗  ██████╗  ██████╗ ███████╗██████╗",
    " ████╗ ████║██╔══██╗██╔════╝     ██╔════╝██╔══██╗██╔═══██╗██╔═══██╗██╔════╝██╔══██╗",
    " ██╔████╔██║███████║██║          ███████╗██████╔╝██║   ██║██║   ██║█████╗  ██████╔╝",
    " ██║╚██╔╝██║██╔══██║██║          ╚════██║██╔═══╝ ██║   ██║██║   ██║██╔══╝  ██╔═══╝",
    " ██║ ╚═╝ ██║██║  ██║╚██████╗     ███████║██║     ╚██████╔╝╚██████╔╝███████╗██║",
    " ╚═╝     ╚═╝╚═╝  ╚═╝ ╚═════╝     ╚══════╝╚═╝      ╚═════╝  ╚═════╝ ╚══════╝╚═╝",
]
GRADIENT = [C.B_RED, C.B_YELLOW, C.B_GREEN, C.B_CYAN, C.B_BLUE, C.B_MAGENTA]

def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")

def print_banner():
    w = max(vlen(l) for l in BANNER_ART)
    inner = w + 2  # content width inside the box — keeps every '│' aligned
    print(f"  {ACCENT}┌─{'═' * inner}─┐{C.RESET}")
    for i, line in enumerate(BANNER_ART):
        print(f"  {ACCENT}│ {pad(GRADIENT[i] + line, inner)} │{C.RESET}")
    tag = f"{C.BOLD}{C.WHITE}M A C   A D D R E S S   S P O O F E R{C.RESET}{C.DIM}   ·   v{VERSION}{C.RESET}"
    print(f"  {ACCENT}│ {pad(center_text(tag, inner), inner)} │{C.RESET}")
    print(f"  {ACCENT}└─{'═' * inner}─┘{C.RESET}")
    # Status bar
    admin = f"{C.GREEN}● ADMIN ✓{C.RESET}" if is_admin() else f"{C.YELLOW}● READ-ONLY{C.RESET}"
    priv = f"{C.YELLOW}🔒 PRIVACY ON{C.RESET}" if PRIVACY_MODE else f"{C.RED}👁 REVEALED{C.RESET}"
    now = datetime.now().strftime("%H:%M")
    print(f"\n  {priv}   {admin}   {C.DIM}{now}{C.RESET}   {banner_status()}\n")

def print_menu():
    def cell(num, label):
        return f"{ACCENT}[{num}]{C.RESET} {C.WHITE}{label}{C.RESET}"
    left = [
        ("1", "📋 Adapters & MACs"),
        ("2", "🌐 IP & Network"),
        ("3", "🎲 Random MAC"),
        ("4", "📝 Custom MAC"),
        ("5", "🔄 Spoof MAC"),
        ("6", "🔙 Restore MAC"),
        ("7", "🧹 Flush DNS"),
    ]
    middle = [
        ("8", "🔌 Renew IP"),
        ("9", "🚀 Full Privacy Reset"),
        ("10", "🕘 MAC History"),
        ("11", "🆕 New Account Prep"),
        ("12", "💻 Identity Check"),
        ("13", "📶 Ping Test"),
        ("14", "🔁 Restart Adapter"),
    ]
    right = [
        ("15", "💾 Backup Manager"),
        ("16", "🎨 Theme"),
        ("17", "🧬 MachineGUID + Hostname"),
        ("18", "🎮 Roblox DeviceID"),
        ("19", "💽 Volume Serial"),
        ("20", "🍪 Roblox Cookies"),
        ("0", "🚪 Exit"),
    ]
    wl = max(vlen(cell(n, l)) for n, l in left)
    wm = max(vlen(cell(n, l)) for n, l in middle)
    rows = []
    for (ln, ll), (mn, ml), (rn, rl) in zip(left, middle, right):
        rows.append(pad(cell(ln, ll), wl) + "   " + pad(cell(mn, ml), wm) + "   " + cell(rn, rl))
    rows.append("")
    rows.append("   " + cell("P", "🔒 Privacy: hide/reveal IPs & MACs (####)"))
    print(panel("M E N U", rows, title_center=True))

def press_enter():
    try:
        input(f"\n  {C.DIM}Press Enter to continue...{C.RESET}")
    except (EOFError, KeyboardInterrupt):
        pass

def ask_yes_no(prompt, default_yes=True):
    d = "Y/n" if default_yes else "y/N"
    try:
        a = input(f"  {C.YELLOW}{prompt} [{d}]: {C.RESET}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default_yes
    if a == "":
        return default_yes
    return a in ("y", "yes", "s", "si", "sí")

# ── Adapter selection ───────────────────────────────────────────────────────
def select_adapter(adapters):
    active = [a for a in adapters if a.get("Status", "").lower() in ("up", "connected")]
    others = [a for a in adapters if a not in active]
    ordered = active + others

    print(f"\n  {C.BOLD}{ACCENT}📡 Available Network Adapters{C.RESET}\n")
    rows = []
    for i, a in enumerate(ordered, 1):
        st = a.get("Status", "").lower()
        status = f"{C.GREEN}● UP{C.RESET}" if st in ("up", "connected") else f"{C.DIM}○ DOWN{C.RESET}"
        mac = a.get("MacAddress") or "N/A"
        rows.append([str(i), a.get("Name", "?"), status, mac_disp(mac), vendor_of(mac)])
    print_table(["#", "ADAPTER", "STATUS", "MAC ADDRESS", "VENDOR"], rows)

    try:
        choice = input(f"\n  {C.YELLOW}Select adapter [1-{len(ordered)}]: {C.RESET}").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(ordered):
            return ordered[int(choice) - 1]
    except (EOFError, KeyboardInterrupt):
        return None
    cprint("  ✗ Invalid selection.", C.B_RED)
    return None

# ── Features ────────────────────────────────────────────────────────────────
def feature_view_adapters():
    print(f"\n  {C.BOLD}{ACCENT}📋 Network Adapters & MAC Addresses{C.RESET}\n")
    with Spinner("Scanning adapters"):
        adapters = get_network_adapters()
    if not adapters:
        cprint("  ✗ Could not retrieve adapter information.", C.B_RED)
        return

    rows = []
    for a in adapters:
        st = a.get("Status", "").lower()
        status = f"{C.GREEN}● UP{C.RESET}" if st in ("up", "connected") else f"{C.DIM}○ DOWN{C.RESET}"
        mac = a.get("MacAddress") or "N/A"
        rows.append([a.get("Name", "?"), status, mac_disp(mac), vendor_of(mac)])
    print_table(["ADAPTER", "STATUS", "MAC ADDRESS", "VENDOR"], rows)

    backup = load_backup()
    for a in adapters:
        name = a.get("Name", "")
        if name in backup:
            print(f"\n  {C.MAGENTA}⚠ {C.BOLD}{name}{C.RESET} is spoofed — original: {mac_disp(backup[name])}{C.RESET}")
        mac = a.get("MacAddress") or ""
        if mac and mac != "N/A":
            print(f"  {C.DIM}  {name}: {mac_disp(mac)}{C.RESET} {mac_badge(mac)}{C.RESET}")

def feature_view_ip():
    print(f"\n  {C.BOLD}{ACCENT}🌐 IP & Network Information{C.RESET}\n")
    with Spinner("Reading network configuration"):
        ip_info = get_ip_info()
    if ip_info:
        rows = []
        for info in ip_info:
            rows.append([
                info.get("InterfaceAlias", "?"),
                pv(info.get("IPv4Address", "-")),
                pv(info.get("IPv4Gateway", "-") or "-"),
                pv(info.get("DNSServer", "-") or "-"),
                mac_disp(info.get("MacAddress", "-")),
            ])
        print_table(["INTERFACE", "IPv4", "GATEWAY", "DNS", "MAC"], rows)
    else:
        cprint("  No active connections found.", C.DIM)

    print()
    with Spinner("Fetching public IP"):
        pub = get_public_ip()
    print(f"  {C.BOLD}Public IP:{C.RESET}   {C.GREEN}{pv(pub)}{C.RESET}")
    ok, info = ping_test()
    if ok:
        print(f"  {C.BOLD}Connectivity:{C.RESET} {C.GREEN}● ONLINE ({info}){C.RESET}")
    else:
        print(f"  {C.BOLD}Connectivity:{C.RESET} {C.RED}● no response{C.RESET}")

def feature_generate_mac():
    print(f"\n  {C.BOLD}{ACCENT}🎲 Random MAC Generator{C.RESET}\n")
    print("  [1] Vendor-realistic  (looks like real hardware)")
    print("  [2] Fully random      (locally administered)")
    try:
        mode = input(f"\n  {C.YELLOW}Mode [1-2] (Enter = both): {C.RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        return

    cands = []
    if mode in ("", "1"):
        cands += [(generate_random_mac(vendor_specific=True), "vendor-realistic") for _ in range(4)]
    if mode in ("", "2"):
        cands += [(generate_random_mac(vendor_specific=False), "fully random") for _ in range(4)]

    while True:
        print()
        rows = []
        for i, (m, kind) in enumerate(cands, 1):
            rows.append([str(i), mac_color(m, reveal=True), kind, vendor_of(m)])
        print_table(["#", "MAC ADDRESS", "TYPE", "VENDOR"], rows)
        print(f"\n  {C.DIM}Copy one to clipboard (1-{len(cands)}), or press Enter to go back.{C.RESET}")
        try:
            a = input(f"  {C.YELLOW}> {C.RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if a == "":
            return
        if a.isdigit() and 1 <= int(a) <= len(cands):
            m = cands[int(a) - 1][0]
            if copy_clipboard(m):
                print(f"  {C.GREEN}✓ {m} copied to clipboard!{C.RESET}")
            else:
                print(f"  {C.YELLOW}ℹ {m}{C.RESET}")
        else:
            return

def feature_custom_mac():
    print(f"\n  {C.BOLD}{ACCENT}📝 MAC Address Checker{C.RESET}\n")
    try:
        mac = input(f"  {C.YELLOW}MAC (XX:XX:XX:XX:XX:XX): {C.RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        return
    mac = normalize_mac(mac)
    if not is_valid_mac(mac):
        cprint("  ✗ Invalid MAC format. Use e.g. 1A:2B:3C:4D:5E:6F", C.B_RED)
        return
    print()
    print(f"  {C.BOLD}MAC:{C.RESET}      {mac_color(mac)}")
    print(f"  {C.BOLD}Vendor:{C.RESET}   {C.CYAN}{vendor_of(mac)}{C.RESET}")
    print(f"  {C.BOLD}Type:{C.RESET}     {C.GREEN}{'Locally Administered (spoofeable)' if is_laa(mac) else 'Universally Administered (factory)'}{C.RESET}")
    if is_laa(mac):
        print(f"  {C.DIM}  This MAC looks like a spoof — drivers will accept it.{C.RESET}")
    if copy_clipboard(mac):
        print(f"  {C.GREEN}✓ Copied to clipboard.{C.RESET}")

def pick_mac_source(name):
    """Ask how the new MAC should be chosen. Returns MAC string or None."""
    print(f"\n  {C.CYAN}How would you like the new MAC?{C.RESET}")
    print(f"    {C.CYAN}[1]{C.RESET} Random — vendor-realistic")
    print(f"    {C.CYAN}[2]{C.RESET} Random — fully random")
    print(f"    {C.CYAN}[3]{C.RESET} Enter custom MAC")
    print(f"    {C.CYAN}[4]{C.RESET} Reuse from history")
    try:
        choice = input(f"\n  {C.YELLOW}Choice [1-4]: {C.RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if choice == "1":
        return generate_random_mac(vendor_specific=True)
    if choice == "2":
        return generate_random_mac(vendor_specific=False)
    if choice == "3":
        try:
            custom = input(f"  {C.YELLOW}MAC (XX:XX:XX:XX:XX:XX): {C.RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        custom = normalize_mac(custom)
        if not is_valid_mac(custom):
            cprint("  ✗ Invalid MAC format!", C.B_RED)
            return None
        return custom
    if choice == "4":
        hist = load_history()
        if not hist:
            cprint("  History is empty. Generate one first.", C.YELLOW)
            return None
        print()
        rows = []
        for i, h in enumerate(hist[:8], 1):
            rows.append([str(i), h.get("time", ""), h.get("adapter", ""), mac_color(h.get("mac", ""))])
        print_table(["#", "WHEN", "ADAPTER", "MAC"], rows)
        try:
            pick = input(f"\n  {C.YELLOW}Pick one [1-{min(8, len(hist))}]: {C.RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if pick.isdigit() and 1 <= int(pick) <= min(8, len(hist)):
            return hist[int(pick) - 1].get("mac")
        cprint("  ✗ Invalid pick.", C.B_RED)
        return None
    cprint("  ✗ Invalid choice.", C.B_RED)
    return None

def feature_spoof_mac():
    print(f"\n  {C.BOLD}{ACCENT}🔄 Spoof MAC Address{C.RESET}\n")
    with Spinner("Scanning adapters"):
        adapters = get_network_adapters()
    if not adapters:
        cprint("  ✗ Could not retrieve adapters.", C.B_RED)
        return

    adapter = select_adapter(adapters)
    if not adapter:
        return
    name = adapter.get("Name", "")
    current_mac = adapter.get("MacAddress", "N/A")

    print(f"\n  {C.BOLD}Adapter:{C.RESET}     {C.WHITE}{name}{C.RESET}")
    print(f"  {C.BOLD}Current MAC:{C.RESET} {mac_disp(current_mac)}")

    new_mac = pick_mac_source(name)
    if not new_mac:
        return

    print(f"\n  {C.BOLD}New MAC:{C.RESET}     {mac_color(new_mac, reveal=True)}")
    print(f"  {C.DIM}  {mac_badge(new_mac)}{C.RESET}")
    if not ask_yes_no("Apply this MAC?", True):
        cprint("  Cancelled.", C.DIM)
        return

    backup = load_backup()
    if name not in backup and is_valid_mac(current_mac):
        backup[name] = current_mac
        save_backup(backup)
        print(f"  {C.GREEN}✓ Original MAC saved to backup.{C.RESET}")

    # Warn about stubborn drivers (Realtek) before attempting
    if not warn_stubborn_driver(name):
        return

    print()
    with Spinner("Spoofing MAC (adapter will restart)"):
        success, msg = spoof_mac(name, new_mac)

    if success:
        add_history(name, new_mac)
        log_action("SPOOF", name, new_mac, "ok")
        print(f"  {C.GREEN}{C.BOLD}✓ MAC address spoofed successfully!{C.RESET}")
        print(f"  {C.DIM}  {msg}. Connectivity may drop for a few seconds.{C.RESET}")
        print()
        with Spinner("Checking connectivity"):
            time.sleep(1)
            ok, info = ping_test()
        print(f"  {C.BOLD}Connectivity:{C.RESET} {connectivity_status() if ok else f'{C.RED}● OFFLINE{C.RESET}'}")
        if not ok:
            print(f"  {C.YELLOW}  ℹ Waiting a few seconds and retrying...{C.RESET}")
            time.sleep(5)
            ok, info = ping_test()
            print(f"  {C.BOLD}Connectivity:{C.RESET} {C.GREEN}● ONLINE ({info}){C.RESET}" if ok
                  else f"  {C.BOLD}Connectivity:{C.RESET} {C.RED}● still offline — check your adapter{C.RESET}")
    else:
        cprint(f"  ✗ Failed to spoof MAC: {msg}", C.B_RED)
        cprint("    Tip: run as Administrator and check the adapter supports MAC override.", C.YELLOW)

def feature_restore_mac():
    print(f"\n  {C.BOLD}{ACCENT}🔙 Restore Original MAC{C.RESET}\n")
    backup = load_backup()
    if not backup:
        print(f"  {C.YELLOW}ℹ No backup found — will attempt to remove any registry override.{C.RESET}")
    elif len(backup) > 1 and ask_yes_no(f"Restore ALL {len(backup)} spoofed adapters?"):
        restored = 0
        for name2 in list(backup.keys()):
            with Spinner(f"Restoring {name2}"):
                ok2, _ = remove_spoof(name2)
            if ok2:
                log_action("RESTORE_ALL", name2, "-", "ok")
                del backup[name2]
                save_backup(backup)
                restored += 1
                print(f"  {C.GREEN}  ✓ {name2} restored to factory MAC{C.RESET}")
            else:
                print(f"  {C.YELLOW}  ⚠ {name2}: nothing to remove{C.RESET}")
        print(f"\n  {C.GREEN}{C.BOLD}✓ Restore-all finished: {restored} adapter(s) back to factory.{C.RESET}")
        return

    with Spinner("Scanning adapters"):
        adapters = get_network_adapters()
    if not adapters:
        cprint("  ✗ Could not retrieve adapters.", C.B_RED)
        return

    adapter = select_adapter(adapters)
    if not adapter:
        return
    name = adapter.get("Name", "")
    print(f"\n  {C.CYAN}Removing spoof for: {C.BOLD}{name}{C.RESET}")

    print()
    with Spinner("Removing spoof"):
        success, msg = remove_spoof(name)

    if success:
        log_action("RESTORE", name, "-", "ok")
        print(f"  {C.GREEN}{C.BOLD}✓ MAC spoof removed!{C.RESET}")
        print(f"  {C.DIM}  Adapter will use its original hardware MAC.{C.RESET}")
        if name in backup:
            del backup[name]
            save_backup(backup)
    else:
        print(f"  {C.YELLOW}ℹ {msg}{C.RESET}")
        if name in backup:
            original = backup[name]
            print(f"  {C.CYAN}Restoring from backup: {mac_disp(original)}{C.RESET}")
            with Spinner("Restoring original MAC"):
                ok2, _ = spoof_mac(name, original)
            if ok2:
                print(f"  {C.GREEN}✓ Restored: {pv(original)}{C.RESET}")
                del backup[name]
                save_backup(backup)
            else:
                cprint("  ✗ Could not restore from backup.", C.B_RED)

def feature_flush_dns():
    print(f"\n  {C.BOLD}{ACCENT}🧹 Flush DNS Cache{C.RESET}\n")
    with Spinner("Flushing DNS resolver cache"):
        ok = flush_dns()
    if ok:
        print(f"  {C.GREEN}{C.BOLD}✓ DNS cache flushed!{C.RESET}")
    else:
        cprint("  ✗ Failed to flush DNS cache.", C.B_RED)

def feature_release_renew():
    print(f"\n  {C.BOLD}{ACCENT}🔌 Renew IP Address (DHCP){C.RESET}\n")
    print(f"  {C.YELLOW}⚠ This will temporarily disconnect your network.{C.RESET}")
    if not ask_yes_no("Continue?", True):
        cprint("  Cancelled.", C.DIM)
        return
    print()
    with Spinner("Releasing & renewing IP (up to ~30 s)"):
        ok = release_renew_ip()
    if ok:
        print(f"  {C.GREEN}{C.BOLD}✓ IP address renewed!{C.RESET}")
        with Spinner("Checking connectivity"):
            time.sleep(2)
            ping_test()
        print(f"  {C.BOLD}Connectivity:{C.RESET} {connectivity_status()}")
    else:
        cprint("  ✗ Failed to renew IP.", C.B_RED)

def feature_full_reset():
    print(f"\n  {C.BOLD}{ACCENT}🚀 Full Privacy Reset (All-in-One){C.RESET}\n")
    print("  This will:")
    print(f"    {C.CYAN}1.{C.RESET} Wipe Roblox DeviceID & browser cookies (sessions first)")
    print(f"    {C.CYAN}2.{C.RESET} Change hostname, MachineGUID & volume serial (HWID)")
    print(f"    {C.CYAN}3.{C.RESET} Generate & apply a new random MAC")
    print(f"    {C.CYAN}4.{C.RESET} Flush DNS & renew IP address")
    print(f"    {C.CYAN}5.{C.RESET} Verify connectivity & show new config")
    print(f"\n  {C.YELLOW}⚠ Your network will briefly disconnect.{C.RESET}")
    print(f"  {C.YELLOW}⚠ Each HWID step asks before changing; reboot required at the end.{C.RESET}")
    if not ask_yes_no("Continue?", True):
        cprint("  Cancelled.", C.DIM)
        return

    with Spinner("Scanning adapters"):
        adapters = get_network_adapters()
    if not adapters:
        cprint("  ✗ Could not retrieve adapters.", C.B_RED)
        return
    adapter = select_adapter(adapters)
    if not adapter:
        return
    name = adapter.get("Name", "")
    current_mac = adapter.get("MacAddress", "N/A")

    # ── Phase 1: Kill sessions first (cookies + DeviceID) ──────────────────
    print(f"\n  {C.CYAN}[1/5]{C.RESET} Wiping Roblox sessions & browser cookies...")
    print(f"  {C.DIM}    (sessions die first so no fingerprint links to the new HWID){C.RESET}")
    roblox_cleanup_step()
    browser_cookies_step()

    # ── Phase 2: Change HWID (hostname + MachineGuid + volume serial) ─────
    print(f"\n  {C.CYAN}[2/5]{C.RESET} Changing Windows identity (HWID + hostname)...")
    hostname_step()
    machine_guid_step()
    volume_serial_step()

    # ── Phase 3: Change network identity (MAC + IP) ────────────────────────
    new_mac = generate_random_mac(vendor_specific=True)
    backup = load_backup()
    if name not in backup and is_valid_mac(current_mac):
        backup[name] = current_mac
        save_backup(backup)

    if not warn_stubborn_driver(name):
        return

    print(f"\n  {C.CYAN}[3/5]{C.RESET} New MAC: {mac_color(new_mac, reveal=True)}")
    with Spinner("Applying spoof"):
        ok_mac, _ = spoof_mac(name, new_mac)
    if ok_mac:
        add_history(name, new_mac)
        log_action("FULL_RESET", name, new_mac, "ok")
        print(f"  {C.GREEN}    ✓ MAC spoofed{C.RESET}")
    else:
        cprint("    ✗ MAC spoof failed — continuing with remaining steps", C.B_RED)

    print(f"  {C.CYAN}[4/5]{C.RESET} Flushing DNS & renewing IP...")
    ok_dns = flush_dns()
    print(f"  {C.GREEN}    ✓ DNS flushed{C.RESET}" if ok_dns else f"  {C.RED}    ✗ DNS flush failed{C.RESET}")
    with Spinner("Renewing IP (up to ~30 s)"):
        ok_ip = release_renew_ip()
    print(f"  {C.GREEN}    ✓ IP renewed{C.RESET}" if ok_ip else f"  {C.YELLOW}    ⚠ IP renewal may have failed{C.RESET}")

    # ── Phase 4: Verify ────────────────────────────────────────────────────
    print(f"  {C.CYAN}[5/5]{C.RESET} Verifying connectivity...")
    with Spinner("Testing connection"):
        time.sleep(2)
        ok_ping, ping_info = ping_test()

    lines = [
        f"{C.BOLD}{C.WHITE}✓ Full Privacy Reset Complete!{C.RESET}",
        "",
        f"{C.WHITE}Adapter:{C.RESET}     {C.BOLD}{name}{C.RESET}",
        f"{C.WHITE}New MAC:{C.RESET}     {mac_color(new_mac, reveal=True)}",
        f"{C.WHITE}Vendor:{C.RESET}      {C.CYAN}{vendor_of(new_mac)}{C.RESET}",
        f"{C.WHITE}Connectivity:{C.RESET} {C.GREEN}● ONLINE ({ping_info}){C.RESET}" if ok_ping
        else f"{C.WHITE}Connectivity:{C.RESET} {C.RED}● OFFLINE{C.RESET}",
    ]
    with Spinner("Fetching public IP"):
        pub = get_public_ip()
    lines.append(f"{C.WHITE}Public IP:{C.RESET}    {C.GREEN}{pv(pub)}{C.RESET}")
    lines += [
        "",
        f"{C.DIM}Next: use a NEW email/username, and REBOOT before playing so the{C.RESET}",
        f"{C.DIM}new hostname, MachineGUID & volume serial fully take effect.{C.RESET}",
    ]
    print("\n" + panel(None, lines, border=C.GREEN))

def feature_history():
    print(f"\n  {C.BOLD}{ACCENT}🕘 MAC Spoof History{C.RESET}\n")
    hist = load_history()
    if not hist:
        cprint("  No history yet. Go spoof some MACs! 😄", C.DIM)
        return
    rows = []
    for h in hist[:15]:
        rows.append([h.get("time", ""), h.get("adapter", ""), mac_color(h.get("mac", "")), h.get("vendor", "")])
    print_table(["WHEN", "ADAPTER", "MAC ADDRESS", "VENDOR"], rows)
    print()
    if ask_yes_no("Clear history?", False):
        save_history([])
        print(f"  {C.GREEN}✓ History cleared.{C.RESET}")

# ── Feature 11: New Account Prep ────────────────────────────────────────────
def feature_new_account_prep():
    print(f"\n  {C.BOLD}{ACCENT}🆕 New Account Prep (Identity Reset){C.RESET}\n")
    print("  This prepares your network identity before creating a new account:")
    print(f"    {ACCENT}1.{C.RESET} Wipe Roblox DeviceID & browser cookies (sessions first)")
    print(f"    {ACCENT}2.{C.RESET} Change hostname & MachineGUID (Windows identity)")
    print(f"    {ACCENT}3.{C.RESET} New random MAC (vendor-realistic)")
    print(f"    {ACCENT}4.{C.RESET} Flush DNS & renew IP (DHCP)")
    print(f"    {ACCENT}5.{C.RESET} Verify connectivity & public IP")
    print(f"\n  {C.YELLOW}⚠ Your network will briefly disconnect.{C.RESET}")
    if not ask_yes_no("Run full identity prep?", True):
        cprint("  Cancelled.", C.DIM)
        return

    with Spinner("Scanning adapters"):
        adapters = get_network_adapters()
    if not adapters:
        cprint("  ✗ Could not retrieve adapters.", C.B_RED)
        return
    active = [a for a in adapters if a.get("Status", "").lower() in ("up", "connected")]
    if len(active) == 1:
        adapter = active[0]
        print(f"\n  {ACCENT}Auto-selected active adapter: {C.BOLD}{adapter.get('Name', '?')}{C.RESET}")
    else:
        adapter = select_adapter(adapters)
    if not adapter:
        return

    name = adapter.get("Name", "")
    current_mac = adapter.get("MacAddress", "N/A")

    # ── Phase 1: Kill sessions first ───────────────────────────────────────
    print(f"\n  {ACCENT}[1/5]{C.RESET} Wiping Roblox sessions & browser cookies...")
    print(f"  {C.DIM}    (sessions die first so no fingerprint links to the new HWID){C.RESET}")
    roblox_cleanup_step()
    browser_cookies_step()

    # ── Phase 2: Change HWID (hostname + MachineGUID) ─────────────────────
    print(f"\n  {ACCENT}[2/5]{C.RESET} Changing Windows identity (hostname + MachineGUID)...")
    hostname_step()
    machine_guid_step()

    # ── Phase 3: Change network identity ────────────────────────────────────
    new_mac = generate_random_mac(vendor_specific=True)
    backup = load_backup()
    if name not in backup and is_valid_mac(current_mac):
        backup[name] = current_mac
        save_backup(backup)

    if not warn_stubborn_driver(name):
        return

    print(f"\n  {ACCENT}[3/5]{C.RESET} New MAC: {mac_color(new_mac, reveal=True)}")
    with Spinner("Applying spoof"):
        ok_mac, msg = spoof_mac(name, new_mac)
    if ok_mac:
        add_history(name, new_mac)
        log_action("NEW_ACCOUNT_PREP", name, new_mac, "ok")
        print(f"  {C.GREEN}    ✓ MAC spoofed{C.RESET}")
    else:
        cprint(f"    ✗ MAC spoof failed: {msg}", C.B_RED)

    print(f"  {ACCENT}[4/5]{C.RESET} Flushing DNS & renewing IP...")
    ok_dns = flush_dns()
    print(f"  {C.GREEN}    ✓ DNS flushed{C.RESET}" if ok_dns else f"  {C.RED}    ✗ DNS flush failed{C.RESET}")
    with Spinner("Renewing IP (up to ~30 s)"):
        ok_ip = release_renew_ip()
    print(f"  {C.GREEN}    ✓ IP renewed{C.RESET}" if ok_ip else f"  {C.YELLOW}    ⚠ IP renewal may have failed{C.RESET}")

    # ── Phase 4: Verify ────────────────────────────────────────────────────
    print(f"  {ACCENT}[5/5]{C.RESET} Verifying connectivity...")
    with Spinner("Testing connection"):
        time.sleep(2)
        ok_ping, ping_info = ping_test()
    with Spinner("Fetching public IP"):
        pub = get_public_ip()

    lines = [
        f"{C.BOLD}{C.WHITE}✓ Identity prep complete!{C.RESET}",
        "",
        f"{C.WHITE}Adapter:{C.RESET}     {C.BOLD}{name}{C.RESET}",
        f"{C.WHITE}New MAC:{C.RESET}     {mac_color(new_mac, reveal=True)}",
        f"{C.WHITE}Public IP:{C.RESET}    {C.GREEN}{pv(pub)}{C.RESET}",
        f"{C.WHITE}Connectivity:{C.RESET} {C.GREEN}● ONLINE ({ping_info}){C.RESET}" if ok_ping
        else f"{C.WHITE}Connectivity:{C.RESET} {C.RED}● OFFLINE{C.RESET}",
        "",
        f"{C.DIM}Reminder: reboot before creating the account so the new{C.RESET}",
        f"{C.DIM}hostname & MachineGUID take effect, and use a new email/username.{C.RESET}",
    ]
    print("\n" + panel(None, lines, border=C.GREEN))

# ── Feature 12: Identity Check ──────────────────────────────────────────────
def feature_identity_check():
    print(f"\n  {C.BOLD}{ACCENT}💻 Identity Checklist{C.RESET}\n")
    with Spinner("Gathering identifiers"):
        adapters = get_network_adapters()
        ip_info = get_ip_info()
        pub = get_public_ip()
    ok, info = ping_test()
    backup = load_backup()
    vpn = detect_vpn(adapters)
    ipv4 = ip_info[0].get("IPv4Address", "-") if ip_info else "-"

    lines = [
        f"{C.WHITE}Computer:{C.RESET}   {C.BOLD}{pv(os.environ.get('COMPUTERNAME', '?'))}{C.RESET}  ({pv(os.environ.get('USERNAME', '?'))})",
        f"{C.WHITE}OS:{C.RESET}         {C.DIM}{platform.platform()}{C.RESET}",
        f"{C.WHITE}MachineGUID:{C.RESET} {C.CYAN}{pv(get_machine_guid() or '-')}{C.RESET}",
        f"{C.WHITE}Vol Serial:{C.RESET}  {C.CYAN}{pv(get_volume_serial() or '-')}{C.RESET}",
        f"{C.WHITE}IPv4:{C.RESET}       {C.CYAN}{pv(ipv4)}{C.RESET}",
        f"{C.WHITE}Public IP:{C.RESET}  {C.GREEN}{pv(pub)}{C.RESET}",
        f"{C.WHITE}VPN:{C.RESET}        {C.GREEN}✓ VPN adapter detected{C.RESET}" if vpn
        else f"{C.WHITE}VPN:{C.RESET}        {C.YELLOW}✗ no VPN detected{C.RESET}",
        f"{C.WHITE}Connectivity:{C.RESET} {C.GREEN}● ONLINE ({info}){C.RESET}" if ok
        else f"{C.WHITE}Connectivity:{C.RESET} {C.RED}● OFFLINE{C.RESET}",
    ]
    print("\n" + panel("I D E N T I T Y", lines))

    print(f"\n  {C.BOLD}{ACCENT}Adapters:{C.RESET}\n")
    rows = []
    for a in adapters:
        st = a.get("Status", "").lower()
        status = f"{C.GREEN}● UP{C.RESET}" if st in ("up", "connected") else f"{C.DIM}○ DOWN{C.RESET}"
        mac = a.get("MacAddress") or "N/A"
        rows.append([a.get("Name", "?"), status, mac_disp(mac), vendor_of(mac)])
    print_table(["ADAPTER", "STATUS", "MAC ADDRESS", "VENDOR"], rows)

    spoofed = []
    for a in adapters:
        nm = a.get("Name", "")
        cur = normalize_mac(a.get("MacAddress") or "")
        orig = normalize_mac(backup.get(nm, "")) if nm in backup else ""
        if is_valid_mac(cur) and is_valid_mac(orig) and cur != orig:
            spoofed.append(nm)
    if spoofed:
        print(f"\n  {C.MAGENTA}⚠ Spoofed adapters ({len(spoofed)}): {C.BOLD}{', '.join(spoofed)}{C.RESET}")
    else:
        print(f"\n  {C.GREEN}✓ No active spoofs detected — hardware MACs in use.{C.RESET}")

# ── Feature 13: Ping Test ───────────────────────────────────────────────────
def feature_ping_test():
    print(f"\n  {C.BOLD}{ACCENT}📶 Ping Test{C.RESET}\n")
    try:
        host = re.sub(r"[^A-Za-z0-9.:_-]", "", input(f"  {C.YELLOW}Host (Enter = 8.8.8.8): {C.RESET}").strip()) or "8.8.8.8"
    except (EOFError, KeyboardInterrupt):
        return
    print(f"\n  {C.CYAN}Pinging {C.BOLD}{host}{C.RESET}{C.CYAN} — 4 requests...{C.RESET}\n")
    try:
        r = subprocess.run(["ping", "-n", "4", host], capture_output=True, text=True, timeout=30)
    except Exception:
        cprint("  ✗ Could not run ping.", C.B_RED)
        return
    for line in r.stdout.splitlines():
        t = line.strip()
        if t and any(k in t.lower() for k in ("reply", "respuesta", "time", "tiempo", "ttl", "bytes")):
            print(f"  {C.DIM}{t}{C.RESET}")
    times = re.findall(r"(?:time|tiempo)[=<]\s*(\d+)", r.stdout, re.I)
    if times:
        nums = [int(x) for x in times]
        print(f"\n  {C.BOLD}Stats:{C.RESET}  min {C.CYAN}{min(nums)} ms{C.RESET}  ·  avg {C.CYAN}{sum(nums) // len(nums)} ms{C.RESET}  ·  max {C.CYAN}{max(nums)} ms{C.RESET}")
    if r.returncode == 0:
        print(f"  {C.GREEN}✓ {host} is reachable{C.RESET}")
    else:
        print(f"  {C.RED}✗ {host} unreachable (packet loss){C.RESET}")

# ── Feature 14: Restart Adapter ─────────────────────────────────────────────
def feature_restart_adapter():
    print(f"\n  {C.BOLD}{ACCENT}🔁 Restart Network Adapter{C.RESET}\n")
    with Spinner("Scanning adapters"):
        adapters = get_network_adapters()
    if not adapters:
        cprint("  ✗ Could not retrieve adapters.", C.B_RED)
        return
    adapter = select_adapter(adapters)
    if not adapter:
        return
    name = adapter.get("Name", "")
    print(f"\n  {C.YELLOW}⚠ This will briefly disconnect: {C.BOLD}{name}{C.RESET}")
    if not ask_yes_no("Restart this adapter?", True):
        cprint("  Cancelled.", C.DIM)
        return
    with Spinner(f"Restarting {name}"):
        ok = restart_adapter(name)
    if ok:
        log_action("RESTART", name, "-", "ok")
        print(f"  {C.GREEN}{C.BOLD}✓ Adapter restarted!{C.RESET}")
        with Spinner("Checking connectivity"):
            time.sleep(2)
            ping_test()
        print(f"  {C.BOLD}Connectivity:{C.RESET} {connectivity_status()}")
    else:
        cprint("  ✗ Failed to restart adapter.", C.B_RED)

# ── Feature 15: Backup Manager ──────────────────────────────────────────────
def feature_backup_manager():
    print(f"\n  {C.BOLD}{ACCENT}💾 Backup Manager{C.RESET}\n")
    backup = load_backup()
    if not backup:
        cprint("  Backup is empty (nothing spoofed yet).", C.DIM)
        print(f"  {C.DIM}  Stored at: {BACKUP_FILE}{C.RESET}")
        return
    rows = [[name, mac_disp(mac), vendor_of(mac)] for name, mac in backup.items()]
    print_table(["ADAPTER", "ORIGINAL MAC", "VENDOR"], rows)
    print()
    print("  [1] Export backup to file")
    print("  [2] Clear backup")
    try:
        c = input(f"  {C.YELLOW}Choice (Enter = back): {C.RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if c == "1":
        fname = APP_DIR / f"mac_spoofer_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_json(fname, backup)
        print(f"  {C.GREEN}✓ Exported to: {C.BOLD}{fname}{C.RESET}")
    elif c == "2":
        if ask_yes_no("Clear backup?", False):
            save_backup({})
            print(f"  {C.GREEN}✓ Backup cleared.{C.RESET}")
    else:
        cprint("  No change.", C.DIM)

# ── Feature 16: Theme ───────────────────────────────────────────────────────
def feature_theme():
    global ACCENT
    print(f"\n  {C.BOLD}{ACCENT}🎨 Theme{C.RESET}\n")
    print(f"  {C.DIM}Accent color for borders, tables and menu:{C.RESET}\n")
    for k, (label, color) in THEMES.items():
        cur = "  ← current" if ACCENT == color else ""
        print(f"    {ACCENT}[{k}]{C.RESET} {color}{label}{C.RESET}{C.DIM}{cur}{C.RESET}")
    try:
        pick = input(f"\n  {C.YELLOW}Theme [1-{len(THEMES)}] (Enter = back): {C.RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        return
    if pick in THEMES:
        ACCENT = THEMES[pick][1]
        save_config()
        print(f"  {C.GREEN}✓ Theme applied: {C.BOLD}{THEMES[pick][0]}{C.RESET}")
    else:
        cprint("  No change.", C.DIM)

# ── Features 17-20: system identity & anti-fingerprint ─────────────────────
def feature_machine_guid():
    print(f"\n  {C.BOLD}{ACCENT}🧬 MachineGUID & Hostname (Windows Identity){C.RESET}\n")
    print(f"  {C.DIM}Roblox/Byfron reads MachineGuid + GetComputerNameExW.{C.RESET}")
    print(f"  {C.DIM}Change both so the PC looks brand-new. Reboot needed.{C.RESET}\n")
    hostname_step()
    print()
    machine_guid_step()

def feature_roblox_deviceid():
    print(f"\n  {C.BOLD}{ACCENT}🎮 Roblox DeviceID Cleaner{C.RESET}\n")
    print(f"  {C.DIM}Roblox stores a deviceId in multiple places:{C.RESET}")
    print(f"  {C.DIM}  • %LOCALAPPDATA%\\Roblox\\LocalStorage\\*.db{C.RESET}")
    print(f"  {C.DIM}  • GlobalBasicSettings_*.xml (login tokens){C.RESET}")
    print(f"  {C.DIM}  • %PROGRAMDATA%\\Roblox (logs & configs){C.RESET}")
    print(f"  {C.DIM}  • HKCU\\Software\\Roblox (registry traces){C.RESET}")
    print(f"  {C.DIM}This wipes all of it (keeping \\Versions) — no reinstall needed.{C.RESET}\n")
    if not ask_yes_no("Close Roblox and wipe its DeviceID & data?", True):
        cprint("  Cancelled.", C.DIM)
        return
    with Spinner("Wiping Roblox data (keeping app version)"):
        cleared = clear_roblox_data()
    if cleared:
        print(f"  {C.GREEN}{C.BOLD}✓ Roblox DeviceID & sessions wiped — app still installed.{C.RESET}")
    else:
        print(f"  {C.YELLOW}⚠ Nothing to clear (Roblox not installed or already clean){C.RESET}")

def feature_volume_serial():
    print(f"\n  {C.BOLD}{ACCENT}💽 Volume Serial Number (Disk HWID){C.RESET}\n")
    print(f"  {C.DIM}Roblox uses GetVolumeInformationA to read the C: drive serial.{C.RESET}")
    print(f"  {C.DIM}Changed with Sysinternals VolumeId — no formatting required.{C.RESET}\n")
    volume_serial_step()

def feature_browser_cookies():
    print(f"\n  {C.BOLD}{ACCENT}🍪 Roblox Cookies Cleaner (All Browsers){C.RESET}\n")
    print(f"  {C.DIM}Deletes roblox.com cookies from Chrome, Edge, Firefox, Brave,{C.RESET}")
    print(f"  {C.DIM}Opera and Vivaldi so the site forgets your login & tracking. The{C.RESET}")
    print(f"  {C.DIM}Roblox app's own session (.ROBLOSECURITY) is removed by option 18.{C.RESET}\n")
    browser_cookies_step()

# ── Self test (no admin needed) ─────────────────────────────────────────────
def selftest():
    print()
    print_banner()
    print(panel("S E L F   T E S T", [
        f"{C.GREEN}✓ ANSI colors ......... working{C.RESET}",
        f"{C.GREEN}✓ Spinner ............. working{C.RESET}",
    ]))
    with Spinner("Testing spinner"):
        time.sleep(0.8)

    print()
    print("  Generating sample MACs:")
    for _ in range(3):
        m = generate_random_mac(vendor_specific=True)
        print(f"    {mac_color(m)}  {mac_badge(m)}")

    print("\n  Validation:")
    print(f"    {C.GREEN}✓ '1A:2B:3C:4D:5E:6F'  → valid{C.RESET}")
    print(f"    {C.GREEN}✓ 'ZZ:00:00:00:00:00'  → invalid{C.RESET}" if not is_valid_mac("ZZ:00:00:00:00:00")
          else f"    {C.RED}✗ validation bug{C.RESET}")

    print("\n  Table render test:")
    print_table(
        ["#", "ADAPTER", "MAC ADDRESS", "VENDOR"],
        [["1", "Wi-Fi", mac_color("02:1A:2B:3C:4D:5E"), "Cisco-like"],
         ["2", "Ethernet", mac_color("00:0C:29:11:22:33"), "VMware"]],
    )
    print("\n  Menu render test:")
    print_menu()
    print(f"\n  {C.GREEN}{C.BOLD}✓ All self tests passed!{C.RESET}")
    print(f"  {C.DIM}You can now run: python mac_spoofer.py (as Administrator){C.RESET}\n")

# ── Main ────────────────────────────────────────────────────────────────────
def main():
    enable_ansi_colors()
    load_config()

    if "--selftest" in sys.argv or "-s" in sys.argv:
        selftest()
        return
    if "--version" in sys.argv or "-v" in sys.argv:
        print(f"MAC Spoofer v{VERSION}")
        return

    if not is_admin():
        print(panel(None, [
            f"{C.B_YELLOW}⚠ Administrator privileges required{C.RESET}",
            "",
            "Spoofing/restoring MACs needs admin rights.",
            "You can relaunch elevated, or continue in read-only",
            "mode (view adapters, IP info, generate MACs).",
        ], border=C.YELLOW))
        if ask_yes_no("Relaunch as Administrator?", True):
            run_as_admin()
            return
        cprint("\n  Continuing in READ-ONLY mode — spoofing disabled.", C.YELLOW)
        time.sleep(1.5)

    while True:
        clear_screen()
        print_banner()
        print_menu()
        try:
            choice = input(f"\n  {C.YELLOW}Select option [0-20] (P = privacy): {C.RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n  {C.DIM}Goodbye! 🛡{C.RESET}\n")
            break

        if choice.lower() == "p":
            toggle_privacy()
            time.sleep(1)
            continue
        if choice == "1":
            feature_view_adapters()
            press_enter()
        elif choice == "2":
            feature_view_ip()
            press_enter()
        elif choice == "3":
            feature_generate_mac()
            press_enter()
        elif choice == "4":
            feature_custom_mac()
            press_enter()
        elif choice == "5":
            feature_spoof_mac()
            press_enter()
        elif choice == "6":
            feature_restore_mac()
            press_enter()
        elif choice == "7":
            feature_flush_dns()
            press_enter()
        elif choice == "8":
            feature_release_renew()
            press_enter()
        elif choice == "9":
            feature_full_reset()
            press_enter()
        elif choice == "10":
            feature_history()
            press_enter()
        elif choice == "11":
            feature_new_account_prep()
            press_enter()
        elif choice == "12":
            feature_identity_check()
            press_enter()
        elif choice == "13":
            feature_ping_test()
            press_enter()
        elif choice == "14":
            feature_restart_adapter()
            press_enter()
        elif choice == "15":
            feature_backup_manager()
            press_enter()
        elif choice == "16":
            feature_theme()
            press_enter()
        elif choice == "17":
            feature_machine_guid()
            press_enter()
        elif choice == "18":
            feature_roblox_deviceid()
            press_enter()
        elif choice == "19":
            feature_volume_serial()
            press_enter()
        elif choice == "20":
            feature_browser_cookies()
            press_enter()
        elif choice == "0":
            print(f"\n  {C.GREEN}Stay safe out there. 🛡{C.RESET}\n")
            break
        else:
            cprint("  Invalid option. Try again.", C.B_RED)
            time.sleep(1)

if __name__ == "__main__":
    main()
