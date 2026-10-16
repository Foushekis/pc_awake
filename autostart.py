"""Start-with-Windows support.

With admin rights we register a Scheduled Task that runs at logon with the
highest privileges (a plain Run-key entry can't start an elevated app, and the
full process list needs elevation). Without admin we fall back to the HKCU Run
key, which starts the app un-elevated (limited process list).
"""
import os
import subprocess
import sys
import tempfile
from xml.sax.saxutils import escape

import core

TASK = "PCAwakeMonitor"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_NOWINDOW = 0x08000000


def launch_command(minimized, frozen=None, executable=None, script=None):
    """Returns (command, arguments, working_dir) for the autostart entry."""
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    executable = executable or sys.executable
    flag = " --minimized" if minimized else ""
    if frozen:
        return executable, flag.strip(), os.path.dirname(executable)
    script = script or os.path.abspath(os.path.join(os.path.dirname(__file__), "monitor.py"))
    pyw = os.path.join(os.path.dirname(executable), "pythonw.exe")  # no console window
    if os.path.exists(pyw):
        executable = pyw
    return executable, f'"{script}"{flag}', os.path.dirname(script)


def task_xml(user, command, arguments, workdir):
    e = escape
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled><UserId>{e(user)}</UserId><Delay>PT15S</Delay></LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><UserId>{e(user)}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec><Command>{e(command)}</Command><Arguments>{e(arguments)}</Arguments><WorkingDirectory>{e(workdir)}</WorkingDirectory></Exec>
  </Actions>
</Task>
"""


def _user():
    name, dom = os.environ.get("USERNAME", ""), os.environ.get("USERDOMAIN", "")
    return f"{dom}\\{name}" if dom else name


def _schtasks(*args):
    return subprocess.run(["schtasks", *args], capture_output=True, text=True,
                          errors="replace", creationflags=_NOWINDOW)


def _run_key_value():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return winreg.QueryValueEx(k, TASK)[0]
    except OSError:
        return None


def is_enabled():
    if sys.platform != "win32":
        return False
    return _schtasks("/query", "/tn", TASK).returncode == 0 or _run_key_value() is not None


def _remove_run_key():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, TASK)
    except OSError:
        pass


def enable(minimized):
    """Returns (ok, message)."""
    cmd, args, wd = launch_command(minimized)
    if core.is_admin():
        path = os.path.join(tempfile.gettempdir(), "pc_awake_task.xml")
        try:
            with open(path, "w", encoding="utf-16") as f:
                f.write(task_xml(_user(), cmd, args, wd))
            r = _schtasks("/create", "/tn", TASK, "/xml", path, "/f")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if r.returncode != 0:
            return False, (r.stdout + r.stderr).strip() or "Could not create the scheduled task."
        _remove_run_key()
        return True, ""
    import winreg
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, TASK, 0, winreg.REG_SZ, f'"{cmd}" {args}'.strip())
    except OSError as ex:
        return False, str(ex)
    return True, ("Enabled without Administrator rights: it will start with a limited "
                  "process list. Run as Administrator and re-enable for full access.")


def disable():
    """Returns (ok, message)."""
    _remove_run_key()
    if _schtasks("/query", "/tn", TASK).returncode == 0:
        r = _schtasks("/delete", "/tn", TASK, "/f")
        if r.returncode != 0:
            return False, "Run as Administrator to remove the startup task."
    return True, ""
