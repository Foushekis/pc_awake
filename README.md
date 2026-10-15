# PC Awake Monitor (Windows)

Shows, live:
- how long the PC has been inactive (no keyboard/mouse input)
- time left until the **screensaver**, **screen off**, **sleep** and **hibernate**
  (uses your current power plan, AC or battery as appropriate)
- which **processes/drivers/services** are keeping the screen or system awake
  (`powercfg /requests`), and which timers they are blocking

Run (Python 3.10+, no dependencies):

    python monitor.py          # window
    python monitor.py --cli    # console

`powercfg /requests` needs Administrator rights; use the "Relaunch as
Administrator" button, otherwise the process list is empty.

Tests (any OS): `python -m unittest discover tests`
