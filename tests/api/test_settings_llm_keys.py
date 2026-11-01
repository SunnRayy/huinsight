"""Settings → AI Models key handling, local vs cloud.

Cloud (UIS_GCS_BUCKET set) keys come from Secret Manager, so a save must be
refused rather than silently written to a container-local .env. Locally a
saved key must reach the running process, not only the .env file.
"""

import json
import os

import pytest

from src.api.routes import settings as settings_routes
from src.services import env_manager

_ENV = "UISTEST_PROVIDER_API_KEY"


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("# keep me\nOTHER=1\n")
    monkeypatch.setattr(env_manager, "ENV_PATH", path)
    monkeypatch.delenv(_ENV, raising=False)
    yield path
    os.environ.pop(_ENV, None)


@pytest.fixture
def no_settings_io(monkeypatch):
    store = {"settings": {"llm": {}}}
    monkeypatch.setattr(settings_routes.settings_manager, "load_settings", lambda: store["settings"])
    monkeypatch.setattr(
        settings_routes.settings_manager, "save_settings", lambda s: store.update(settings=s)
    )
    monkeypatch.setattr(settings_routes, "mark_dirty", lambda: None)
    return store


def _update(key_value):
    return settings_routes.LLMSettingsUpdate(
        channels=[settings_routes.ChannelUpdate(
            name="T", provider="gemini", enabled=True, api_key_env=_ENV,
            api_key_value=key_value, models=["m"],
        )],
        primary_model="gemini/m",
        fallback_models=[],
        temperature=0.5,
        max_output_tokens=100,
    )


def test_local_save_reaches_running_process(env_file, monkeypatch, no_settings_io):
    monkeypatch.delenv("UIS_GCS_BUCKET", raising=False)
    monkeypatch.setenv(_ENV, "old-key")

    resp = settings_routes.update_llm_settings(_update("new-key"))

    assert os.environ[_ENV] == "new-key"
    text = env_file.read_text()
    assert "new-key" in text and "# keep me" in text and "OTHER=1" in text
    assert resp.keys_editable is True
    assert resp.key_source == "env_file"
    assert resp.channels[0].key_status == "configured"


def test_cloud_save_with_key_is_refused_and_writes_nothing(env_file, monkeypatch, no_settings_io):
    monkeypatch.setenv("UIS_GCS_BUCKET", "bucket")
    monkeypatch.setenv(_ENV, "secret-manager-key")
    before_settings = no_settings_io["settings"]

    resp = settings_routes.update_llm_settings(_update("typed-key"))

    assert resp.status_code == 409
    body = json.loads(resp.body)
    assert body["error"]["code"] == "ERR_KEYS_MANAGED_EXTERNALLY"
    assert _ENV in body["error"]["message"]
    assert "typed-key" not in body["error"]["message"]
    assert os.environ[_ENV] == "secret-manager-key"
    assert "typed-key" not in env_file.read_text()
    assert no_settings_io["settings"] is before_settings  # config not saved either


def test_cloud_save_without_key_still_saves_config(env_file, monkeypatch, no_settings_io):
    monkeypatch.setenv("UIS_GCS_BUCKET", "bucket")
    monkeypatch.setenv(_ENV, "secret-manager-key")

    resp = settings_routes.update_llm_settings(_update(None))

    assert resp.keys_editable is False
    assert resp.key_source == "secret_manager"
    assert no_settings_io["settings"]["llm"]["primary_model"] == "gemini/m"


def test_key_status_reflects_server_env_not_env_file(env_file, monkeypatch):
    # Cloud has no .env; a Secret Manager key must still show as configured.
    monkeypatch.setenv(_ENV, "from-secret-manager")
    assert env_manager.get_key_status(_ENV) == "configured"
    monkeypatch.delenv(_ENV)
    env_file.write_text(f"{_ENV}=only-in-file\n")
    assert env_manager.get_key_status(_ENV) == "missing"


def test_update_key_raises_on_cloud(env_file, monkeypatch):
    monkeypatch.setenv("UIS_GCS_BUCKET", "bucket")
    with pytest.raises(env_manager.KeysNotEditableError):
        env_manager.update_key(_ENV, "x")
    assert _ENV not in os.environ


def test_channel_test_without_typed_key_uses_server_key(monkeypatch):
    import litellm

    seen = {}
    monkeypatch.setattr(litellm, "completion", lambda **kw: seen.update(kw))
    monkeypatch.setenv(_ENV, "server-key")

    resp = settings_routes.test_channel(
        settings_routes.ChannelTestRequest(provider="gemini", model="m", api_key_env=_ENV)
    )

    assert resp.success is True
    assert seen["api_key"] == "server-key"


def test_channel_test_prefers_typed_key(monkeypatch):
    import litellm

    seen = {}
    monkeypatch.setattr(litellm, "completion", lambda **kw: seen.update(kw))
    monkeypatch.setenv(_ENV, "server-key")

    settings_routes.test_channel(settings_routes.ChannelTestRequest(
        provider="gemini", model="m", api_key="typed", api_key_env=_ENV,
    ))

    assert seen["api_key"] == "typed"


def test_channel_test_with_no_key_anywhere_fails_without_calling(monkeypatch):
    import litellm

    monkeypatch.setattr(litellm, "completion", lambda **kw: pytest.fail("must not call"))
    monkeypatch.delenv(_ENV, raising=False)

    resp = settings_routes.test_channel(
        settings_routes.ChannelTestRequest(provider="gemini", model="m", api_key_env=_ENV)
    )

    assert resp.success is False
