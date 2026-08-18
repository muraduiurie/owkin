import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def no_config_file(monkeypatch):
    # keep the repo's own config.yaml out of these tests
    monkeypatch.setenv("CONFIG_FILE", "/nonexistent/config.yaml")


def test_defaults_apply_without_a_config_file():
    settings = Settings()
    assert settings.server.port == 8000
    assert settings.docker.repository == "owkin-job"
    assert settings.debug is False


def test_yaml_file_is_read(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("server:\n  port: 9999\ndebug: true\n")
    monkeypatch.setenv("CONFIG_FILE", str(cfg))

    settings = Settings()
    assert settings.server.port == 9999
    assert settings.debug is True


def test_env_overrides_yaml_but_keeps_siblings(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("scanner:\n  url: http://from-yaml\n  timeout: 3\n")
    monkeypatch.setenv("CONFIG_FILE", str(cfg))
    monkeypatch.setenv("SCANNER__TIMEOUT", "42")

    settings = Settings()
    assert settings.scanner.timeout == 42
    assert settings.scanner.url == "http://from-yaml"


def test_bad_type_in_yaml_is_rejected(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("server:\n  port: not-a-number\n")
    monkeypatch.setenv("CONFIG_FILE", str(cfg))

    with pytest.raises(ValueError):
        Settings()
