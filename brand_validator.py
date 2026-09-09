"""Confidence-based Brand Validation Engine.

Determines whether a scraped product genuinely belongs to a target brand
using structured metadata (explicit brand field, manufacturer) prioritized
over title keyword heuristics. Prevents false positives such as third-party
accessories that merely mention the target brand in their title.

Architecture principle:
    Explicit brand field > manufacturer > title-primary-brand > title keyword.
    An explicit different brand ALWAYS overrides title keyword matching.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("brand_validator")


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

class BrandStatus(Enum):
    """Outcome of brand validation."""
    VERIFIED = "VERIFIED"   # Explicit brand matches target
    REJECTED = "REJECTED"   # Explicit brand contradicts target, or compatibility context
    UNKNOWN  = "UNKNOWN"    # No explicit brand; insufficient evidence


@dataclass
class BrandSignal:
    """A single piece of evidence contributing to the confidence score."""
    name: str
    score: int
    detail: str


@dataclass
class BrandValidationResult:
    """Full audit trail for a brand validation decision."""
    brand_status: BrandStatus
    scraped_brand: Optional[str]
    normalized_brand: Optional[str]
    target_brand: str
    confidence_score: float       # sum of signal scores
    filter_reason: str
    signals: list[BrandSignal] = field(default_factory=list)
    matched_compatibility_phrase: Optional[str] = None


# ---------------------------------------------------------------------------
# Score Constants
# ---------------------------------------------------------------------------

SCORE_BRAND_MATCH_EXACT       =  100
SCORE_STRUCTURED_BRAND_MATCH  =  100
SCORE_MANUFACTURER_MATCH      =   80
SCORE_TITLE_BRAND_PRIMARY     =   50   # Brand appears at/near start of title
SCORE_TITLE_CONTAINS_BRAND    =   10   # Brand mentioned anywhere in title

SCORE_FOR_BRAND               = -100   # "for Samsung"
SCORE_COMPATIBLE_WITH         = -100   # "compatible with Samsung"
SCORE_REPLACEMENT_FOR         = -100   # "replacement for Samsung"
SCORE_ACCESSORY_FOR           = -100   # "case for Samsung"
SCORE_EXPLICIT_OTHER_BRAND    = -150   # Scraped brand is a *different* known entity

# Decision thresholds
THRESHOLD_VERIFIED =  50
THRESHOLD_REJECTED =   0   # score < 0 → REJECTED


# ---------------------------------------------------------------------------
# Compatibility / Accessory Patterns (compiled once, reused)
# ---------------------------------------------------------------------------

# Preposition phrases that indicate the target brand is a *device* being
# accessorized, not the *product* brand.
_COMPAT_PREPOSITIONS = (
    r"for",
    r"compatible\s+with",
    r"fits",
    r"works\s+with",
    r"designed\s+for",
    r"made\s+for",
    r"suitable\s+for",
    r"replacement\s+for",
    r"supported\s+by",
)

# Accessory product nouns — when these precede "for <brand>", it is almost
# certainly an accessory listing.
_ACCESSORY_NOUNS = (
    r"case", r"cover", r"charger", r"cable", r"battery", r"screen",
    r"protector", r"stand", r"mount", r"strap", r"band", r"earbuds",
    r"headset", r"adapter", r"pouch", r"sleeve", r"holder", r"dock",
    r"keyboard", r"mouse", r"stylus", r"pen", r"tempered\s+glass",
    r"back\s+cover", r"skin", r"film", r"guard", r"clip", r"cradle",
    r"earpad", r"ear\s+pad", r"ear\s+tip", r"nib", r"refill",
    r"replacement\s+strap", r"silicone\s+strap", r"resin\s+strap",
    r"replacement\s+band", r"spring\s+bar", r"bezel",
    r"charms?", r"jibbitz", r"pins?",
)


def _build_compat_regex(brand: str) -> re.Pattern:
    """Build a compiled regex that detects compatibility phrasing around a brand."""
    escaped = re.escape(brand)
    preps = "|".join(_COMPAT_PREPOSITIONS)
    # Pattern A: "<preposition> <brand>" anywhere in title
    #   e.g. "for Samsung", "compatible with Apple", "fits Crocs"
    pat_a = rf"\b(?:{preps})\s+{escaped}\b"
    # Pattern B: "<accessory_noun> <preposition> <brand>"
    #   e.g. "case for Samsung Galaxy", "strap for Casio G-Shock"
    nouns = "|".join(_ACCESSORY_NOUNS)
    pat_b = rf"\b(?:{nouns})\s+(?:{preps})\s+{escaped}\b"
    combined = rf"(?:{pat_b})|(?:{pat_a})"
    return re.compile(combined, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Brand Normalization
# ---------------------------------------------------------------------------

# Common brand aliases → canonical name
_BRAND_ALIASES: dict[str, str] = {
    "samsung electronics":   "samsung",
    "samsung india":         "samsung",
    "apple inc":             "apple",
    "apple inc.":            "apple",
    "apple india":           "apple",
    "sony india":            "sony",
    "sony corporation":      "sony",
    "xiaomi india":          "xiaomi",
    "xiaomi technology":     "xiaomi",
    "redmi":                 "xiaomi",
    "redmi india":           "xiaomi",
    "mi":                    "xiaomi",
    "mi india":              "xiaomi",
    "realme india":          "realme",
    "realme mobile":         "realme",
    "nothing technology":    "nothing",
    "nothing india":         "nothing",
    "cmf by nothing":        "nothing",
    "cmf":                   "nothing",
    "casio india":           "casio",
    "casio computer":        "casio",
    "g-shock":               "casio",
    "gshock":                "casio",
    "crocs india":           "crocs",
    "crocs inc":             "crocs",
    "crocs inc.":            "crocs",
    "wakefit innovations":   "wakefit",
    "wakefit india":         "wakefit",
    "amazonbasics":          "amazonbasics",
    "amazon basics":         "amazonbasics",
    "yamaha music":          "yamaha",
    "yamaha india":          "yamaha",
}


def normalize_brand(raw: Optional[str]) -> Optional[str]:
    """Normalize a raw brand string to a canonical lowercase form.

    Strips whitespace, HTML entities, collapses spaces, and maps known aliases.
    Returns ``None`` if the input is empty or obviously meaningless.
    """
    if not raw:
        return None
    # Early check for known empty/placeholder values (before stripping punctuation)
    raw_check = raw.strip().lower()
    if raw_check in {"na", "n/a", "unknown", "generic", "unbranded", "other", "-", "--", "null", "none", ""}:
        return None
    # Strip HTML entities and non-printable characters
    cleaned = re.sub(r"&[a-zA-Z]+;|&#\d+;", " ", raw)
    cleaned = re.sub(r"[^\w\s.\-']", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    if not cleaned or cleaned in {"na", "n/a", "unknown", "generic", "unbranded", "other", "-", "--", "null", "none"}:
        return None
    # Check alias table
    canonical = _BRAND_ALIASES.get(cleaned)
    if canonical:
        return canonical
    return cleaned


def _brands_match(normalized_a: Optional[str], normalized_b: Optional[str]) -> bool:
    """Check if two normalized brands refer to the same entity."""
    if not normalized_a or not normalized_b:
        return False
    if normalized_a == normalized_b:
        return True
    # Handle prefix matching: "samsung" matches "samsung electronics"
    if normalized_a.startswith(normalized_b) or normalized_b.startswith(normalized_a):
        return True
    return False


# ---------------------------------------------------------------------------
# Main Validator
# ---------------------------------------------------------------------------

class BrandValidator:
    """Reusable, brand-agnostic product-brand validation engine.

    Usage::

        validator = BrandValidator()
        result = validator.validate(
            scraped_brand="Siwi",
            title="Wireless Earbuds for Samsung Galaxy S III...",
            target_brands=["samsung", "galaxy"],
        )
        assert result.brand_status == BrandStatus.REJECTED
    """

    def __init__(self, allow_unknown: bool = False):
        """
        Args:
            allow_unknown: If ``True``, products with no explicit brand are
                allowed through as UNKNOWN (caller decides).  If ``False``
                (default), UNKNOWN is treated the same as REJECTED.
        """
        self.allow_unknown = allow_unknown

    def validate(
        self,
        scraped_brand: Optional[str],
        title: str,
        target_brands: list[str],
        manufacturer: Optional[str] = None,
        is_trusted_store: bool = False,
    ) -> BrandValidationResult:
        """Evaluate whether a product belongs to the target brand.

        Args:
            scraped_brand: Explicit brand from structured product metadata.
            title: Full product title string.
            target_brands: List of acceptable brand names / aliases.
            manufacturer: Optional manufacturer field from product metadata.

        Returns:
            A ``BrandValidationResult`` with full audit trail.
        """
        signals: list[BrandSignal] = []
        score = 0
        compat_phrase: Optional[str] = None

        norm_scraped = normalize_brand(scraped_brand)
        norm_manufacturer = normalize_brand(manufacturer)

        # Normalize all target brands
        norm_targets = set()
        raw_target_label = target_brands[0] if target_brands else "Unknown"
        for tb in target_brands:
            nt = normalize_brand(tb)
            if nt:
                norm_targets.add(nt)
            else:
                norm_targets.add(tb.lower().strip())

        title_lower = title.lower()

        # ----- Signal 1: Explicit scraped brand -----
        if norm_scraped:
            if any(_brands_match(norm_scraped, nt) for nt in norm_targets):
                signals.append(BrandSignal(
                    "BRAND_MATCH_EXACT", SCORE_BRAND_MATCH_EXACT,
                    f"Explicit brand '{scraped_brand}' matches target.",
                ))
                score += SCORE_BRAND_MATCH_EXACT
            else:
                signals.append(BrandSignal(
                    "EXPLICIT_OTHER_BRAND", SCORE_EXPLICIT_OTHER_BRAND,
                    f"Explicit brand '{scraped_brand}' (normalized: '{norm_scraped}') "
                    f"does not match target brand(s) {list(norm_targets)}.",
                ))
                score += SCORE_EXPLICIT_OTHER_BRAND

        # ----- Signal 2: Manufacturer field -----
        if norm_manufacturer:
            if any(_brands_match(norm_manufacturer, nt) for nt in norm_targets):
                signals.append(BrandSignal(
                    "MANUFACTURER_MATCH", SCORE_MANUFACTURER_MATCH,
                    f"Manufacturer '{manufacturer}' matches target.",
                ))
                score += SCORE_MANUFACTURER_MATCH
            elif not norm_scraped:
                # Manufacturer is a different brand and there's no explicit brand
                signals.append(BrandSignal(
                    "EXPLICIT_OTHER_BRAND", SCORE_EXPLICIT_OTHER_BRAND,
                    f"Manufacturer '{manufacturer}' (normalized: '{norm_manufacturer}') "
                    f"does not match target.",
                ))
                score += SCORE_EXPLICIT_OTHER_BRAND

        # ----- Signal 3: Compatibility / accessory phrasing -----
        for tb in norm_targets:
            pat = _build_compat_regex(tb)
            match = pat.search(title_lower)
            if match:
                compat_phrase = match.group(0)
                signals.append(BrandSignal(
                    "COMPATIBILITY_CONTEXT", SCORE_FOR_BRAND,
                    f"Target brand appears in compatibility context: '{compat_phrase}'.",
                ))
                score += SCORE_FOR_BRAND
                break  # one match is enough

        # Also check for raw target brand names (un-normalized) in compat context
        if not compat_phrase:
            for raw_tb in target_brands:
                pat = _build_compat_regex(raw_tb)
                match = pat.search(title_lower)
                if match:
                    compat_phrase = match.group(0)
                    signals.append(BrandSignal(
                        "COMPATIBILITY_CONTEXT", SCORE_FOR_BRAND,
                        f"Target brand appears in compatibility context: '{compat_phrase}'.",
                    ))
                    score += SCORE_FOR_BRAND
                    break

        # ----- Signal 4: Title-based brand presence -----
        brand_in_title = False
        for tb_raw in target_brands:
            tb_lower = tb_raw.lower().strip()
            if not tb_lower:
                continue
            # Check if brand appears at the very start of the title (primary brand position)
            if re.match(rf"^{re.escape(tb_lower)}\b", title_lower):
                signals.append(BrandSignal(
                    "TITLE_BRAND_PRIMARY", SCORE_TITLE_BRAND_PRIMARY,
                    f"Brand '{tb_raw}' appears at start of title (primary position).",
                ))
                score += SCORE_TITLE_BRAND_PRIMARY
                brand_in_title = True
                break
            # Check if brand appears anywhere in the title
            elif re.search(rf"\b{re.escape(tb_lower)}\b", title_lower):
                signals.append(BrandSignal(
                    "TITLE_CONTAINS_BRAND", SCORE_TITLE_CONTAINS_BRAND,
                    f"Brand '{tb_raw}' mentioned in title (non-primary position).",
                ))
                score += SCORE_TITLE_CONTAINS_BRAND
                brand_in_title = True
                break

        if not brand_in_title:
            if not norm_scraped:
                signals.append(BrandSignal(
                    "NO_BRAND_EVIDENCE", 0,
                    f"Neither explicit brand nor title mention of target brand(s).",
                ))
            elif title_lower.strip() and not is_trusted_store:
                signals.append(BrandSignal(
                    "MISSING_BRAND_IN_TITLE", -60,
                    f"Title completely lacks target brand mention (suspicious seller spoofing).",
                ))
                score += -60

        # ----- Decision -----
        has_explicit_brand = norm_scraped is not None or norm_manufacturer is not None

        if score >= THRESHOLD_VERIFIED and has_explicit_brand:
            # High confidence: explicit structured data confirms brand
            status = BrandStatus.VERIFIED
            reason = f"Brand verified (score={score}): "
            reason += "; ".join(s.detail for s in signals if s.score > 0)
        elif score < THRESHOLD_REJECTED:
            status = BrandStatus.REJECTED
            reason = f"Brand rejected (score={score}): "
            reason += "; ".join(s.detail for s in signals if s.score < 0)
        elif not has_explicit_brand:
            # No explicit brand data — title keywords alone cannot verify.
            # This prevents "Siwi Earbuds for Samsung" with brand=None from
            # being classified as Samsung just because title starts with it.
            status = BrandStatus.UNKNOWN
            reason = f"No explicit brand data available (score={score}): "
            reason += "; ".join(s.detail for s in signals)
        else:
            # Has explicit data but score is between 0 and threshold — ambiguous
            status = BrandStatus.REJECTED
            reason = f"Insufficient brand confidence (score={score}): "
            reason += "; ".join(s.detail for s in signals)

        result = BrandValidationResult(
            brand_status=status,
            scraped_brand=scraped_brand,
            normalized_brand=norm_scraped,
            target_brand=raw_target_label,
            confidence_score=score,
            filter_reason=reason,
            signals=signals,
            matched_compatibility_phrase=compat_phrase,
        )

        # Debug logging
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "[BRAND FILTER]\n"
                "  Product: %s\n"
                "  Explicit brand: %s\n"
                "  Target brand: %s\n"
                "  Title contains target: %s\n"
                "  Compatibility context: %s\n"
                "  Score: %s\n"
                "  Decision: %s\n"
                "  Reason: %s",
                title[:80],
                scraped_brand or "(none)",
                raw_target_label,
                "YES" if brand_in_title else "NO",
                compat_phrase or "NO",
                score,
                status.value,
                reason,
            )

        return result
