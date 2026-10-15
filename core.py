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
    "EXECUTION": "app keeps running during sleep / delays sleep",
    "PERFBOOST": "performance boost",
    "ACTIVELOCKSCREEN": "lock screen",
}


@dataclass
class Request:
    category: str
    kind: str   # PROCESS / DRIVER / SERVICE
    name: str
    reason: str = ""


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
def _run(args):
    return subprocess.run(args, capture_output=True, text=True,
                          errors="replace", creationflags=0x08000000).stdout


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
    out = _run(["powercfg", "/query", "SCHEME_CURRENT", sub, setting])
    pair = parse_power_indexes(out)
    if not pair:
        return None
    return (pair[0] if ac else pair[1]) or None


def read_requests():
    """Returns (requests, error). Error is set if powercfg needs admin rights."""
    out = _run(["powercfg", "/requests"])
    if not out.strip() or "administrator" in out.lower() and "[" not in out:
        return [], "Run as Administrator to see which processes block sleep."
    return parse_requests(out), None


def snapshot():
    ac = on_ac_power()
    reqs, err = read_requests()
    cats = {r.category for r in reqs}
    display_block = [r for r in reqs if r.category == "DISPLAY"]
    system_block = [r for r in reqs if r.category in ("SYSTEM", "EXECUTION", "AWAYMODE")]
    timers = [
        Timer("Screensaver", screensaver_timeout(), display_block),
        Timer("Screen turns off", power_timeout(SUB_VIDEO, VIDEOIDLE, ac), display_block),
        Timer("PC sleeps", power_timeout(SUB_SLEEP, STANDBYIDLE, ac), system_block),
        Timer("PC hibernates", power_timeout(SUB_SLEEP, HIBERNATEIDLE, ac), system_block),
    ]
    return {"idle": idle_seconds(), "ac": ac, "timers": timers,
            "requests": reqs, "error": err}


if sys.platform != "win32":
    def snapshot():  # noqa: F811
        raise RuntimeError("PC awake monitor only runs on Windows.")
