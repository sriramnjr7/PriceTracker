"""Unit tests for enhanced Casio scraper, prefix classifier, and catalog sweep."""

import pytest
from config import Settings
from scrapers.casio import CasioScraper
from brand_validator import BrandValidator, BrandStatus


@pytest.fixture
def casio_scraper():
    return CasioScraper(Settings())


def test_classify_casio_gshock_prefix(casio_scraper):
    family, formatted = casio_scraper._classify_casio_watch("GA-2100-1A1", ["RESIN"], "casio-g-shock-ga-2100-1adr")
    assert family == "G-Shock"
    assert "Casio G-Shock" in formatted
    assert "GA-2100-1A1" in formatted


def test_classify_casio_edifice_prefix(casio_scraper):
    family, formatted = casio_scraper._classify_casio_watch("EFB-730D-3A", ["100PGP"], "efb-730d-3a")
    assert family == "Edifice"
    assert "Casio Edifice" in formatted
    assert "EFB-730D-3A" in formatted


def test_classify_casio_mtp_vt03d(casio_scraper):
    family, formatted = casio_scraper._classify_casio_watch(
        "MTP-VT03D-1B",
        ["CASIO-MENS-METAL", "silent_sale_product"],
        "casio-mtp-vt03d-1bdf-black-analog-mens-watch"
    )
    assert family == "Casio"
    assert formatted == "Casio MTP-VT03D-1B"


def test_classify_casio_vintage(casio_scraper):
    family, formatted = casio_scraper._classify_casio_watch(
        "A1000MPG-9",
        ["A-1000", "VINTAGE"],
        "casio-vintage-a1000mpg-9ef-rose-gold"
    )
    assert family == "Vintage"
    assert "Casio Vintage" in formatted


def test_brand_validator_trusted_casio_bypass():
    validator = BrandValidator()
    result = validator.validate(
        scraped_brand="Casio",
        title="Casio MTP-VT03D-1B",
        target_brands=["casio", "g-shock", "edifice"],
        is_trusted_store=True
    )
    assert result.brand_status == BrandStatus.VERIFIED
    assert result.confidence_score >= 100
