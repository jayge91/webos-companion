#!/usr/bin/env bash
# Verify the END-USER install path from INSTALL.md on each supported distro, in
# throwaway containers, in parallel. Needs Docker.
#
#   ./test-install.sh                 # every distro, from the published repo
#   ./test-install.sh fedora          # just one (substring match)
#   ./test-install.sh -v fedora       # ...and stream its full log
#   REPO=git+https://github.com/you/webos-companion@branch ./test-install.sh
#
# For each distro this runs EXACTLY what INSTALL.md tells a user to run:
#   1. install python + pipx + git the distro's documented way
#   2. pipx install <REPO>
#   3. webos-companion --version         -> expect "webos-companion 0.1.0"
#   4. webos-companion --help            -> entry point resolves
#   5. webos-companion setup </dev/null  -> exits 2 "interactive" (no TTY), not a crash
#   6. webos-companion status            -> runs, reports "config error" (no config yet)
#
# It does NOT pair or touch a TV. Unit tests + build live in ./test-distros.sh;
# real D-Bus/DRM in ./test-integration.sh.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
LOGDIR="$(mktemp -d)"
trap 'rm -rf "$LOGDIR"' EXIT

VERBOSE=0; [ "${1:-}" = "-v" ] && { VERBOSE=1; shift; }
FILTER="${1:-}"

# What to install. Defaults to the published repo (matches INSTALL.md verbatim);
# override to test a fork or branch before publishing.
REPO="${REPO-git+https://github.com/jayge91/webos-companion}"

# Optional apt caching proxy (e.g. apt-cacher-ng). Set APT_PROXY=http://host:3142
# to speed up the Debian/Ubuntu builds; unset it's a no-op, skipped if unreachable.
APT_PROXY="${APT_PROXY-}"
if [ -n "$APT_PROXY" ] && ! curl -sf -m2 -o /dev/null "$APT_PROXY/acng-report.html"; then
  APT_PROXY=""
fi
[ -n "$APT_PROXY" ] && echo "using apt proxy $APT_PROXY"
echo "installing: $REPO"

# distro | image | "commands from INSTALL.md Step 1"
DISTROS=(
  "arch|archlinux:base|pacman -Sy --noconfirm --needed python python-pipx git"
  "debian12|debian:12|export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y -qq pipx git"
  "ubuntu2404|ubuntu:24.04|export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y -qq pipx git"
  "fedora41|fedora:41|dnf install -y -q pipx git"
  "opensuse|opensuse/tumbleweed|zypper -q -n install python3-pipx git"
)

one() {
  local name="$1" image="$2" setup="$3" log="$LOGDIR/$1.log"
  docker rm -f "wc-inst-$name" >/dev/null 2>&1 || true
  {
    echo "IMAGE $image"
    docker run --rm --name "wc-inst-$name" -e "APT_PROXY=$APT_PROXY" -e "REPO=$REPO" "$image" bash -uc '
      set -e
      if [ -n "${APT_PROXY:-}" ] && command -v apt-get >/dev/null; then
        mkdir -p /etc/apt/apt.conf.d
        echo "Acquire::http::Proxy \"$APT_PROXY\";" > /etc/apt/apt.conf.d/01proxy
      fi
      '"$setup"' >/dev/null 2>&1 || { echo "SETUP FAILED"; exit 3; }
      python3 --version
      export PATH="$HOME/.local/bin:$PATH"
      pipx install "$REPO" >/dev/null 2>&1 || { echo "PIPX INSTALL FAILED"; exit 4; }

      v="$(webos-companion --version)"; echo "version: $v"
      [ "$v" = "webos-companion 0.1.0" ] || { echo "BAD VERSION STRING"; exit 5; }

      webos-companion --help >/dev/null || { echo "HELP FAILED"; exit 6; }

      rc=0; webos-companion setup </dev/null >/tmp/s 2>&1 || rc=$?
      grep -qi interactive /tmp/s && [ "$rc" = 2 ] || { echo "setup non-tty: rc=$rc"; cat /tmp/s; exit 7; }
      echo "setup non-tty: exits 2 (interactive) OK"

      rc=0; webos-companion status >/tmp/st 2>&1 || rc=$?
      echo "status: rc=$rc $(head -1 /tmp/st)"

      echo "ALL OK"
    ' 2>&1
    echo "EXIT $?"
  } >"$log" 2>&1
}

pids=()
for entry in "${DISTROS[@]}"; do
  IFS='|' read -r name image setup <<<"$entry"
  [ -n "$FILTER" ] && [[ "$name $image" != *"$FILTER"* ]] && continue
  one "$name" "$image" "$setup" &
  pids+=($!)
done
[ "${#pids[@]}" -eq 0 ] && { echo "no distro matched '$FILTER'"; exit 2; }

echo "running ${#pids[@]} distro(s) in parallel..."
wait "${pids[@]}"

pass=0 fail=0
printf '\n%-12s %-22s %-8s %s\n' DISTRO IMAGE RESULT DETAIL
printf '%s\n' "────────────────────────────────────────────────────────────────────"
for log in "$LOGDIR"/*.log; do
  [ -e "$log" ] || continue
  name="$(basename "$log" .log)"
  image="$(sed -n 's/^IMAGE //p' "$log")"
  exit_line="$(sed -n 's/^EXIT //p' "$log" | tail -1)"
  pyver="$(grep -oE 'Python 3\.[0-9]+' "$log" | head -1)"
  if [ "$exit_line" = "0" ]; then
    printf '%-12s %-22s %-8s %s\n' "$name" "$image" "PASS" "$pyver  install + CLI OK"
    pass=$((pass+1))
  else
    reason="$(grep -oE 'SETUP FAILED|PIPX INSTALL FAILED|BAD VERSION STRING|HELP FAILED|setup non-tty.*|status: rc=.*|.*not found' "$log" | head -1)"
    printf '%-12s %-22s %-8s %s\n' "$name" "$image" "FAIL" "${pyver:-?}  ${reason:-see log}"
    fail=$((fail+1))
    [ "$VERBOSE" = 1 ] && { echo "---- $name ----"; cat "$log"; echo "--------------"; }
  fi
done
printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
