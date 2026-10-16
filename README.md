# PC Awake Monitor (Windows)

Shows, live:
- how long the PC has been inactive (no keyboard/mouse input)
- time left until the **screensaver**, **screen off**, **sleep** and **hibernate**
  (uses your current power plan, AC or battery as appropriate)
- which **processes/drivers/services** are keeping the screen or system awake
  (`powercfg /requests`), and which timers they are blocking

- **wake timers** (`powercfg /waketimers`) and **devices allowed to wake the PC**
  (`powercfg /devicequery wake_armed`) - e.g. an Xbox controller
- **ignore switch:** select a blocker and click *Ignore selected* to make Windows
  ignore it (`powercfg /requestsoverride`, persistent, undo with *Stop ignoring*);
  select a wake device and click *Disable wake* (`powercfg /devicedisablewake`).
  These change system settings and need Administrator.

Run (Python 3.10+; optional `pip install -r requirements.txt` adds the system-tray icon):

    python monitor.py          # window
    python monitor.py --cli    # console

`powercfg /requests` needs Administrator rights; use the "Relaunch as
Administrator" button, otherwise the process list is empty.

Tests (any OS): `python -m unittest discover tests`

## Build an .exe

Double-click `build.bat` (or run it in a terminal). It produces
`dist\PCAwakeMonitor.exe`, a single file with no Python needed to run it. The exe
asks for Administrator rights on launch, so the full process list works.
The `--cli` mode needs the plain `python monitor.py --cli`, not the exe.

## Start with Windows

At the bottom of the window: tick **Launch automatically at login**, and choose
**Show window** or **Minimized to tray**.
- With Administrator rights it registers a Scheduled Task (runs elevated at login,
  no UAC prompt, not stopped on battery). Without admin it falls back to a
  Run-key entry that starts un-elevated, with a limited process list.
- Tray mode: closing the window hides it to the tray (green icon = nothing blocking,
  orange = something is keeping the PC awake). Right-click the icon -> Quit.
  Without `pystray`/`pillow` installed, "minimized" uses the taskbar instead.
- Untick the box to remove it again (removing the task also needs admin).
