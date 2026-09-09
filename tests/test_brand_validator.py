"""Comprehensive unit tests for the confidence-based Brand Validation Engine.

Tests every false-positive scenario from the implementation requirements,
plus edge cases for normalization, compatibility detection, and unknown brands.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from brand_validator import (
    BrandValidator,
    BrandStatus,
    BrandValidationResult,
    normalize_brand,
    _brands_match,
)


@pytest.fixture
def validator():
    return BrandValidator(allow_unknown=False)


@pytest.fixture
def validator_allow_unknown():
    return BrandValidator(allow_unknown=True)


# ---------------------------------------------------------------------------
# Mandatory Test Cases from Requirements (A through G)
# ---------------------------------------------------------------------------

class TestMandatoryFalsePositives:
    """The exact test cases specified in the implementation requirements."""

    def test_A_siwi_earbuds_for_samsung(self, validator):
        """brand=Siwi, title mentions Samsung → REJECT."""
        result = validator.validate(
            scraped_brand="Siwi",
            title="Wireless Earbuds for Samsung Galaxy S III | Mini Value, Samsung Galaxy S III Next, Samsung Galaxy S 4 GT959, Samsung Galaxy S Advance Wireless Earbuds",
            target_brands=["samsung", "galaxy"],
        )
        assert result.brand_status == BrandStatus.REJECTED, f"Expected REJECTED, got {result.brand_status.value}: {result.filter_reason}"
        assert result.scraped_brand == "Siwi"
        assert result.confidence_score < 0

    def test_B_spigen_case_for_samsung(self, validator):
        """brand=Spigen, title is a case for Samsung → REJECT."""
        result = validator.validate(
            scraped_brand="Spigen",
            title="Spigen Case for Samsung Galaxy S24 Ultra",
            target_brands=["samsung", "galaxy"],
        )
        assert result.brand_status == BrandStatus.REJECTED, f"Expected REJECTED, got {result.brand_status.value}: {result.filter_reason}"

    def test_C_samsung_galaxy_s24(self, validator):
        """brand=Samsung, genuine Samsung product → ACCEPT."""
        result = validator.validate(
            scraped_brand="Samsung",
            title="Samsung Galaxy S24 256GB Phantom Black",
            target_brands=["samsung", "galaxy"],
        )
        assert result.brand_status == BrandStatus.VERIFIED, f"Expected VERIFIED, got {result.brand_status.value}: {result.filter_reason}"
        assert result.confidence_score >= 50

    def test_D_samsung_990_pro_ssd(self, validator):
        """brand=Samsung, Samsung SSD → ACCEPT."""
        result = validator.validate(
            scraped_brand="Samsung",
            title="Samsung 990 Pro 2TB NVMe SSD",
            target_brands=["samsung"],
        )
        assert result.brand_status == BrandStatus.VERIFIED

    def test_E_unknown_brand_samsung_title(self, validator):
        """brand=None, title says Samsung → UNKNOWN (rejected by default)."""
        result = validator.validate(
            scraped_brand=None,
            title="Samsung Galaxy S24 Ultra 256GB",
            target_brands=["samsung"],
        )
        assert result.brand_status in (BrandStatus.UNKNOWN, BrandStatus.REJECTED), \
            f"Expected UNKNOWN or REJECTED, got {result.brand_status.value}"
        # With allow_unknown=False, this should NOT be VERIFIED
        assert result.brand_status != BrandStatus.VERIFIED

    def test_F_sony_headphones_compatible_with_samsung(self, validator):
        """brand=Sony, headphones compatible with Samsung → REJECT for Samsung target."""
        result = validator.validate(
            scraped_brand="Sony",
            title="Sony Headphones compatible with Samsung TV",
            target_brands=["samsung"],
        )
        assert result.brand_status == BrandStatus.REJECTED

    def test_G_samsung_galaxy_buds(self, validator):
        """brand=Samsung, genuine Samsung earbuds → ACCEPT."""
        result = validator.validate(
            scraped_brand="Samsung",
            title="Samsung Galaxy Buds FE",
            target_brands=["samsung", "galaxy"],
        )
        assert result.brand_status == BrandStatus.VERIFIED


# ---------------------------------------------------------------------------
# Extended False-Positive Tests
# ---------------------------------------------------------------------------

class TestExtendedFalsePositives:
    """Additional false-positive scenarios across multiple brands."""

    def test_spigen_case_for_iphone(self, validator):
        """brand=Spigen, case for iPhone → REJECT for Apple target."""
        result = validator.validate(
            scraped_brand="Spigen",
            title="Spigen case for iPhone 15 Pro Max",
            target_brands=["apple", "iphone"],
        )
        assert result.brand_status == BrandStatus.REJECTED

    def test_generic_charger_for_samsung(self, validator):
        """brand=URBN, charger for Samsung → REJECT."""
        result = validator.validate(
            scraped_brand="URBN",
            title="URBN 65W GaN USB-C Charger for Samsung Galaxy S24",
            target_brands=["samsung"],
        )
        assert result.brand_status == BrandStatus.REJECTED

    def test_redtape_clogs_not_crocs(self, validator):
        """brand=Red Tape, clogs product → REJECT for Crocs target."""
        result = validator.validate(
            scraped_brand="Red Tape",
            title="Red Tape Men Solid Clogs",
            target_brands=["crocs"],
        )
        assert result.brand_status == BrandStatus.REJECTED

    def test_bata_clogs_not_crocs(self, validator):
        """brand=Bata, clogs → REJECT for Crocs target."""
        result = validator.validate(
            scraped_brand="Bata",
            title="Bata Comfit Lightweight Clogs",
            target_brands=["crocs"],
        )
        assert result.brand_status == BrandStatus.REJECTED

    def test_genuine_crocs_clog(self, validator):
        """brand=Crocs, genuine Crocs → ACCEPT."""
        result = validator.validate(
            scraped_brand="Crocs",
            title="Crocs Unisex Bayaband Navy Clog",
            target_brands=["crocs"],
        )
        assert result.brand_status == BrandStatus.VERIFIED

    def test_earbuds_for_apple_not_apple_product(self, validator):
        """Third-party earbuds compatible with Apple → REJECT."""
        result = validator.validate(
            scraped_brand="boAt",
            title="boAt Airdopes 141 Earbuds compatible with Apple iPhone 15",
            target_brands=["apple", "iphone"],
        )
        assert result.brand_status == BrandStatus.REJECTED

    def test_genuine_apple_airpods(self, validator):
        """brand=Apple, genuine AirPods → ACCEPT."""
        result = validator.validate(
            scraped_brand="Apple",
            title="Apple AirPods Pro 2nd Gen with USB-C",
            target_brands=["apple", "airpods"],
        )
        assert result.brand_status == BrandStatus.VERIFIED

    def test_cable_for_nothing_phone(self, validator):
        """brand=Portronics, cable for Nothing → REJECT."""
        result = validator.validate(
            scraped_brand="Portronics",
            title="Portronics USB-C Cable for Nothing Phone 2a",
            target_brands=["nothing", "cmf"],
        )
        assert result.brand_status == BrandStatus.REJECTED

    def test_genuine_nothing_cmf_buds(self, validator):
        """brand=Nothing, genuine CMF product → ACCEPT (via alias)."""
        result = validator.validate(
            scraped_brand="CMF by Nothing",
            title="CMF by Nothing Buds Pro 2 Wireless Earbuds",
            target_brands=["nothing", "cmf"],
        )
        assert result.brand_status == BrandStatus.VERIFIED

    def test_casio_watch_genuine(self, validator):
        """brand=Casio, genuine G-Shock → ACCEPT."""
        result = validator.validate(
            scraped_brand="Casio",
            title="Casio G-Shock GA-2100-1A1DR Analog-Digital Watch",
            target_brands=["casio", "g-shock"],
        )
        assert result.brand_status == BrandStatus.VERIFIED

    def test_strap_for_casio_third_party(self, validator):
        """Third-party strap for Casio → REJECT."""
        result = validator.validate(
            scraped_brand="Watchbands",
            title="Replacement Resin Strap for Casio G-Shock DW-5600",
            target_brands=["casio", "g-shock"],
        )
        assert result.brand_status == BrandStatus.REJECTED

    def test_logitech_mouse_genuine(self, validator):
        """brand=Logitech, genuine mouse → ACCEPT."""
        result = validator.validate(
            scraped_brand="Logitech",
            title="Logitech MX Master 3S Wireless Mouse",
            target_brands=["logitech"],
        )
        assert result.brand_status == BrandStatus.VERIFIED

    def test_sony_wh1000xm6_genuine(self, validator):
        """brand=Sony, genuine headphones → ACCEPT."""
        result = validator.validate(
            scraped_brand="Sony",
            title="Sony WH-1000XM6 Wireless Noise Cancelling Headphones",
            target_brands=["sony"],
        )
        assert result.brand_status == BrandStatus.VERIFIED

    def test_replacement_screen_for_samsung(self, validator):
        """Third-party replacement screen for Samsung → REJECT."""
        result = validator.validate(
            scraped_brand="iFixit",
            title="iFixit Replacement Screen for Samsung Galaxy S23",
            target_brands=["samsung"],
        )
        assert result.brand_status == BrandStatus.REJECTED


# ---------------------------------------------------------------------------
# Brand Normalization Tests
# ---------------------------------------------------------------------------

class TestBrandNormalization:
    def test_samsung_variants(self):
        assert normalize_brand("Samsung") == "samsung"
        assert normalize_brand("SAMSUNG") == "samsung"
        assert normalize_brand("Samsung Electronics") == "samsung"
        assert normalize_brand("  Samsung  India  ") == "samsung"

    def test_apple_variants(self):
        assert normalize_brand("Apple") == "apple"
        assert normalize_brand("Apple Inc.") == "apple"
        assert normalize_brand("Apple Inc") == "apple"

    def test_nothing_cmf_aliases(self):
        assert normalize_brand("CMF by Nothing") == "nothing"
        assert normalize_brand("CMF") == "nothing"
        assert normalize_brand("Nothing Technology") == "nothing"

    def test_xiaomi_aliases(self):
        assert normalize_brand("Xiaomi") == "xiaomi"
        assert normalize_brand("Redmi") == "xiaomi"
        assert normalize_brand("Mi India") == "xiaomi"

    def test_empty_values(self):
        assert normalize_brand(None) is None
        assert normalize_brand("") is None
        assert normalize_brand("  ") is None
        assert normalize_brand("Unknown") is None
        assert normalize_brand("N/A") is None
        assert normalize_brand("Generic") is None
        assert normalize_brand("Unbranded") is None

    def test_html_entity_cleaning(self):
        assert normalize_brand("Samsung&amp;Co") is not None
        assert normalize_brand("Apple&#39;s") is not None


# ---------------------------------------------------------------------------
# Brands Match Tests
# ---------------------------------------------------------------------------

class TestBrandsMatch:
    def test_exact_match(self):
        assert _brands_match("samsung", "samsung") is True

    def test_prefix_match(self):
        assert _brands_match("samsung", "samsung electronics") is True

    def test_no_match(self):
        assert _brands_match("siwi", "samsung") is False
        assert _brands_match("spigen", "samsung") is False

    def test_none_values(self):
        assert _brands_match(None, "samsung") is False
        assert _brands_match("samsung", None) is False
        assert _brands_match(None, None) is False


# ---------------------------------------------------------------------------
# Compatibility Detection Tests
# ---------------------------------------------------------------------------

class TestCompatibilityDetection:
    """Test that "for <brand>", "compatible with <brand>" etc. are detected."""

    def test_for_samsung(self, validator):
        result = validator.validate(
            scraped_brand="Siwi",
            title="Wireless Earbuds for Samsung Galaxy",
            target_brands=["samsung"],
        )
        assert result.matched_compatibility_phrase is not None
        assert result.brand_status == BrandStatus.REJECTED

    def test_compatible_with_apple(self, validator):
        result = validator.validate(
            scraped_brand="Anker",
            title="Anker Charger compatible with Apple iPhone 15",
            target_brands=["apple"],
        )
        assert result.matched_compatibility_phrase is not None
        assert result.brand_status == BrandStatus.REJECTED

    def test_fits_crocs(self, validator):
        result = validator.validate(
            scraped_brand="Generic",  # gets normalized to None
            title="Jibbitz Charms that fits Crocs Classic",
            target_brands=["crocs"],
        )
        assert result.brand_status == BrandStatus.REJECTED

    def test_replacement_for_casio(self, validator):
        result = validator.validate(
            scraped_brand="StrapsCo",
            title="StrapsCo Replacement Strap for Casio G-Shock",
            target_brands=["casio"],
        )
        assert result.matched_compatibility_phrase is not None
        assert result.brand_status == BrandStatus.REJECTED


# ---------------------------------------------------------------------------
# Score / Confidence Tests
# ---------------------------------------------------------------------------

class TestConfidenceScoring:
    """Verify the scoring arithmetic produces correct decisions."""

    def test_explicit_brand_match_scores_100(self, validator):
        result = validator.validate(
            scraped_brand="Samsung",
            title="Samsung Galaxy S24",
            target_brands=["samsung"],
        )
        # Should have BRAND_MATCH_EXACT (+100) + TITLE_BRAND_PRIMARY (+50)
        assert result.confidence_score >= 100

    def test_explicit_other_brand_scores_negative(self, validator):
        result = validator.validate(
            scraped_brand="Siwi",
            title="Earbuds for Samsung Galaxy",
            target_brands=["samsung"],
        )
        # EXPLICIT_OTHER_BRAND (-150) + COMPATIBILITY_CONTEXT (-100) + TITLE_CONTAINS (+10)
        assert result.confidence_score < -100

    def test_title_only_brand_no_explicit_is_unknown(self, validator):
        """Brand in title but no explicit brand → UNKNOWN (title alone cannot verify)."""
        result = validator.validate(
            scraped_brand=None,
            title="Samsung Galaxy S24 Ultra",
            target_brands=["samsung"],
        )
        # Title-only brand presence without explicit data → UNKNOWN
        assert result.brand_status == BrandStatus.UNKNOWN


# ---------------------------------------------------------------------------
# Filter Reason / Audit Trail Tests
# ---------------------------------------------------------------------------

class TestAuditTrail:
    def test_rejection_has_reason(self, validator):
        result = validator.validate(
            scraped_brand="Siwi",
            title="Earbuds for Samsung Galaxy",
            target_brands=["samsung"],
        )
        assert result.filter_reason
        assert "Siwi" in result.filter_reason or "siwi" in result.filter_reason.lower()

    def test_verification_has_reason(self, validator):
        result = validator.validate(
            scraped_brand="Samsung",
            title="Samsung Galaxy S24",
            target_brands=["samsung"],
        )
        assert result.filter_reason
        assert "verified" in result.filter_reason.lower() or "samsung" in result.filter_reason.lower()

    def test_signals_list_populated(self, validator):
        result = validator.validate(
            scraped_brand="Siwi",
            title="Earbuds for Samsung Galaxy S24",
            target_brands=["samsung"],
        )
        assert len(result.signals) >= 2  # At least EXPLICIT_OTHER_BRAND + COMPATIBILITY_CONTEXT


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_title(self, validator):
        result = validator.validate(
            scraped_brand="Samsung",
            title="",
            target_brands=["samsung"],
        )
        # Explicit brand matches, so should be VERIFIED even with empty title
        assert result.brand_status == BrandStatus.VERIFIED

    def test_empty_target_brands(self, validator):
        result = validator.validate(
            scraped_brand="Samsung",
            title="Samsung Galaxy S24",
            target_brands=[],
        )
        # No target to match against
        assert result.brand_status in (BrandStatus.UNKNOWN, BrandStatus.REJECTED)

    def test_multiple_target_brands_any_match(self, validator):
        """Should verify if explicit brand matches ANY of the target brands."""
        result = validator.validate(
            scraped_brand="Yamaha",
            title="Yamaha F310 Acoustic Guitar",
            target_brands=["yamaha", "fender", "ibanez"],
        )
        assert result.brand_status == BrandStatus.VERIFIED

    def test_manufacturer_field(self, validator):
        """Manufacturer match should contribute to score."""
        result = validator.validate(
            scraped_brand=None,
            title="Galaxy S24 Ultra 256GB",
            target_brands=["samsung"],
            manufacturer="Samsung Electronics",
        )
        # manufacturer match (+80) should bring score to at least 80
        assert result.confidence_score >= 80
        assert result.brand_status == BrandStatus.VERIFIED


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
