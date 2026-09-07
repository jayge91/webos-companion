# Maintaining / releasing

## Repo settings to do once (GitHub web UI)

- **About** → set the description and these **topics**:
  `lg` `webos` `oled` `burn-in` `wake-on-lan` `wayland` `kde` `systemd`
  `linux` `python` `tv` `home-automation`
- **Settings → General** → set a **Social preview** image (shows on Reddit / HN / Slack).
- **Settings → General → Features** → enable **Discussions** (the issue-template
  `config.yml` links to it).
- **Insights → Community Standards** — fill any gaps it flags.

## Cutting a release

1. Bump `version` in `pyproject.toml` and add a section to `CHANGELOG.md`.
2. `git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z`
3. GitHub → **Releases → Draft a new release** → pick the tag, paste the
   changelog section as the notes, publish.
4. AUR: in `packaging/`, `updpkgsums`, `makepkg --printsrcinfo > .SRCINFO`,
   push `PKGBUILD` + `.SRCINFO` to the AUR git repo.

## Test matrix before a release

```sh
docker compose run --rm test     # unit suite
./test-install.sh                # documented pipx path, 5 distros
./test-integration.sh debian     # real D-Bus / DRM against this host
```

Plus a manual blank / suspend / resume / shutdown cycle on real hardware.

## Announcing (see the launch notes in the project history)

Priority order: reply to the "Linux?" issues on JPersson77/LGTVCompanion →
r/OLED_Gaming + r/linux_gaming with a demo GIF → Show HN / lobste.rs →
tip GamingOnLinux + OMG! Linux → CachyOS Discord. Have the tag, the AUR package,
and the demo GIF ready first, and be around to answer issues for a week.
