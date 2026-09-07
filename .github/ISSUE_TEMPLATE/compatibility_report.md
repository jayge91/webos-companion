---
name: Compatibility report
about: Tell us how it went on your setup — whether it worked or not
labels: compatibility
---

**Did it work?**  (all of it / partly / not at all)


**Setup**
- Distro + version:
- Desktop + session (e.g. GNOME 47 / Wayland, Sway, KDE Plasma 6):
- GPU + driver (`lspci -k | grep -A2 -E 'VGA|3D'`):
- TV model + webOS version (`webos-companion status`, or the TV's Settings → Support):
- TV on the same subnet as the PC?

**Which behaviours did you test?**  (tick what you tried)
- [ ] Screen blanks on idle → TV panel goes off
- [ ] Screen wakes → TV panel comes back
- [ ] Suspend → TV powers off
- [ ] Resume → Wake-on-LAN brings the TV back
- [ ] Shutdown / reboot → TV powers off
- [ ] `webos-companion setup` / discovery found the TV

**Anything that didn't work, or needed manual config**


**`webos-companion status` output**
```
paste here
```

**Journal, if something misbehaved**
```
journalctl --user -u webos-companion -n 100 --no-pager
```
