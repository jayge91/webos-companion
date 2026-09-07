# Dev/test image for the Linux port. Arch-based to match CachyOS userland.
# Builds and runs the unit-test suite only — no host services are touched.
FROM archlinux:base

RUN pacman -Syu --noconfirm \
        python python-pip dbus iproute2 \
    && pacman -Scc --noconfirm

WORKDIR /app

# Install deps first for layer caching, then the package itself (editable, so a
# bind-mounted source tree is used live).
COPY pyproject.toml README.md ./
COPY webos_companion ./webos_companion
RUN pip install --break-system-packages --no-cache-dir -e '.[test]'

COPY . .

# Run as a real uid (1000 = typical single-user desktop) so files written into
# the bind-mounted tree are owned by the host user and dbus-daemon has a passwd
# entry. Override at build time with --build-arg UID=$(id -u) if yours differs.
ARG UID=1000
ARG GID=1000
RUN groupadd -g "$GID" dev 2>/dev/null || true \
    && useradd -u "$UID" -g "$GID" -m -s /bin/bash dev
USER dev

# A private session bus so the logind trigger tests can run too.
CMD ["dbus-run-session", "--", "pytest", "-q"]
