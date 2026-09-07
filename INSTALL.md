# Installing webOS Companion on Linux

This guide is written for someone who has **not** installed a Linux application
from source before. Every command is meant to be copy‑pasted into a terminal
(on KDE that's **Konsole**; on GNOME, **Terminal** — or press `Ctrl`+`Alt`+`T`).

> **Tested on:** KDE Plasma 6 / Wayland. It *should* work on any **systemd +
> Wayland** desktop (GNOME, etc.) and any distro with **Python ≥ 3.11** — those
> haven't been tested on real hardware yet, so if you try one, please open an
> issue with how it went. X11-only sessions are not supported.

---

## What it does

It makes an LG WebOS TV behave like a normal PC monitor:

| When your desktop… | …the TV does |
| --- | --- |
| turns the screen off to save power (idle blank) | blanks the panel, but stays on and on the network — instant wake |
| goes to **sleep / suspend** | fully powers off |
| **wakes up** | Wake‑on‑LAN + turns back on |
| **shuts down / reboots** | fully powers off |

It runs quietly in the background as a service. It does **not** need root.

---

## What you need before starting

1. **The TV and this PC on the same network**, and ideally the TV on a fixed IP
   (set a "DHCP reservation" / "static lease" for it in your router — ask your
   router's manual how; it's optional but stops things breaking if the TV's IP
   changes).

2. **The TV's IP address and MAC address.** On the TV:
   `Settings (gear button) → All Settings → Connection` (or `Network`) →
   `Wi‑Fi Connection` or `Wired Connection (Ethernet)` → `Advanced Wi‑Fi Settings`
   (or `Advanced`). Write down **IP Address** and **MAC Address**.
   (You can also read them from your router's list of connected devices.)

3. **Two TV settings turned on** (needed so the TV can be woken over the network —
   this is true even on a wired connection). Menu paths vary by model year:
   - **"Turn on via Wi‑Fi"** (a.k.a. *TV On With Mobile*):
     - 2021+ (C1/C2/C3/C4): `All Settings → General → Devices → External Devices → TV On With Mobile → Turn on via Wi‑Fi` → **On**
     - CX: `All Settings → Connection → Mobile Connection Management → TV On with Mobile → Turn On via Wi‑Fi` → **On**
   - **"Quick Start+"** (newer models call it **"Always Ready"**):
     `All Settings → General → Devices → Quick Start+` → **On**
   - Also worth doing: set the TV's own **Auto Power Off** to a long time or Off so
     it doesn't fight the app (`All Settings → General → OLED Care → Device Self Care
     → Energy Saving → Auto Power Off`).

   (These TV-setup steps are adapted from the upstream
   [LGTV Companion](https://github.com/JPersson77/LGTVCompanion) README.)

---

## Step 1 — Install Python and pipx

You need **Python 3.11 or newer** (most distros from ~2023 on) and **pipx**, which
installs Python apps in their own isolated folder so they can't disturb the rest
of your system. Pick your distro:

| Distro | Command |
| --- | --- |
| **Arch / CachyOS / Manjaro / EndeavourOS** | `sudo pacman -S --needed python python-pipx` |
| **Fedora** | `sudo dnf install pipx` |
| **Debian 12+ / Ubuntu 23.10+ / Mint 22+** | `sudo apt install pipx` |
| **openSUSE** | `sudo zypper install python3-pipx` |
| **anything else** | check `python3 --version` is ≥ 3.11, then `python3 -m pip install --user pipx` |

You also need **git** (`pacman -S git` / `dnf install git` / `apt install git` /
`zypper install git`) — the install in Step 2 fetches from GitHub.

> **Ubuntu 22.04** ships Python 3.10 — too old. Use 24.04+ or another distro.

Then let pipx set up your `PATH` so the command works everywhere:

```bash
pipx ensurepath
```

**Close the terminal and open a new one** for that to take effect.

> You do **not** install `websockets` / `dbus-fast` / `pyyaml` yourself — pipx
> pulls them into the app's private folder in Step 2.

---

## Step 2 — Install webOS Companion

```bash
pipx install git+https://github.com/jayge91/webos-companion
```

Check it worked:

```bash
webos-companion --version
```

You should see `webos-companion 0.1.0`. If you get `command not found`, see
[Troubleshooting](#troubleshooting).

---

## Step 3 — Run the setup wizard

Make sure the **TV is on**, then run:

```bash
webos-companion setup
```

It walks you through everything:

1. **Scans the network and lists the LG TVs it found** — IP, MAC, the name you set
   on the TV, and (on 2019+ models) the model number:
   ```
   Found 2 device(s):

     1) 192.168.1.42   80:5b:65:a1:b2:c3  Living Room OLED  [OLED42C2PUA]  (LG webOS TV)
     2) 192.168.1.43   b0:37:95:d4:e5:f6  Bedroom TV        [OLED65C1PUB]  (LG webOS TV)

   Choose a number, or type the TV's IP address [1]:
   ```
   Type the number of your TV (match it by name, model, or the MAC address you
   noted in "What you need"), or type its IP directly. If nothing was found, it
   just asks for the IP.
2. **Fills in the MAC address** from the device you picked — press Enter to accept.
3. **Detects which HDMI port** the TV is on — press Enter to accept.
4. Writes the config file for you at `~/.config/webos-companion/config.yaml`.
5. **Pairs with the TV** — a permission prompt may appear *on the TV screen*;
   accept it with the remote. (If the TV has trusted this PC before, it just
   connects with no prompt.)
6. Offers to **install and start the background service** — say yes.

For most people that's picking their TV from the list, pressing Enter a couple of
times, accepting the prompt on the TV if it shows, and typing `y` at the end.

> `webos-companion discover` runs just the scan on its own if you want to see what's
> on the network.

When it finishes, check everything is talking:

```bash
webos-companion status
```

Expected:

```
paired:     yes
connector:  card1-HDMI-A-1  dpms=On
tv power:   Active
service:    active (enabled) — /home/you/.config/systemd/user/webos-companion.service
```

---

## Step 4 — Quick test

```bash
webos-companion off      # the TV panel should go black within a second
webos-companion on       # and come back
```

Then watch it react to real events (turn your screen off, suspend the PC, …):

```bash
journalctl --user -u webos-companion -f
```

Press `Ctrl`+`C` to stop watching (the service keeps running).

That's it — it now runs automatically every time you log in.

---

### Doing it by hand instead

If you'd rather not use the wizard:

- **Config file** — create `~/.config/webos-companion/config.yaml`:
  ```yaml
  ip: "192.168.1.42"        # your TV's IP address        (required)
  mac: "80:5b:65:a1:b2:c3"  # your TV's MAC address        (required, for wake-on-LAN)
  connector: ""             # "" = auto-detect the LG panel; or e.g. "HDMI-A-1"
  ssl: true                 # secure port 3001 (leave true for modern TVs)
  poll_interval: 2.0        # seconds between display-power checks
  screensaver_dbus: false   # true = also react to screen lock (usually not wanted)
  wol_broadcast: "255.255.255.255"
  ```
- **Pair** — `webos-companion pair` (accept the prompt on the TV if it shows one)
- **Install the service** — `webos-companion service install`
  (remove it later with `webos-companion service remove`)

---

## Everyday use

| Task | Command |
| --- | --- |
| Check status | `systemctl --user status webos-companion` |
| See recent logs | `journalctl --user -u webos-companion -n 50` |
| Follow logs live | `journalctl --user -u webos-companion -f` |
| Restart it | `systemctl --user restart webos-companion` |
| Stop it (until next login) | `systemctl --user stop webos-companion` |
| Stop it permanently | `webos-companion service remove` |
| Everything at a glance | `webos-companion status` |
| Manual TV control | `webos-companion on` / `webos-companion off` |
| Scan for TVs | `webos-companion discover` |
| One-off diagnostics | `webos-companion probe` |

---

## Updating

```bash
pipx upgrade webos-companion
systemctl --user restart webos-companion
```

If the systemd unit itself changed (rare — check the release notes), also run
`webos-companion service install` again to refresh it.

---

## Uninstalling

```bash
webos-companion service remove
pipx uninstall webos-companion
rm -rf ~/.config/webos-companion ~/.local/state/webos-companion
```

That removes everything. It never installed anything system-wide or as root.

---

## Troubleshooting

**`webos-companion: command not found`**
Run `pipx ensurepath`, then close and reopen the terminal. Still missing? Run
`~/.local/bin/webos-companion --version` — if *that* works, your `PATH` isn't
picking up `~/.local/bin`; log out and back in.

**Pairing fails or hangs** (`Pairing failed: …`)
The TV isn't reachable. Check the `ip` matches the TV, the TV is on, and this PC
and the TV are on the same network: `ping 192.168.1.42` (use your TV's IP) should
get replies. (A successful pair with *no* prompt on the TV is normal if it has
trusted this PC before.)

**`webos-companion status` says `tv power: unreachable`**
Same as above — network/IP problem, or the TV is fully off. Turn the TV on and
retry.

**After the PC resumes from sleep, the TV doesn't come back on**
- Re-check the two TV settings in "What you need" (**Turn on via Wi‑Fi** and
  **Quick Start+ / Always Ready**). Without them the TV ignores Wake-on-LAN.
- Watch `journalctl --user -u webos-companion -f` right after waking. You should
  see `system resumed -> bringing the TV back on`, then (if the network is still
  coming up) `waiting for the network`, then `sending Wake-on-LAN`, then
  `TV recovered -> state ON` within a minute. If it logs
  `gave up bringing the TV back`, the TV isn't accepting Wake-on-LAN.

**The service won't start**
```bash
systemctl --user status webos-companion
journalctl --user -u webos-companion -e
```
A `config error` line means `~/.config/webos-companion/config.yaml` is missing or
has no `ip`.

**The TV doesn't blank when my screen turns off (but does on lock)**
Turn your screen off and back on, then look at the log:
`journalctl --user -u webos-companion -n 20`. If you **don't** see a
`display blanked -> turning the TV screen off` line, your compositor isn't
updating the state file this relies on — set `screensaver_dbus: true` in
`~/.config/webos-companion/config.yaml` and `systemctl --user restart
webos-companion` to use the fallback path instead.

**Messages about `network unreachable` / `waiting for the network` right after resume**
Normal. The Wi‑Fi/Ethernet takes a few seconds to come back after waking; the app
waits for it and then retries. Nothing to do.

---

## What happens on each event (reference)

| Event | Action | TV comes back by |
| --- | --- | --- |
| Desktop blanks the screen (idle) | `turnOffScreen` | itself, when the desktop un-blanks (instant) |
| PC suspends / sleeps | `system/turnOff` | Wake-on-LAN on resume |
| PC shuts down / reboots | `system/turnOff` | you turning it on, or next boot |
| Screen lock (Meta+L) | *nothing*, unless `screensaver_dbus: true` | — |
