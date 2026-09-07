---
name: Bug report
about: Something isn't working
labels: bug
---

**What happened / what you expected**


**Setup**
- Distro + version:
- Desktop + session (e.g. KDE Plasma 6, Wayland):
- GPU driver (`lspci -k | grep -A2 VGA`):
- TV model + webOS version (`webos-companion status`, or the TV's Settings → Support):
- Same subnet as the PC, or different?

**`webos-companion status` output**
```
paste here
```

**Journal around the problem**
```
journalctl --user -u webos-companion -n 100 --no-pager
```

**Anything from `webos-companion probe`** (optional, useful for D-Bus / DRM issues)
```
paste here
```
