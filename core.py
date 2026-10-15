"""Data collection for the PC awake monitor (Windows).

Pure parsing helpers live at the top so they can be unit-tested on any OS;
the Windows-specific calls are below and only run on win32.
"""
import re
import subprocess
import sys
from dataclasses import dataclass, field

# powercfg GUIDs (locale independent)
SUB_VIDEO = "7516b95f-f776-4464-8c53-06167f40cc99"
VIDEOIDLE = "3c0bc021-c8a8-4e07-a973-6b14cbcb2b7e"
SUB_SLEEP = "238c9fa8-0aad-41ed-83f4-97be242c8f20"
STANDBYIDLE = "29f6c1db-86da-48c5-9fdb-f2b67b1f44da"
HIBERNATEIDLE = "9d7815a6-7ee4-497e-8888-515a05f02364"

# Meaning of each /requests category (English headers; others shown verbatim).
REQUEST_BLOCKS = {
    "DISPLAY": "keeps the screen on (and blocks the screensaver)",
    "SYSTEM": "keeps the PC from sleeping",
    "AWAYMODE": "away mode - PC looks asleep but keeps running",
    "EXECUTION": "stays running in the background; does NOT block sleep or screen-off",
    "PERFBOOST": "performance boost",
    "ACTIVELOCKSCREEN": "lock screen",
}


@dataclass
class Request:
    category: str
    kind: str   # PROCESS / DRIVER / SERVICE
    name: str
    reason: str = ""
    ignored: bool = False


def parse_requests(text):
    """Parse `powercfg /requests`. Entries are recognised by their leading
    [PROCESS]/[DRIVER]/[SERVICE] tag, so this works on localized Windows too."""
    out, category, last = [], "", None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            last = None
            continue
        m = re.match(r"^\[(\w+)\]\s*(.*)$", line)
        if m:
            last = Request(category, m.group(1).upper(), m.group(2))
            out.append(last)
        elif not raw[:1].isspace() and line.endswith(":"):
            category = line[:-1].strip().upper()
            last = None
        elif last is not None:
            last.reason = (last.reason + " " + line).strip()
    return out


def blocks_idle(req):
    """Only DISPLAY/SYSTEM/AWAYMODE requests stop screen-off, screensaver or sleep.
    EXECUTION (e.g. Electron apps) just exempts a process from being suspended."""
    return req.category in ("DISPLAY", "SYSTEM", "AWAYMODE")


def friendly_name(req):
    """`\\Device\\HarddiskVolume3\\...\\chrome.exe` -> `chrome.exe`."""
    return re.split(r"[\\/]", req.name.strip())[-1] or req.name


def parse_power_indexes(text):
    """Return (ac_seconds, dc_seconds) from `powercfg /query <scheme> <sub> <setting>`.
    The last two 0x........ values are AC then DC regardless of language."""
    vals = re.findall(r"0x([0-9a-fA-F]{8})", text)
    if len(vals) < 2:
        return None
    return int(vals[-2], 16), int(vals[-1], 16)


def fmt_duration(seconds):
    if seconds is None:
        return "-"
    s = int(max(0, seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


OVERRIDABLE = ("DISPLAY", "SYSTEM", "AWAYMODE")


def override_key(req):
    """Identity used for `powercfg /requestsoverride` (and our local record)."""
    name = req.name.strip() if req.kind == "DRIVER" else friendly_name(req)
    return req.kind.upper(), name.lower()


def parse_overrides(text):
    """Parse `powercfg /requestsoverride` -> {(KIND, name_lower): {types}}.
    Accepts both `[KIND] name TYPE..` and a bare `[KIND]` header followed by
    `name TYPE..` lines. Best effort: entries are `name` + trailing request types."""
    out, kind = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^\[(\w+)\]\s*(.*)$", line)
        if m:
            kind, line = m.group(1).upper(), m.group(2).strip()
            if not line:
                continue
        if kind is None:
            continue
        toks = line.split()
        types = set()
        while toks and toks[-1].upper() in OVERRIDABLE:
            types.add(toks.pop().upper())
        if toks and types:
            out.setdefault((kind, " ".join(toks).lower()), set()).update(types)
    return out


def is_ignored(req, overrides):
    types = overrides.get(override_key(req), set())
    return req.category in types


@dataclass
class WakeTimer:
    owner: str
    detail: str


def parse_waketimers(text):
    """Entries are lines carrying a [PROCESS]/[SERVICE]/[DRIVER] tag (locale independent);
    the following indented line, if any, is the reason."""
    out = []
    lines = text.splitlines()
    for i, raw in enumerate(lines):
        m = re.search(r"\[(\w+)\]\s*(.+)", raw)
        if not m:
            continue
        body = m.group(2).strip()
        owner = re.split(r"\s+(?:expires|λήγει)\b", body)[0]
        detail = body
        if i + 1 < len(lines) and lines[i + 1][:1].isspace() and lines[i + 1].strip():
            detail += " | " + lines[i + 1].strip()
        out.append(WakeTimer(friendly_name(Request("", m.group(1), owner)), detail))
    return out


def parse_wake_devices(wake_armed_text, all_devices_text):
    """Device names from `/devicequery wake_armed`. The 'NONE' placeholder is
    localized, so keep only lines that are real devices in `all_devices`."""
    known = {l.strip().lower() for l in all_devices_text.splitlines() if l.strip()}
    return [l.strip() for l in wake_armed_text.splitlines()
            if l.strip() and l.strip().lower() in known]


@dataclass
class Timer:
    name: str
    timeout: int | None          # seconds; None/0 = never
    blocked_by: list = field(default_factory=list)

    def remaining(self, idle):
        if not self.timeout:
            return None
        return max(0, self.timeout - idle)


# ---------------------------------------------------------------- Windows ---
import json
import os
import time

_STORE = os.path.join(os.path.expanduser("~"), ".pc_awake.json")
_cache = {}


def _cached(key, ttl, fn):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def _invalidate():
    _cache.clear()


def _run(args):
    return subprocess.run(args, capture_output=True, text=True,
                          errors="replace", creationflags=0x08000000)


def is_admin():
    import ctypes
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def idle_seconds():
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO), 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
    now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
    return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0


def on_ac_power():
    import ctypes
    from ctypes import wintypes

    class SPS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte), ("SystemStatusFlag", ctypes.c_ubyte),
                    ("BatteryLifeTime", wintypes.DWORD), ("BatteryFullLifeTime", wintypes.DWORD)]

    s = SPS()
    ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s))
    return s.ACLineStatus != 0  # 0 = battery, 1 = AC, 255 = unknown (assume AC)


def screensaver_timeout():
    """Seconds until the screensaver starts, or None when disabled."""
    import ctypes
    spi = ctypes.windll.user32.SystemParametersInfoW
    active, secs = ctypes.c_int(0), ctypes.c_int(0)
    spi(16, 0, ctypes.byref(active), 0)   # SPI_GETSCREENSAVEACTIVE
    spi(14, 0, ctypes.byref(secs), 0)     # SPI_GETSCREENSAVETIMEOUT
    return secs.value if active.value and secs.value else None


def power_timeout(sub, setting, ac):
    out = _run(["powercfg", "/query", "SCHEME_CURRENT", sub, setting]).stdout
    pair = parse_power_indexes(out)
    if not pair:
        return None
    return (pair[0] if ac else pair[1]) or None


def read_requests():
    """Returns (requests, error). Error is set if powercfg needs admin rights."""
    out = _run(["powercfg", "/requests"]).stdout
    if not out.strip() or "administrator" in out.lower() and "[" not in out:
        return [], "Run as Administrator to see which processes block sleep."
    return parse_requests(out), None


def _load_store():
    try:
        with open(_STORE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"ignored": [], "disabled_wake": []}


def _save_store(d):
    try:
        with open(_STORE, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except OSError:
        pass


def read_overrides():
    """Windows' override list, plus what we applied ourselves (in case the
    list output isn't parseable on this Windows version/language)."""
    ov = parse_overrides(_run(["powercfg", "/requestsoverride"]).stdout)
    for kind, name, types in _load_store()["ignored"]:
        ov.setdefault((kind, name), set()).update(types)
    return ov


def set_ignored(req, ignore):
    """Make Windows ignore (or stop ignoring) a request. Needs admin."""
    kind, name = override_key(req)
    shown = req.name.strip() if req.kind == "DRIVER" else friendly_name(req)
    types = [req.category] if req.category in OVERRIDABLE else []
    if not types:
        return False, f"{req.category or 'This'} requests can't be overridden by Windows."
    for t in types:
        args = ["powercfg", "/requestsoverride", kind, shown] + ([t] if ignore else [])
        r = _run(args)
        if r.returncode != 0:
            return False, (r.stdout + r.stderr).strip() or "powercfg failed (run as Administrator)."
    store = _load_store()
    store["ignored"] = [e for e in store["ignored"] if (e[0], e[1]) != (kind, name)]
    if ignore:
        store["ignored"].append([kind, name, types])
    _save_store(store)
    _invalidate()
    return True, ""


def set_device_wake(device, allow):
    r = _run(["powercfg", "/deviceenablewake" if allow else "/devicedisablewake", device])
    if r.returncode != 0:
        return False, (r.stdout + r.stderr).strip() or "powercfg failed (run as Administrator)."
    _invalidate()
    return True, ""


def read_wake_timers():
    return parse_waketimers(_run(["powercfg", "/waketimers"]).stdout)


def read_wake_devices():
    armed = _run(["powercfg", "/devicequery", "wake_armed"]).stdout
    allv = _cached("all_devices", 3600,
                   lambda: _run(["powercfg", "/devicequery", "all_devices"]).stdout)
    return parse_wake_devices(armed, allv)


def snapshot():
    ac = on_ac_power()
    reqs, err = _cached("requests", 2, read_requests)
    overrides = _cached("overrides", 5, read_overrides)
    for r in reqs:
        r.ignored = is_ignored(r, overrides)
    active = [r for r in reqs if not r.ignored]
    display_block = [r for r in active if r.category == "DISPLAY"]
    system_block = [r for r in active if r.category in ("SYSTEM", "AWAYMODE")]
    timers = [
        Timer("Screensaver", screensaver_timeout(), display_block),
        Timer("Screen turns off", power_timeout(SUB_VIDEO, VIDEOIDLE, ac), display_block),
        Timer("PC sleeps", power_timeout(SUB_SLEEP, STANDBYIDLE, ac), system_block),
        Timer("PC hibernates", power_timeout(SUB_SLEEP, HIBERNATEIDLE, ac), system_block),
    ]
    return {"idle": idle_seconds(), "ac": ac, "timers": timers, "requests": reqs,
            "error": err, "admin": is_admin(),
            "wake_timers": _cached("waketimers", 5, read_wake_timers),
            "wake_devices": _cached("wakedevices", 10, read_wake_devices)}


if sys.platform != "win32":
    def snapshot():  # noqa: F811
        raise RuntimeError("PC awake monitor only runs on Windows.")
