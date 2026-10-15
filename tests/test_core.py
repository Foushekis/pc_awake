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
