from __future__ import annotations

from pathlib import Path

import pytest

from tests.helpers import make_edid


@pytest.fixture
def drm_tree(tmp_path: Path):
    """Build a fake /sys/class/drm tree; returns (root_path, make_connector)."""
    root = tmp_path / "drm"
    root.mkdir()

    def make_connector(
        name: str,
        *,
        card: str = "card1",
        dpms: str = "On",
        status: str = "connected",
        vendor: str | None = "GSM",
    ) -> Path:
        d = root / f"{card}-{name}"
        d.mkdir(parents=True)
        (d / "dpms").write_text(dpms + "\n")
        (d / "status").write_text(status + "\n")
        if vendor is not None:
            (d / "edid").write_bytes(make_edid(vendor))
        return d

    return root, make_connector


@pytest.fixture
def xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "config"
    state = tmp_path / "state"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    return cfg, state
