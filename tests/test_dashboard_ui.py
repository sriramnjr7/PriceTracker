import os
import re
import pytest

DASHBOARD_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "api", "dashboard.html")

def test_dashboard_file_exists():
    assert os.path.exists(DASHBOARD_PATH), "api/dashboard.html must exist"

def test_dashboard_required_element_ids():
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    required_ids = [
        # Main views & shells
        "login-view", "dashboard-view", "app-sidebar",
        # Topbar & search
        "catalog-search", "catalog-status-indicator",
        # Tab content containers
        "tab-content-dashboard", "tab-content-collection",
        "tab-content-shoes", "tab-content-logs",
        # Products & Feed
        "products-container", "deals-feed-container",
        # Collection elements
        "collection-items-container", "col-stat-total", "col-stat-watches",
        "col-stat-shoes", "col-stat-brands", "col-stat-valuation",
        "collection-search-input", "col-category-pills",
        # Running shoes elements
        "shoes-deals-container", "shoes-master-toggle", "shoes-search-input",
        # Logs elements
        "log-terminal-stream", "log-daemon-chip", "issues-spotlight-card",
        # Modals
        "add-product-modal", "price-history-modal", "modal-edit-target",
        "collection-detail-modal", "collection-form-modal",
        # Toast
        "toast-pill"
    ]

    for rid in required_ids:
        pattern = rf'id=["\']{re.escape(rid)}["\']'
        assert re.search(pattern, html), f"Required element ID '{rid}' must exist in api/dashboard.html"

def test_dashboard_required_js_functions():
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    required_fns = [
        "switchNavTab", "handleAuthLogin", "handleSignOut",
        "triggerManualSweep", "openAddProductModal", "closeAddProductModal",
        "submitNewProduct", "openPriceHistoryModal", "closePriceHistoryModal",
        "openEditTargetModal", "closeEditTargetModal", "submitEditTargetPrice",
        "fetchCollectionData", "renderCollectionCards", "openCollectionDetailModal",
        "closeCollectionDetailModal", "openCollectionFormModal", "closeCollectionFormModal",
        "resetCollectionToDefaults", "handleShoesToggle", "handleShoesSweepClick",
        "fetchLogsData", "probeVIPNow", "showToast"
    ]

    for fn in required_fns:
        assert f"function {fn}" in html or f"async function {fn}" in html, (
            f"Required JS function '{fn}' must exist in api/dashboard.html"
        )

def test_dashboard_css_bracket_balance():
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    css_match = re.search(r"<style>(.*?)</style>", html, re.DOTALL)
    assert css_match, "api/dashboard.html must contain a <style> block"
    css = css_match.group(1)

    open_count = 0
    clean_css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    for ch in clean_css:
        if ch == "{":
            open_count += 1
        elif ch == "}":
            open_count -= 1
            assert open_count >= 0, "CSS has unbalanced closing braces '}'"
    assert open_count == 0, f"CSS has unbalanced open braces '{open_count}'"

def test_dashboard_no_deprecated_italics():
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    assert "font-style: italic" not in html and "font-style:italic" not in html, (
        "api/dashboard.html must not use font-style: italic according to redesign values"
    )

def test_dashboard_uses_geist_fonts():
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    assert "Geist" in html, "api/dashboard.html must include Geist font family"
    assert "tabular-nums" in html, "api/dashboard.html must include tabular-nums for numeric precision"

def test_dashboard_no_legacy_neon_tokens():
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    assert "#00ffa3" not in html, "api/dashboard.html must not use legacy neon #00ffa3"
    assert not re.search(r"0,\s*255,\s*163", html), "api/dashboard.html must not use legacy neon rgba(0, 255, 163)"

def test_dashboard_chart_uses_geist():
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    assert "titleFont: { family: \"'Geist'" in html or "titleFont: { family: \"'Geist" in html, (
        "Chart.js titleFont must use Geist font family"
    )
    assert "'Inter', sans-serif" not in html, "api/dashboard.html must not hardcode 'Inter', sans-serif"

def test_dashboard_viewport_and_dvh():
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    assert "min-height: 100dvh;" in html, "api/dashboard.html must include 100dvh for mobile Safari support"
    assert "max-width: 360px" in html, "api/dashboard.html must include responsive styling for narrow viewports <= 360px"

def test_dashboard_accessibility_and_meta():
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    assert '<meta name="description"' in html, "api/dashboard.html must include meta description"
    assert '<meta property="og:title"' in html, "api/dashboard.html must include OpenGraph meta title"
    assert 'class="skip-to-content"' in html, "api/dashboard.html must include skip-to-content accessibility link"

def test_my_collection_auth_gating():
    """Ensure /my-collection is strictly gated behind authentication and has no bypass."""
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    # Ensure initAuthFlow does not bypass login for collection route
    init_auth_match = re.search(r"async\s+function\s+initAuthFlow\s*\(\)\s*\{(.*?)\}\s*function\s+onAuthenticated", html, re.DOTALL)
    assert init_auth_match is not None, "initAuthFlow function must exist"
    init_auth_body = init_auth_match.group(1)
    assert "route.includes" not in init_auth_body, "initAuthFlow must not contain route bypass for collection"
    assert 'showView("login-view")' in init_auth_body, "initAuthFlow must show login-view when unauthenticated"

    # Ensure switchNavTab requires authentication for all tabs
    switch_tab_match = re.search(r"function\s+switchNavTab\s*\([^)]*\)\s*\{(.*?)\}\s*currentActiveTab\s*=", html, re.DOTALL)
    assert switch_tab_match is not None, "switchNavTab function must exist"
    switch_tab_body = switch_tab_match.group(1)
    assert 'localStorage.getItem("sritrack_authenticated") !== "true"' in switch_tab_body
    assert 'showView("login-view")' in switch_tab_body

def test_page_header_layout_and_spacing_css():
    """Ensure page title, header row, and action buttons have explicit CSS rules and spacing."""
    with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    assert ".page-title-section" in html, "CSS must define .page-title-section"
    assert ".page-header-row" in html, "CSS must define .page-header-row"
    assert ".collection-header-actions" in html, "CSS must define .collection-header-actions"
    assert ".page-heading" in html, "CSS must define .page-heading"
    assert ".page-subheading" in html, "CSS must define .page-subheading"


