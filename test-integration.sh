#!/usr/bin/env bash
# Tier 2: exercise the daemon's real integration paths (discover / probe /
# dry-run watch) using ANOTHER distro's Python + D-Bus stack, against THIS
# host's live logind, /sys/class/drm and desktop session.
#
# Everything is throwaway:
#   * the image is built fresh and can be deleted with:  docker rmi wc-int-<distro>
#   * the container is --rm; /sys and the D-Bus sockets are bind-mounted READ-ONLY
#   * runs as your uid (files it writes to dev-config/ dev-state/ are yours)
#   * dry-run is passive: no logind inhibitor is taken, the TV is not touched
#   * the only outbound traffic is SSDP / AirPlay / WebSocket probes to the TV
#
# Usage:  ./test-integration.sh debian                 # 20s dry-run watch
#         ./test-integration.sh fedora discover
#         ./test-integration.sh ubuntu 'probe'
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
DISTRO="${1:-debian}"; shift || true
CMD="${*:-run --dry-run -v --seconds 20}"

case "$DISTRO" in
  debian)   IMG=debian:12          ; PREP='export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 python3-pip pipx iproute2 iputils-ping ca-certificates' ;;
  ubuntu)   IMG=ubuntu:24.04       ; PREP='export DEBIAN_FRONTEND=noninteractive && apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 python3-pip pipx iproute2 iputils-ping ca-certificates' ;;
  fedora)   IMG=fedora:41          ; PREP='dnf install -y -q python3 python3-pip pipx iproute iputils' ;;
  opensuse) IMG=opensuse/tumbleweed; PREP='zypper -q -n install python3 python3-pip python3-pipx iproute2 iputils' ;;
  arch)     IMG=archlinux:base     ; PREP='pacman -Sy --noconfirm --needed python python-pipx iproute2' ;;
  *) echo "unknown distro: $DISTRO (debian|ubuntu|fedora|opensuse|arch)"; exit 2 ;;
esac

TAG="wc-int-$DISTRO"
XRD="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

# optional apt caching proxy (see test-distros.sh) — set APT_PROXY=http://host:3142
APT_PROXY="${APT_PROXY-}"
if [ -n "$APT_PROXY" ] && ! curl -sf -m2 -o /dev/null "$APT_PROXY/acng-report.html"; then
  APT_PROXY=""
fi
PROXY_RUN=":"
[ -n "$APT_PROXY" ] && PROXY_RUN="command -v apt-get >/dev/null && (mkdir -p /etc/apt/apt.conf.d && echo 'Acquire::http::Proxy \"$APT_PROXY\";' > /etc/apt/apt.conf.d/01proxy) || true"

docker build -t "$TAG" -f - "$HERE" >/dev/null <<EOF
FROM $IMG
RUN $PROXY_RUN
RUN $PREP
ARG UID=$(id -u)
ARG GID=$(id -g)
RUN old=\$(getent passwd \$UID | cut -d: -f1); [ -n "\$old" ] && userdel "\$old" 2>/dev/null || true; \
    (groupadd -g \$GID dev 2>/dev/null || true); \
    useradd -u \$UID -g \$GID -M -d /home/dev dev && mkdir -p /home/dev && chown \$UID:\$GID /home/dev
COPY . /src
RUN python3 -m pip install --break-system-packages /src 2>/dev/null || pipx install /src
USER dev
EOF

docker rm -f "wc-int-$DISTRO" >/dev/null 2>&1 || true
exec docker run --rm -i --name "wc-int-$DISTRO" \
  --network host \
  -e "DBUS_SESSION_BUS_ADDRESS=unix:path=$XRD/bus" \
  -e "XDG_RUNTIME_DIR=$XRD" \
  -v /sys:/sys:ro \
  -v /run/dbus/system_bus_socket:/run/dbus/system_bus_socket \
  -v "$XRD/bus:$XRD/bus" \
  -v "$HERE/dev-config":/home/dev/.config/webos-companion \
  -v "$HERE/dev-state":/home/dev/.local/state/webos-companion \
  "$TAG" bash -uc "python3 --version; echo '--- webos-companion $CMD ---'; exec webos-companion $CMD"
