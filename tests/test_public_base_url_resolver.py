"""
Tests for Settings.resolved_public_base_url().

This helper is what backend.api.routes uses to build the verification + reset
links in outgoing emails.  On Render we deliberately leave PUBLIC_BASE_URL
unset in the blueprint (Render's schema doesn't let us auto-resolve it),
and rely on Render's runtime RENDER_EXTERNAL_URL injection instead.  These
tests pin that resolution order so a future refactor can't silently break
email links the day after a fresh Render deploy.
"""

from __future__ import annotations

from backend.config import Settings


def test_explicit_public_base_url_wins(monkeypatch):
    """If the operator sets PUBLIC_BASE_URL, that's what gets used."""
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://bcsi-web.onrender.com")
    s = Settings(public_base_url="https://app.example.com")
    assert s.resolved_public_base_url() == "https://app.example.com"


def test_falls_back_to_render_external_url(monkeypatch):
    """Default PUBLIC_BASE_URL + RENDER_EXTERNAL_URL set → use Render's URL."""
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://bcsi-web.onrender.com")
    s = Settings()                              # leaves the localhost default
    assert s.resolved_public_base_url() == "https://bcsi-web.onrender.com"


def test_strips_trailing_slash(monkeypatch):
    """No trailing slash — email links concatenate `/api/v1/auth/verify?...`."""
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://bcsi-web.onrender.com/")
    s = Settings()
    assert s.resolved_public_base_url() == "https://bcsi-web.onrender.com"

    s2 = Settings(public_base_url="https://app.example.com/")
    assert s2.resolved_public_base_url() == "https://app.example.com"


def test_localhost_default_when_nothing_set(monkeypatch):
    """Dev / docker-compose path — no env, default base URL."""
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    s = Settings()
    assert s.resolved_public_base_url() == "http://localhost:8000"


def test_explicit_setting_beats_render_url_even_when_both_set(monkeypatch):
    """If both are set, PUBLIC_BASE_URL wins — operator override is explicit."""
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://render-default.onrender.com")
    s = Settings(public_base_url="https://custom-domain.com")
    assert s.resolved_public_base_url() == "https://custom-domain.com"
