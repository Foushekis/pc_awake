"""PC awake monitor: what keeps your PC awake, and how long until it idles off.

    python monitor.py          # GUI
    python monitor.py --cli    # live console view
"""
import ctypes
import sys
import time

import core


def rid(r):
    """Stable row id: survives re-reads of powercfg so the selection isn't lost."""
    return f"{r.kind}|{r.category}|{r.name}"


def blockers_text(reqs):
    return ", ".join(sorted({core.friendly_name(r) for r in reqs}))


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
        print("\nKeeping the PC awake:")
        if s["error"]:
            print("  " + s["error"])
        for r in s["requests"]:
            tag = " (ignored)" if r.ignored else ("" if core.blocks_idle(r) else " (does not block sleep)")
            print(f"  [{r.category}] {core.friendly_name(r)} ({r.kind}){tag}  {r.reason}")
        if not s["requests"] and not s["error"]:
            print("  nothing")
        print("\nWake timers (can wake the PC from sleep):")
        for w in s["wake_timers"] or []:
            print("  " + w.detail)
        if not s["wake_timers"]:
            print("  none")
        print("\nDevices allowed to wake the PC:")
        for d in s["wake_devices"] or []:
            print("  " + d)
        if not s["wake_devices"]:
            print("  none")
        time.sleep(1)


def run_gui():
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title("PC Awake Monitor")
    root.geometry("760x640")

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
        lab = ttk.Label(frame, width=40)
        lab.grid(row=i, column=2, sticky="w", padx=6)
        rows[name] = (bar, lab)

    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=12, pady=6)

    def make_tab(title, cols, widths, button_row):
        tab = ttk.Frame(nb)
        nb.add(tab, text=title)
        tree = ttk.Treeview(tab, columns=cols, show="headings", height=7)
        for c, w in zip(cols, widths):
            tree.heading(c, text=c)
            tree.column(c, width=w)
        tree.pack(fill="both", expand=True, pady=(4, 2))
        bar = ttk.Frame(tab)
        bar.pack(fill="x")
        return tree, bar

    req_tree, req_bar = make_tab("Keeping awake", ("Process", "Type", "Kind", "Status", "Reason"),
                                 (160, 90, 70, 80, 280), True)
    timer_tree, _ = make_tab("Wake timers", ("Owner", "Details"), (180, 500), False)
    dev_tree, dev_bar = make_tab("Devices that can wake PC", ("Device",), (680,), True)

    note = ttk.Label(root, foreground="#b00020", wraplength=720)
    note.pack(anchor="w", padx=12, pady=(0, 4))
    latest = {"s": None}

    def selected_request():
        sel = req_tree.selection()
        if not sel:
            return None
        return next((r for r in latest["s"]["requests"] if rid(r) == sel[0]), None)

    def toggle_ignore(ignore):
        r = selected_request()
        if not r:
            return
        if ignore and not messagebox.askyesno(
                "Ignore request",
                f"Tell Windows to ignore {core.friendly_name(r)}'s {r.category} request?\n\n"
                "This is a system setting (powercfg /requestsoverride) that persists until "
                "you click 'Stop ignoring'."):
            return
        ok, msg = core.set_ignored(r, ignore)
        note.config(text="" if ok else msg)

    def toggle_wake(allow):
        sel = dev_tree.selection()
        if not sel:
            return
        dev = dev_tree.item(sel[0], "values")[0]
        if not allow and not messagebox.askyesno(
                "Disable wake", f"Stop '{dev}' from waking the PC?\n\n"
                "Undo later with powercfg /deviceenablewake."):
            return
        ok, msg = core.set_device_wake(dev, allow)
        note.config(text="" if ok else msg)

    ttk.Button(req_bar, text="Ignore selected (Windows override)",
               command=lambda: toggle_ignore(True)).pack(side="left", padx=2, pady=4)
    ttk.Button(req_bar, text="Stop ignoring",
               command=lambda: toggle_ignore(False)).pack(side="left", padx=2)
    ttk.Button(dev_bar, text="Disable wake for selected",
               command=lambda: toggle_wake(False)).pack(side="left", padx=2, pady=4)

    def elevate():
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable,
                                            f'"{__file__}"', None, 1)
        root.destroy()

    ttk.Button(root, text="Relaunch as Administrator", command=elevate).pack(pady=(0, 10))
    sigs = {}

    def refill(tree, key, items):
        if sigs.get(key) == [i[0] for i in items]:
            return
        sigs[key] = [i[0] for i in items]
        tree.delete(*tree.get_children())
        for iid, vals in items:
            tree.insert("", "end", iid=iid, values=vals)

    def tick():
        s = core.snapshot()
        latest["s"] = s
        head.config(text=f"Inactive for {core.fmt_duration(s['idle'])}")
        sub.config(text="Plugged in (AC settings)" if s["ac"] else "On battery (DC settings)")
        for t in s["timers"]:
            bar, lab = rows[t.name]
            if not t.timeout:
                bar["value"] = 0
                lab.config(text="disabled / never")
                continue
            bar["value"] = 100 * min(s["idle"], t.timeout) / t.timeout
            txt = f"{core.fmt_duration(t.remaining(s['idle']))} left (of {core.fmt_duration(t.timeout)})"
            if t.blocked_by:
                txt = "BLOCKED by " + blockers_text(t.blocked_by)
            lab.config(text=txt)
        refill(req_tree, "req", [
            (rid(r), (core.friendly_name(r), r.category, r.kind,
             "ignored" if r.ignored else ("ACTIVE" if core.blocks_idle(r) else "harmless"),
             r.reason or core.REQUEST_BLOCKS.get(r.category, ""))) for r in s["requests"]])
        refill(timer_tree, "wt", [(f"w{i}", (w.owner, w.detail)) for i, w in enumerate(s["wake_timers"])])
        refill(dev_tree, "dev", [(f"d{i}", (d,)) for i, d in enumerate(s["wake_devices"])])
        note.config(text=s["error"] or "")
        root.after(1000, tick)

    tick()
    root.mainloop()


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("This app only runs on Windows.")
    run_cli() if "--cli" in sys.argv else run_gui()
