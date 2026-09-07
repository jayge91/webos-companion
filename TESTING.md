# Testing

Three tiers, by what has to be real. All of it runs from throwaway Docker
containers (plus, for tier 3b, qemu inside a container) — nothing is installed on
the host.

| Tier | Script | What it proves |
| --- | --- | --- |
| 0 | `./test-install.sh` | the **INSTALL.md** end-user path (`pipx install git+URL` + CLI) on 5 distros, from the *published* repo |
| 1 | `./test-distros.sh` | builds + the full unit suite on 6 distros, from a local checkout |
| 2 | `./test-integration.sh <distro> [cmd]` | the daemon's real D-Bus / DRM / TV paths, using another distro's Python stack against **this** host |
| 3a | *(notes below)* | which screen-off trigger a given compositor supports |
| 3b | `./test-vm.sh` | does `/sys/class/drm/*/dpms` flip under a non-KWin Wayland compositor |

---

## Tier 0 — the documented install path

```sh
./test-install.sh                 # all 5 distros, from github.com/jayge91/webos-companion
./test-install.sh fedora          # one
REPO=git+https://github.com/you/webos-companion@wip ./test-install.sh   # a branch
```

Each container runs *exactly* what INSTALL.md Step 1–3 tells a user to run — the
distro's `pipx` + `git` packages, then `pipx install <REPO>` — and checks the
`webos-companion` entry point resolves (`--version`, `--help`), that `setup`
exits cleanly with "interactive" when there's no TTY, and that `status` runs.
No pairing, no TV. This is the "does a stranger's `pipx install` line work"
check; Tier 1 covers the build from a local tree.

| Distro | Python | `pipx` pkg | Result |
| --- | --- | --- | --- |
| Arch (`archlinux:base`) | 3.14 | `python-pipx` | **PASS** |
| Debian 12 | 3.11 | `pipx` | **PASS** |
| Ubuntu 24.04 | 3.12 | `pipx` | **PASS** |
| Fedora 41 | 3.13 | `pipx` | **PASS** |
| openSUSE Tumbleweed | 3.13 | `python3-pipx` | **PASS** |

---

## Tier 1 — build / deps / unit tests

```sh
./test-distros.sh              # all 6, in parallel (~3 min)
./test-distros.sh fedora       # one
./test-distros.sh -v ubuntu    # stream a failing distro's full log
```

Each distro container: installs `python3` + `pipx` the distro's way, runs
`pytest` (under `dbus-run-session`, so the logind/screensaver tests run too),
then a `pipx install` smoke test.

| Distro | Python | Result |
| --- | --- | --- |
| Arch (`archlinux:base`) | 3.14 | **PASS** — 83 |
| Debian 12 | 3.11 | **PASS** — 83 |
| Ubuntu 24.04 | 3.12 | **PASS** — 83 |
| Fedora 41 | 3.13 | **PASS** — 83 |
| openSUSE Tumbleweed | 3.13 | **PASS** — 83 |
| Ubuntu 22.04 | 3.10 | **xfail** — below the `requires-python = ">=3.11"` floor, no apt `pipx` (doesn't count against the run) |

All five supported distros run the *entire* suite, including the D-Bus tests.

**Python 3.11 is the floor.** Dropping to 3.10 would only need guarding the one
`tomllib` import (legacy `config.toml` migration); not done — 3.11 covers every
current non-LTS-frozen distro.

If you set `$APT_PROXY` (e.g. to a LAN **apt-cacher-ng**), the Debian/Ubuntu
builds route apt through it; it's auto-skipped when unset or unreachable.

---

## Tier 2 — real integration, other distro's userspace vs *this* host

```sh
./test-integration.sh debian discover        # scan the real network
./test-integration.sh fedora probe           # real logind + KDE ScreenSaver + TV
./test-integration.sh ubuntu 'run --dry-run -v --seconds 20'
```

The container shares the host network namespace and bind-mounts `/sys` + the
D-Bus sockets **read-only**; it runs as your uid, holds no logind inhibitor
(dry-run is passive), and never sends a power command. Delete the images with
`docker rmi wc-int-<distro>`.

**Result:** Debian 12, Ubuntu 24.04, Fedora 41, openSUSE TW each connect to the
real `org.freedesktop.login1` (system bus) and `org.freedesktop.ScreenSaver`
(session bus), read `/sys/class/drm`, and complete full TV discovery
(SSDP + port probe + TLS-cert check + AirPlay model/name) — i.e. every distro's
`dbus-fast` / `websockets` / `pyyaml` works against the live system.

---

## Tier 3a — compositor screen-off triggers

The daemon has two ways to learn the screen went off:

1. **Primary — DRM poll:** `/sys/class/drm/<conn>/dpms` flips `On`→`Off` when the
   compositor disables the connector. This is kernel atomic-KMS behaviour
   (`drm_atomic_helper_update_legacy_modeset_state()` syncs the legacy property),
   not compositor-specific. Verified working on **amdgpu under KWin** (see the
   host checklist in [INSTALL.md] / the daemon's own logs).
2. **Fallback — `screensaver_dbus: true`:** react to
   `org.freedesktop.ScreenSaver.ActiveChanged` on the session bus.

Per compositor:

| Compositor | `org.freedesktop.ScreenSaver`? | Notes |
| --- | --- | --- |
| **KWin** (KDE) | yes | both paths work; DRM poll is the default (doesn't fire on a bare lock) |
| **GNOME / Mutter** | yes — gnome-shell registers it and emits `ActiveChanged` | fallback works; DRM poll expected to work (Mutter uses the same atomic path) |
| **Sway / wlroots** | **no** — Sway delegates idle to `swayidle` | fallback is a no-op; the **DRM poll is the only trigger**. The daemon detects the missing name, logs one warning, and parks (no retry spin). |

(An earlier `test-desktop.sh` tried to run these compositors headless in a
container to check this automatically; gnome-shell/sway are too fragile without a
real seat, so it was dropped in favour of the table above + tier 3b.)

---

## Tier 3b — `/sys/class/drm/*/dpms` under a non-KWin compositor (VM)

```sh
./test-vm.sh            # boot, install a desktop, run the dpms check, power off
./test-vm.sh shell      # boot and drop into an ssh shell in the VM
```

qemu runs **inside** a container (`--device /dev/kvm`); the Ubuntu 24.04 image +
cloud-init seed live in `vm-scratch/` (gitignored — `rm -rf vm-scratch` when
done). The guest has a `virtio-gpu` = real KMS (`card0-Virtual-1`). It tries a
GNOME autologin session first, falls back to **weston on the DRM backend**, then
samples `card0-Virtual-1/dpms` across the compositor's idle blank.

**Result** — weston (the Wayland reference compositor, DRM/atomic backend) on the
virtual GPU:

```
baseline dpms: card0-Virtual-1=On
weston up. idle-time=5s
t+02s  card0-Virtual-1=On
t+04s  card0-Virtual-1=On
t+06s  card0-Virtual-1=Off      <- idle timer fired; connector DPMS off
t+08s..t+30s  card0-Virtual-1=Off
```

**A non-KWin Wayland compositor flips `/sys/class/drm/<conn>/dpms` On→Off on
idle blank**, exactly as KWin does. weston uses the same libdrm atomic path as
Mutter and wlroots, and the kernel syncs the legacy property regardless of
compositor — so the daemon's primary trigger is not KWin-specific.

(Headless GNOME autologin never came up in the VM — a gdm3 + virtio-GPU + no-GL
plumbing issue, unrelated to the daemon; weston is a sufficient proxy for the
question. GNOME on real hardware remains worth a spot-check.)

---

## Running the normal suite

```sh
docker compose run --rm test      # 83 tests, ~6s
```

or natively: `pip install -e '.[test]' && python -m pytest`.
