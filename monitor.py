"""PC awake monitor: what keeps your PC awake, and how long until it idles off.

    python monitor.py          # GUI
    python monitor.py --cli    # live console view
"""
import ctypes
import sys
import time

import core


def blockers_text(reqs):
    names = sorted({core.friendly_name(r) for r in reqs})
    return ", ".join(names)


def run_cli():
    while True:
        s = core.snapshot()
        print("\033[2J\033[H", end="")
        print(f"Idle for {core.fmt_duration(s['idle'])}   "
              f"({'plugged in' if s['ac'] else 'on battery'})\n")
        for t in s["timers"]:
            left = core.fmt_duration(t.remaining(s["idle"])) if t.timeout else "never"
            note = f"  BLOCKED by {blockers_text(t.blocked_by)}" if t.blocked_by and t.timeout else ""
            print(f"{t.name:<18} after {core.fmt_duration(t.timeout):<10} in {left}{note}")
        print("\nWhat is keeping the PC awake:")
        if s["error"]:
            print("  " + s["error"])
        for r in s["requests"]:
            print(f"  [{r.category}] {core.friendly_name(r)} ({r.kind})  {r.reason}")
        if not s["requests"] and not s["error"]:
            print("  nothing")
        time.sleep(1)


def run_gui():
    import tkinter as tk
    from tkinter import ttk

    root = tk.Tk()
    root.title("PC Awake Monitor")
    root.geometry("720x520")

    head = ttk.Label(root, font=("Segoe UI", 16, "bold"))
    head.pack(anchor="w", padx=12, pady=(12, 0))
    sub = ttk.Label(root)
    sub.pack(anchor="w", padx=12)

    frame = ttk.LabelFrame(root, text="Time until...")
    frame.pack(fill="x", padx=12, pady=10)
    rows = {}
    for i, name in enumerate(["Screensaver", "Screen turns off", "PC sleeps", "PC hibernates"]):
        ttk.Label(frame, text=name, width=18).grid(row=i, column=0, sticky="w", padx=6, pady=3)
        bar = ttk.Progressbar(frame, length=220, maximum=100)
        bar.grid(row=i, column=1, padx=6)
        lab = ttk.Label(frame, width=34)
        lab.grid(row=i, column=2, sticky="w", padx=6)
        rows[name] = (bar, lab)

    ttk.Label(root, text="Keeping the PC awake right now",
              font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12)
    cols = ("process", "category", "kind", "reason")
    tree = ttk.Treeview(root, columns=cols, show="headings", height=8)
    for c, w in zip(cols, (180, 110, 80, 300)):
        tree.heading(c, text=c.capitalize())
        tree.column(c, width=w)
    tree.pack(fill="both", expand=True, padx=12, pady=6)
    note = ttk.Label(root, foreground="#b00020", wraplength=680)
    note.pack(anchor="w", padx=12, pady=(0, 4))

    def elevate():
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, f'"{__file__}"', None, 1)
        root.destroy()

    state = {"reqs": 0}

    def tick():
        s = core.snapshot()
        head.config(text=f"Inactive for {core.fmt_duration(s['idle'])}")
        sub.config(text="Plugged in (AC settings)" if s["ac"] else "On battery (DC settings)")
        for t in s["timers"]:
            bar, lab = rows[t.name]
            if not t.timeout:
                bar["value"] = 0
                lab.config(text="disabled / never")
                continue
            left = t.remaining(s["idle"])
            bar["value"] = 100 * min(s["idle"], t.timeout) / t.timeout
            txt = f"{core.fmt_duration(left)} left (of {core.fmt_duration(t.timeout)})"
            if t.blocked_by:
                txt = "BLOCKED by " + blockers_text(t.blocked_by)
            lab.config(text=txt)
        sig = [(r.category, r.name) for r in s["requests"]]
        if sig != state["reqs"]:
            state["reqs"] = sig
            tree.delete(*tree.get_children())
            for r in s["requests"]:
                tree.insert("", "end", values=(core.friendly_name(r), r.category, r.kind,
                                               r.reason or core.REQUEST_BLOCKS.get(r.category, "")))
        note.config(text=s["error"] or "")
        root.after(1000, tick)

    ttk.Button(root, text="Relaunch as Administrator", command=elevate).pack(pady=(0, 10))
    tick()
    root.mainloop()


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("This app only runs on Windows.")
    run_cli() if "--cli" in sys.argv else run_gui()
