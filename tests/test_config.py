import pytest

from webos_companion import config
from webos_companion.config import Config


def test_defaults_and_validate():
    cfg = Config()
    with pytest.raises(ValueError):
        cfg.validate()
    cfg.ip = "192.168.1.5"
    cfg.validate()


def test_save_load_roundtrip(xdg):
    cfg = Config(ip="10.0.0.9", mac="ab:cd:ef:12:34:56", connector="HDMI-A-1", ssl=False)
    cfg.save()
    assert config.config_path().exists()
    assert config.config_path().suffix == ".yaml"
    loaded = Config.load()
    assert loaded == cfg


def test_saved_file_is_readable_yaml_with_comments(xdg):
    Config(ip="10.0.0.9", mac="aa:bb:cc:dd:ee:ff").save()
    text = config.config_path().read_text()
    assert "# your TV's IP address" in text
    assert "ip: 10.0.0.9" in text


def test_load_missing_returns_defaults(xdg):
    assert Config.load() == Config()


def test_unknown_key_rejected(xdg):
    config.config_path().parent.mkdir(parents=True)
    config.config_path().write_text("ip: 1.2.3.4\nbogus: 1\n")
    with pytest.raises(ValueError, match="bogus"):
        Config.load()


def test_legacy_toml_is_migrated(xdg):
    legacy = config.legacy_config_path()
    legacy.parent.mkdir(parents=True)
    legacy.write_text('ip = "10.0.0.7"\nmac = "aa:bb:cc:dd:ee:ff"\nssl = false\n')

    loaded = Config.load()
    assert loaded.ip == "10.0.0.7"
    assert loaded.ssl is False
    # migrated to yaml, old file removed
    assert config.config_path().exists()
    assert not legacy.exists()


def test_client_key_roundtrip(xdg):
    assert config.load_client_key() is None
    config.save_client_key("secret-key")
    assert config.load_client_key() == "secret-key"
    assert (config.client_key_path().stat().st_mode & 0o777) == 0o600
