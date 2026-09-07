# Changelog

## 0.1.0 — 2026-09-06

First public release. A Linux port of
[LGTV Companion](https://github.com/JPersson77/LGTVCompanion) — makes an LG webOS
TV follow the local display power state.

- Screen blanks on idle → `turnOffScreen` (panel off, TV stays on the network).
- Suspend / shutdown → `system/turnOff`.
- Resume → Wake-on-LAN, reconnect, restore the screen state; a background
  recoverer keeps retrying for up to 5 minutes.
- Three trigger sources: DRM `dpms` poll (primary), systemd-logind
  (`PrepareForSleep` / `PrepareForShutdown` + a delay inhibitor),
  and `org.freedesktop.ScreenSaver` (opt-in fallback).
- `webos-companion setup` — network scan, TV picklist (IP / MAC / name / model
  via AirPlay `/info`), config, pairing, and a `systemctl --user` service.
- CLI: `setup`, `discover`, `pair`, `on`, `off`, `status`, `probe`,
  `service {install,remove,status}`, `run [--dry-run] [--seconds N]`.
- Runs entirely unprivileged.

Verified end-to-end on KDE Plasma 6 / Wayland, NVIDIA RTX 3080 Ti (proprietary
driver), one LG C2 (webOS 22). 83 tests, green on Python 3.11–3.14 across Arch,
Debian 12, Ubuntu 24.04, Fedora 41, openSUSE Tumbleweed. See the
[Project status](README.md#project-status) section for what's tested and the
known limitations.
