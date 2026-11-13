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
