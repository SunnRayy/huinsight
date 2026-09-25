"""API-test defaults.

The AI-advisor routes refuse to generate when no LLM key is configured. Whether
a key is present depends on the machine (src/api/main.py loads a local .env),
so route tests that mock the generators pretend a key exists by default. Tests
of the no-key path override this with their own monkeypatch.
"""
import pytest


@pytest.fixture(autouse=True)
def _llm_key_configured_by_default(monkeypatch):
    monkeypatch.setattr("src.api.routes.ai_advisor.llm_keys_configured", lambda: True)
