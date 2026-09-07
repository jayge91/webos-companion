#!/usr/bin/env bash
# Run the test suite + a pipx-install smoke test on several distros, in throwaway
# containers, ALL IN PARALLEL. Needs Docker. From the linux/ directory:
#
#   ./test-distros.sh            # every distro at once
#   ./test-distros.sh fedora     # just one (substring match)
#   ./test-distros.sh -v fedora  # ...and stream its full log
#
# Covers packaging / dependencies / build / unit tests (the pytest suite mocks
# D-Bus, DRM and the compositor and spins its own session bus). It does NOT
# exercise real logind / /sys/class/drm / a real desktop — for that use
# ./test-integration.sh (Tier 2) or a VM (Tier 3).
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
LOGDIR="$(mktemp -d)"
trap 'rm -rf "$LOGDIR"' EXIT

VERBOSE=0; [ "${1:-}" = "-v" ] && { VERBOSE=1; shift; }
FILTER="${1:-}"

# Optional apt caching proxy (e.g. apt-cacher-ng). Set APT_PROXY=http://host:3142
# to speed up the Debian/Ubuntu builds; unset it's a no-op, and it's skipped
# automatically if the given proxy is unreachable.
APT_PROXY="${APT_PROXY-}"
if [ -n "$APT_PROXY" ] && ! curl -sf -m2 -o /dev/null "$APT_PROXY/acng-report.html"; then
  APT_PROXY=""
fi
[ -n "$APT_PROXY" ] && echo "using apt proxy $APT_PROXY"

APT='export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y -qq python3 python3-pip python3-venv pipx dbus iproute2 iputils-ping'
# ubuntu2204: Python 3.10 (< the project's 3.11 floor) and no apt "pipx" — kept in
# the matrix so the lower bound stays documented; it is EXPECTED TO FAIL.
DISTROS=(
  "arch|archlinux:base|pacman -Sy --noconfirm --needed python python-pip python-pipx dbus iproute2"
  "debian12|debian:12|$APT"
  "ubuntu2404|ubuntu:24.04|$APT"
  "ubuntu2204|ubuntu:22.04|export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y -qq python3 python3-pip dbus iproute2 && python3 -m pip install -q pipx"
  "fedora41|fedora:41|dnf install -y -q python3 python3-pip pipx dbus-daemon iproute iputils"
  "opensuse|opensuse/tumbleweed|zypper -q -n install python3 python3-pip python3-pipx dbus-1-daemon iproute2 iputils"
)

one() {
  local name="$1" image="$2" setup="$3" log="$LOGDIR/$1.log"
  docker rm -f "wc-mx-$name" >/dev/null 2>&1 || true
  {
    echo "IMAGE $image"
    docker run --rm --name "wc-mx-$name" -e "APT_PROXY=$APT_PROXY" -v "$HERE":/src:ro "$image" bash -uc "
      set -e
      if [ -n \"\${APT_PROXY:-}\" ] && command -v apt-get >/dev/null; then
        mkdir -p /etc/apt/apt.conf.d
        echo \"Acquire::http::Proxy \\\"\$APT_PROXY\\\";\" > /etc/apt/apt.conf.d/01proxy
      fi
      $setup >/dev/null 2>&1 || { echo 'SETUP FAILED'; exit 3; }
      python3 --version
      cp -r /src /app && cd /app
      python3 -m pip install --quiet --break-system-packages -e '.[test]'
      if command -v dbus-run-session >/dev/null; then
        dbus-run-session -- python3 -m pytest -q
      else
        echo '(no dbus-run-session; logind/screensaver tests skip)'; python3 -m pytest -q
      fi
      export PATH=\"\$HOME/.local/bin:\$PATH\"
      ( pipx install /app || python3 -m pipx install /app ) >/dev/null 2>&1
      webos-companion --version && echo 'pipx+cli OK'
    " 2>&1
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

# ubuntu2204 is expected to fail (Python 3.10 < the 3.11 floor) — it does not count
# against the exit status, it is only in the matrix to keep the lower bound honest.
XFAIL="ubuntu2204"

pass=0 fail=0 xfail=0
printf '\n%-12s %-22s %-8s %s\n' DISTRO IMAGE RESULT DETAIL
printf '%s\n' "────────────────────────────────────────────────────────────────────"
for log in "$LOGDIR"/*.log; do
  [ -e "$log" ] || continue
  name="$(basename "$log" .log)"
  image="$(sed -n 's/^IMAGE //p' "$log")"
  exit_line="$(sed -n 's/^EXIT //p' "$log" | tail -1)"
  pyver="$(grep -oE 'Python 3\.[0-9]+' "$log" | head -1)"
  summ="$(grep -oE '[0-9]+ (passed|failed|error)[^,]*' "$log" | tail -1)"
  if [ "$exit_line" = "0" ]; then
    printf '%-12s %-22s %-8s %s\n' "$name" "$image" "PASS" "$pyver  $summ"
    pass=$((pass+1))
  elif [[ " $XFAIL " == *" $name "* ]]; then
    printf '%-12s %-22s %-8s %s\n' "$name" "$image" "xfail" "${pyver:-?}  below the 3.11 floor (expected)"
    xfail=$((xfail+1))
  else
    reason="$(grep -oE 'SETUP FAILED|Requires-Python|No matching distribution|command not found|ERROR:.*' "$log" | head -1)"
    printf '%-12s %-22s %-8s %s\n' "$name" "$image" "FAIL" "${pyver:-?}  ${reason:-see log}"
    fail=$((fail+1))
    [ "$VERBOSE" = 1 ] && { echo "---- $name full log ----"; cat "$log"; echo "------------------------"; }
  fi
done
printf '\n%d passed, %d failed, %d xfail\n' "$pass" "$fail" "$xfail"
[ "$fail" -eq 0 ]
