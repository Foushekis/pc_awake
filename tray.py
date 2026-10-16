"""System-tray icon (optional: needs `pip install pystray pillow`)."""
try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:  # app still works; "minimized" falls back to the taskbar
    pystray = None

OK, ALERT = "#2e7d32", "#ef6c00"


def _image(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=color)
    d.arc((18, 18, 46, 46), start=300, end=240, fill="white", width=5)  # power symbol
    d.line((32, 14, 32, 32), fill="white", width=5)
    return img


class Tray:
    available = pystray is not None

    def __init__(self, events):
        """`events` is a queue.Queue; menu clicks put 'show' / 'quit' on it."""
        self.alert = False
        self.icon = None
        self.events = events

    def start(self):
        menu = pystray.Menu(
            pystray.MenuItem("Open", lambda: self.events.put("show"), default=True),
            pystray.MenuItem("Quit", lambda: self.events.put("quit")))
        self.icon = pystray.Icon("pc_awake", _image(OK), "PC Awake Monitor", menu)
        self.icon.run_detached()

    def update(self, tooltip, alert):
        if not self.icon:
            return
        self.icon.title = tooltip[:120]  # Windows caps tooltips at 127 chars
        if alert != self.alert:
            self.alert = alert
            self.icon.icon = _image(ALERT if alert else OK)

    def stop(self):
        if self.icon:
            self.icon.stop()
            self.icon = None
