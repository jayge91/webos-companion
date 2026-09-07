#!/usr/bin/env bash
# Tier 3b: boot Ubuntu + GNOME (Mutter/Wayland) in a REAL VM with a virtual GPU
# and check whether /sys/class/drm/*/dpms flips when the desktop blanks on idle —
# the daemon's primary trigger — under a compositor other than KWin.
#
# qemu runs INSIDE a container (--device /dev/kvm). Disk image + seed live in
# vm-scratch/ (gitignored). Set APT_PROXY=http://host:3142 to pull GNOME through
# an apt cache. Nothing installs on the host; `rm -rf vm-scratch` when done.
#
#   ./test-vm.sh            # boot, install GNOME, run the check, power off
#   ./test-vm.sh shell      # boot, then open an ssh shell inside the VM
set -eu
HERE="$(cd "$(dirname "$0")" && pwd)"
S="$HERE/vm-scratch"; mkdir -p "$S"
MODE="${1:-run}"
APT_PROXY="${APT_PROXY-}"
URL=https://cloud-images.ubuntu.com/releases/noble/release/ubuntu-24.04-server-cloudimg-amd64.img

[ -f "$S/ubuntu-24.04.img" ] || curl -L --progress-bar -o "$S/ubuntu-24.04.img" "$URL"
[ -f "$S/id" ] || ssh-keygen -t ed25519 -N '' -f "$S/id" -q

cat > "$S/user-data" <<EOF
#cloud-config
hostname: gnomevm
users:
  - name: t
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    shell: /bin/bash
    ssh_authorized_keys: ["$(cat "$S/id.pub")"]
apt:
  http_proxy: "$APT_PROXY"
  conf: |
    Acquire::Retries "20";
    Acquire::http::Pipeline-Depth "0";
    Acquire::Queue-Mode "access";
write_files:
  - path: /etc/gdm3/custom.conf
    content: "[daemon]\nAutomaticLoginEnable=true\nAutomaticLogin=t\nWaylandEnable=true\n"
runcmd:
  - [bash, -c, "for i in 1 2 3 4 5; do apt-get update -qq && apt-get install -y -qq --no-install-recommends gnome-shell gdm3 dbus-user-session gnome-settings-daemon python3-pip && break; sleep 15; done"]
  - [systemctl, set-default, graphical.target]
  - [systemctl, isolate, graphical.target]
  - [bash, -c, "touch /tmp/setup-done"]
EOF
printf 'instance-id: gnomevm\nlocal-hostname: gnomevm\n' > "$S/meta-data"

cat > "$S/guest-test.sh" <<'GT'
#!/usr/bin/env bash
set -u
U=1000
t(){ sudo -u t env XDG_RUNTIME_DIR=/run/user/$U DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$U/bus "$@"; }
dpms(){ for f in /sys/class/drm/card*-*/dpms; do printf '%s=%s ' "$(basename "$(dirname "$f")")" "$(cat "$f" 2>/dev/null)"; done; echo; }
sample(){ for i in $(seq 1 "$1"); do printf 't+%02ds  ' $((i*2)); dpms; sleep 2; done; }

echo "### DRM in the guest: $(ls /sys/class/drm/ | tr '\n' ' ')"
echo "### cloud-init: $(cloud-init status 2>/dev/null); gnome-shell pkg: $(dpkg -l gnome-shell 2>/dev/null | grep -c ^ii)"

echo "### wait up to 2 min for a gnome-shell wayland session"
for i in $(seq 1 40); do pgrep -x gnome-shell >/dev/null && break; sleep 3; done

if pgrep -x gnome-shell >/dev/null; then
  echo "=== COMPOSITOR: GNOME / Mutter ==="
  loginctl list-sessions --no-legend
  echo -n "baseline dpms: "; dpms
  t gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type nothing 2>/dev/null || true
  echo "### idle-delay=5s -> sampling dpms for 30s"
  t gsettings set org.gnome.desktop.session idle-delay 5 2>&1 || echo "  gsettings failed"
  sample 15
  echo "### wake"
  t dbus-send --session --dest=org.gnome.ScreenSaver /org/gnome/ScreenSaver org.gnome.ScreenSaver.SetActive boolean:false 2>/dev/null || true
  t gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null || true
  sleep 5; echo -n "after wake:    "; dpms

  echo "### the daemon (dry-run) reacting to a GNOME blank"
  python3 -m pip install -q --break-system-packages "$HOME/src" 2>&1 | tail -1 || true
  mkdir -p "$HOME/.config/webos-companion"
  printf 'ip: 10.0.0.1\nscreensaver_dbus: true\n' > "$HOME/.config/webos-companion/config.yaml"
  ( t "$HOME/.local/bin/webos-companion" run --dry-run -v --seconds 45 2>&1 \
      | grep -E 'watching DRM connector|display blanked|display on|ScreenSaver ActiveChanged|not available on the session|listening for logind' ) &
  D=$!
  sleep 4
  t gsettings set org.gnome.desktop.session idle-delay 5
  sleep 30
  t gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null || true
  wait $D 2>/dev/null || true
else
  echo "!! no gnome-shell session — using weston on the real DRM backend instead"
  sudo systemctl stop gdm3 2>/dev/null || true
  sudo apt-get install -y -qq --no-install-recommends weston >/dev/null 2>&1
  echo "### DRM sanity: $(ls -l /dev/dri/ 2>&1 | tr '\n' ' ')"
  echo "### modes: $(cat /sys/class/drm/card0-Virtual-1/modes 2>/dev/null | tr '\n' ',')"
  cat > /tmp/weston.ini <<'W'
[core]
idle-time=5
require-input=false
xwayland=false
W
  echo "=== COMPOSITOR: weston (DRM/atomic backend, running as root) ==="
  echo -n "baseline dpms: "; dpms
  sudo mkdir -p /run/weston && sudo chmod 700 /run/weston
  sudo env XDG_RUNTIME_DIR=/run/weston LIBSEAT_BACKEND=builtin \
    weston --backend=drm --config=/tmp/weston.ini --log=/tmp/weston.log \
           --continue-without-input >/tmp/weston.out 2>&1 &
  WP=$!
  for i in $(seq 1 10); do grep -qiE "compositor|output .* enabled|repaint" /tmp/weston.log 2>/dev/null && break; sleep 2; done
  echo "--- weston startup log ---"; sudo tail -12 /tmp/weston.log 2>/dev/null; sudo tail -3 /tmp/weston.out 2>/dev/null
  if ! kill -0 $WP 2>/dev/null; then echo "!! weston exited; cannot test dpms in this VM"; else
    echo "### weston up. idle-time=5s -> sampling card0-Virtual-1 dpms for 30s"
    sample 15
    echo "### send a fake input event to wake"
    sudo bash -c 'command -v evemu-event >/dev/null || true; systemctl start systemd-backlight 2>/dev/null || true'
    sudo pkill -SIGUSR1 weston 2>/dev/null || true   # weston wakes on activity; SIGUSR1 as a nudge
    sleep 4; echo -n "after nudge: "; dpms
  fi
  sudo kill $WP 2>/dev/null || true
fi
wait $D 2>/dev/null || true
echo "### END"
GT

docker build -t wc-qemu -f - "$HERE" >/dev/null <<'EOF'
FROM debian:12
RUN export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y -qq \
    --no-install-recommends qemu-system-x86 qemu-utils cloud-image-utils openssh-client
EOF

rm -rf "$S/src"; mkdir -p "$S/src"
tar -C "$HERE" --exclude='*/__pycache__' -cf - webos_companion pyproject.toml README.md | tar -C "$S/src" -xf -

# The orchestrator runs from a file inside the VM mount (never from stdin — piping
# a script via `bash -s` can end early when docker closes the container's stdin).
cat > "$S/orch.sh" <<'ORCH'
#!/usr/bin/env bash
set -u
MODE="${1:-run}"
cd /vm
qemu-img create -f qcow2 -F qcow2 -b ubuntu-24.04.img disk.qcow2 16G >/dev/null
cloud-localds seed.iso user-data meta-data
qemu-system-x86_64 -enable-kvm -m 4096 -smp 4 \
  -drive file=disk.qcow2,if=virtio -drive file=seed.iso,if=virtio,format=raw \
  -device virtio-vga -display none -serial file:/vm/console.log \
  -netdev user,id=n,hostfwd=tcp::2222-:22 -device virtio-net-pci,netdev=n </dev/null >/dev/null 2>&1 &
QEMU=$!
trap 'kill $QEMU 2>/dev/null || true; wait 2>/dev/null || true' EXIT
SSH="ssh -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=4 -o BatchMode=yes -i id t@127.0.0.1"

echo "[vm] booting; waiting for ssh (up to 8 min)..."
ok=""
for i in $(seq 1 120); do
  kill -0 $QEMU 2>/dev/null || { echo "[vm] qemu died:"; tail -20 console.log; exit 1; }
  $SSH true 2>/dev/null && { ok=1; break; }
  sleep 4
done
[ -n "$ok" ] || { echo "[vm] ssh never came up"; tail -40 console.log; exit 1; }
echo "[vm] ssh up after ~$((i*4))s. waiting for cloud-init (GNOME install, several min)..."
$SSH "sudo cloud-init status --wait" 2>&1 | tail -2

if [ "$MODE" = shell ]; then echo "[vm] ready — 'sudo poweroff' to exit"; exec $SSH; fi

tar -C src -cf - . | $SSH "rm -rf src && mkdir src && tar -C src -xf -"
$SSH "cat > /tmp/gt.sh" < guest-test.sh
$SSH "bash /tmp/gt.sh"
echo "[vm] powering off"
$SSH "sudo poweroff" 2>/dev/null || true
sleep 5
ORCH

docker rm -f wc-vm >/dev/null 2>&1 || true
DFLAGS=(-i); [ "$MODE" = shell ] && DFLAGS=(-it)
docker run --rm "${DFLAGS[@]}" --name wc-vm --device /dev/kvm -v "$S":/vm -w /vm wc-qemu \
  bash /vm/orch.sh "$MODE"
