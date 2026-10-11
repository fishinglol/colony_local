import pytest

from colony.config import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Every test gets its own data dir and never touches real keys or ~/.colony."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MOCK_MODE", "true")
    monkeypatch.setenv("LAYA_URL", "")
    monkeypatch.setenv("JEV_API_KEY", "")                    # a real key in ~/.colony/.env must not leak into tests
    monkeypatch.setenv("PROJECTS_DIR", str(tmp_path / "projects"))               # never the real ~/Documents
    monkeypatch.setenv("OPENCLAW_CONFIG_PATH", str(tmp_path / "openclaw.json"))   # never the real ~/.openclaw
    from colony.engine import openclaw
    openclaw._known_agents.clear()
    monkeypatch.setattr(openclaw, "GATEWAY_LOG", tmp_path / "no-gateway.log")       # never the real Gateway's log
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
