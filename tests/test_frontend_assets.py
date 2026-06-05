"""
Frontend static-asset smoke tests.

What this catches
─────────────────
The Python test suite can't run JavaScript, but it CAN protect against the
most common regressions: a refactor accidentally deleting a DOM element the
JS depends on, or removing a window-exposed handler that an `onclick=` calls.

Each assertion documents a specific contract between index.html and app.js.
When you remove or rename a mount point, you'll see a clear failure here
pointing at exactly what depends on it.

For real interaction tests (login flow, portfolio rendering) use the
existing API-level tests in test_users.py / test_user_alerts.py —
they exercise everything the JS calls into.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


@pytest.fixture(scope="module")
def index_html() -> str:
    return (FRONTEND / "index.html").read_text()


@pytest.fixture(scope="module")
def app_js() -> str:
    return (FRONTEND / "app.js").read_text()


@pytest.fixture(scope="module")
def styles_css() -> str:
    return (FRONTEND / "styles.css").read_text()


# ── Files exist and are non-trivial ───────────────────────────────────────────

def test_frontend_files_present():
    for name in ("index.html", "app.js", "styles.css"):
        path = FRONTEND / name
        assert path.exists(), f"{name} missing"
        assert path.stat().st_size > 1024, f"{name} suspiciously small"


# ── DOM mount-point contracts ────────────────────────────────────────────────

@pytest.mark.parametrize("element_id", [
    # Core dashboard widgets
    "tickerInput", "analyzeBtn", "companiesBody", "sectorChart",
    "companyDetail", "bcsiHero", "bcsiDims", "accordion",
    "liveIndicator",
    # Auth widget (v0.3.0 frontend)
    "userBtn", "authMenu", "authForms", "authProfile",
    "loginForm", "registerForm",
    "loginUsername", "loginPassword",
    "regUsername", "regEmail", "regPassword",
    # Portfolio + alerts panels
    "portfolioSection", "portfolioBody", "portfolioEmpty",
    "pfCount", "pfBcsi", "pfRisk", "pfMomentum",
    "pfSectors", "pfHighlights", "pfMissing",
    "alertsSection", "alertsList",
    "alertTicker", "alertCondition", "alertThreshold",
])
def test_index_html_has_required_mount_point(index_html, element_id):
    """app.js binds to these IDs — deleting one breaks the UI silently."""
    assert f'id="{element_id}"' in index_html, \
        f"missing #{element_id} in index.html — would break app.js binding"


# ── Window-exposed handlers ──────────────────────────────────────────────────

@pytest.mark.parametrize("handler", [
    "analyzeCompany", "filterCompanies", "toggleSection",
    # Auth
    "toggleAuthMenu", "switchAuthTab", "submitLogin", "submitRegister",
    "logout",
    # User-scoped views
    "refreshPortfolio", "refreshAlerts", "submitAlert", "deleteAlert",
])
def test_app_js_exposes_handler_on_window(app_js, handler):
    """Inline `onclick="someHandler()"` requires the function on window."""
    assert re.search(rf"window\.{handler}\s*=", app_js), \
        f"window.{handler} not exposed in app.js — onclick handlers will fail"


# ── Backend↔frontend endpoint contracts ──────────────────────────────────────

@pytest.mark.parametrize("suffix", [
    # Path *after* the /api/v1 prefix (app.js now constructs full URLs as
    # `API + "/..."` or `${API}/...` so we look for the suffix the call
    # appends to the API constant).  This keeps the contract test useful
    # while tolerating the BACKEND_BASE-aware refactor for split deploys.
    "/auth/register",
    "/auth/login",
    "/auth/token",
    "/users/me",
    "/users/me/portfolio",
    "/users/me/alerts",
    "/lookup",                  # ticker name → symbol autocomplete
])
def test_app_js_calls_expected_backend_path(app_js, suffix):
    """If a route is renamed on the backend, the matching JS call breaks."""
    # Either via fetch(API + "...") or apiFetch(API + "...") or fetch(`${API}...`)
    expected_variants = [
        f'API + "{suffix}"',
        f"API + '{suffix}'",
        f"${{API}}{suffix}",
    ]
    assert any(v in app_js for v in expected_variants), \
        f"app.js no longer calls {suffix} — rename in lockstep with backend " \
        f"(checked variants: {expected_variants})"


def test_app_js_uses_backend_base_constant(app_js):
    """The BACKEND_BASE override hook must be present so split deploys work."""
    assert "BACKEND_BASE" in app_js, \
        "frontend lost the BACKEND_BASE constant — split deploys will break"
    assert "window.BCSI_BACKEND_URL" in app_js, \
        "frontend doesn't read window.BCSI_BACKEND_URL — index.html override " \
        "won't take effect"


def test_index_html_has_backend_url_override_hook(index_html):
    """index.html must declare the window.BCSI_BACKEND_URL placeholder so
    deploy targets can override the backend domain in one line."""
    assert "BCSI_BACKEND_URL" in index_html, \
        "index.html missing the window.BCSI_BACKEND_URL placeholder script"


# ── Script + stylesheet linkage ──────────────────────────────────────────────

def test_index_links_app_js_and_styles(index_html):
    assert 'src="/static/app.js"'        in index_html
    assert 'href="/static/styles.css"'   in index_html


def test_no_stale_pending_momentum_text(app_js):
    """v0.3.0 wired Momentum in — the old 'pending Phase 7' note must be gone."""
    assert "pending — Phase 7" not in app_js, \
        "Stale Momentum 'pending' note found in app.js — remove it."


def test_styles_define_new_v04_classes(styles_css):
    """Sanity-check the v0.4.0 CSS classes the JS adds dynamically."""
    for cls in (".user-widget", ".auth-menu", ".alerts-list", ".alert-form",
                ".portfolio-stats", ".pf-missing-note"):
        assert cls in styles_css, f"missing CSS rule for {cls}"
