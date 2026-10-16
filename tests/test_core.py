import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import core

SAMPLE = """DISPLAY:
[PROCESS] \\Device\\HarddiskVolume3\\Program Files\\VideoLAN\\VLC\\vlc.exe
Video Wake Lock

SYSTEM:
[DRIVER] Realtek USB Audio
An audio stream is currently in use.
[SERVICE] \\Device\\HarddiskVolume3\\Windows\\System32\\svchost.exe

AWAYMODE:
None.

EXECUTION:
None.
"""

QUERY = """  Power Setting GUID: 3c0bc021
    Possible Settings increment: 0x00000001
    Current AC Power Setting Index: 0x00000258
    Current DC Power Setting Index: 0x0000012c
"""

class T(unittest.TestCase):
    def test_requests(self):
        r = core.parse_requests(SAMPLE)
        self.assertEqual([(x.category, x.kind) for x in r],
                         [("DISPLAY", "PROCESS"), ("SYSTEM", "DRIVER"), ("SYSTEM", "SERVICE")])
        self.assertEqual(core.friendly_name(r[0]), "vlc.exe")
        self.assertEqual(r[0].reason, "Video Wake Lock")
    def test_indexes(self):
        self.assertEqual(core.parse_power_indexes(QUERY), (600, 300))
    def test_fmt(self):
        self.assertEqual(core.fmt_duration(3725), "1h 02m 05s")
        self.assertEqual(core.fmt_duration(None), "-")
    def test_timer(self):
        t = core.Timer("x", 300)
        self.assertEqual(t.remaining(100), 200)
        self.assertIsNone(core.Timer("x", None).remaining(5))

if __name__ == "__main__":
    unittest.main()


class T2(unittest.TestCase):
    def test_overrides(self):
        ov = core.parse_overrides("[PROCESS]\nvlc.exe DISPLAY SYSTEM\n[DRIVER] Xbox Wireless Adapter SYSTEM\n")
        self.assertEqual(ov[("PROCESS", "vlc.exe")], {"DISPLAY", "SYSTEM"})
        self.assertEqual(ov[("DRIVER", "xbox wireless adapter")], {"SYSTEM"})
        r = core.parse_requests("SYSTEM:\n[DRIVER] Xbox Wireless Adapter\n")[0]
        self.assertTrue(core.is_ignored(r, ov))
        self.assertFalse(core.is_ignored(core.Request("DISPLAY", "DRIVER", "Xbox Wireless Adapter"), ov))

    def test_waketimers(self):
        t = core.parse_waketimers(
            "Timer set by [SERVICE] \\Device\\X\\svchost.exe expires at 3:00:00 AM on 10/16/2026.\n"
            "  Reason: Windows will execute 'NT TASK\\Update' scheduled task.\n")
        self.assertEqual(t[0].owner, "svchost.exe")
        self.assertIn("Reason", t[0].detail)
        self.assertEqual(core.parse_waketimers("There are no active wake timers."), [])

    def test_wake_devices(self):
        allv = "Xbox Controller\nHID Keyboard Device\n"
        self.assertEqual(core.parse_wake_devices("HID Keyboard Device\n", allv), ["HID Keyboard Device"])
        self.assertEqual(core.parse_wake_devices("NONE\n", allv), [])


class T3(unittest.TestCase):
    def test_execution_does_not_block(self):
        self.assertFalse(core.blocks_idle(core.Request("EXECUTION", "PROCESS", "claude.exe")))
        self.assertTrue(core.blocks_idle(core.Request("SYSTEM", "DRIVER", "Xbox")))


class T4(unittest.TestCase):
    def test_launch_command(self):
        import autostart
        self.assertEqual(
            autostart.launch_command(True, frozen=True, executable=r"C:\a\PCAwakeMonitor.exe"),
            (r"C:\a\PCAwakeMonitor.exe", "--minimized", "C:\\a" if os.sep == "\\" else ""))
        cmd, args, _ = autostart.launch_command(False, frozen=False, executable="/py/python",
                                                script="/x/monitor.py")
        self.assertEqual((cmd, args), ("/py/python", '"/x/monitor.py"'))
        self.assertTrue(autostart.launch_command(True, frozen=False, executable="/py/python",
                                                 script="/x/monitor.py")[1].endswith("--minimized"))

    def test_task_xml(self):
        import autostart
        from xml.etree import ElementTree as ET
        x = autostart.task_xml("PC\\me", "C:\\Program Files\\a&b.exe", '"m.py" --minimized', "C:\\w")
        root = ET.fromstring(x.replace('encoding="UTF-16"', ""))
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        self.assertEqual(root.find(".//t:Command", ns).text, "C:\\Program Files\\a&b.exe")
        self.assertEqual(root.find(".//t:RunLevel", ns).text, "HighestAvailable")
        self.assertEqual(root.find(".//t:DisallowStartIfOnBatteries", ns).text, "false")
