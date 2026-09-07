"""Configuration (YAML) and persisted pairing key (XDG paths)."""

from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path

import yaml

APP = "webos-companion"


def _xdg(env: str, default: Path) -> Path:
    raw = os.environ.get(env)
    return Path(raw) if raw else default


def config_dir() -> Path:
    return _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / APP


def state_dir() -> Path:
    return _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / APP


def config_path() -> Path:
    return config_dir() / "config.yaml"


def legacy_config_path() -> Path:
    return config_dir() / "config.toml"


def client_key_path() -> Path:
    return state_dir() / "client-key"


# One-line comment written above each key in the generated file.
_COMMENTS = {
    "ip": "your TV's IP address (required)",
    "mac": "your TV's MAC address, for Wake-on-LAN on resume (required)",
    "connector": 'DRM connector, e.g. "HDMI-A-1". Empty = auto-detect the LG panel by EDID',
    "ssl": "use the secure port 3001 (leave true for modern webOS)",
    "port": "override the websocket port; 0 = 3001 (ssl) / 3000 (plain)",
    "poll_interval": "seconds between display-power (dpms) checks",
    "screensaver_dbus": (
        "also react to org.freedesktop.ScreenSaver (also fires on a plain lock);\n"
        "turn on only where the sysfs dpms node does not move"
    ),
    "wol_broadcast": "broadcast address for the Wake-on-LAN magic packet",
}


@dataclass
class Config:
    ip: str = ""
    mac: str = ""
    connector: str = ""
    ssl: bool = True
    port: int = 0
    poll_interval: float = 2.0
    screensaver_dbus: bool = False
    wol_broadcast: str = "255.255.255.255"

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        explicit = path is not None
        path = path or config_path()
        if not path.exists() and not explicit and legacy_config_path().exists():
            return cls._load_legacy_toml(legacy_config_path())
        if not path.exists():
            return cls()
        data = yaml.safe_load(path.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{path}: expected a mapping of settings")
        return cls._from_dict(data, path)

    @classmethod
    def _load_legacy_toml(cls, path: Path) -> "Config":
        import tomllib

        with path.open("rb") as fh:
            data = tomllib.load(fh)
        cfg = cls._from_dict(data, path)
        # write it out in the new format and drop the old file
        cfg.save()
        path.unlink(missing_ok=True)
        return cfg

    @classmethod
    def _from_dict(cls, data: dict, path: Path) -> "Config":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown config keys in {path}: {sorted(unknown)}")
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_dumps(self))
        path.chmod(0o600)

    def validate(self) -> None:
        if not self.ip:
            raise ValueError("config: 'ip' is required")
        if self.poll_interval <= 0:
            raise ValueError("config: 'poll_interval' must be > 0")


def _dumps(cfg: Config) -> str:
    lines = ["# webos-companion configuration", ""]
    for f in fields(cfg):
        for comment in _COMMENTS.get(f.name, "").split("\n"):
            if comment:
                lines.append(f"# {comment}")
        value = getattr(cfg, f.name)
        lines.append(yaml.safe_dump({f.name: value}, default_flow_style=False).strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load_client_key(path: Path | None = None) -> str | None:
    path = path or client_key_path()
    try:
        key = path.read_text().strip()
    except FileNotFoundError:
        return None
    return key or None


def save_client_key(key: str, path: Path | None = None) -> None:
    path = path or client_key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(key + "\n")
    path.chmod(0o600)
