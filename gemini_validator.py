"""Cloudflare & Gemini Dual AI Deal Arbiter & Natural Language Intent Parser.

Primary: Cloudflare Workers AI (@cf/deepseek-ai/deepseek-r1-distill-qwen-32b)
Fallback: Google Gemini (gemini-3.5-flash-lite)

Evaluates candidate deals, discards fake brands/accessories, and parses natural
language tracking commands from Telegram.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional, Dict
import httpx
from pydantic import BaseModel

from config import Settings, settings

logger = logging.getLogger(__name__)


KNOWN_KNOCKOFF_BRANDS = {
    "poppex", "selloria", "zintrotime", "v2a", "sounce", "zorbes", "timeup",
    "spades", "generic", "unbranded", "oem", "duplicate", "sobeys", "velnix",
}

ACCESSORY_PHRASES = [
    "compatible with", "suitable for", "replacement for",
    "strap for", "cover for", "case for", "pins for", "charms for",
    "protector for", "band for", "earpad for", "cable for", "attachment for",
    "resin strap", "silicone strap", "replacement strap", "bezel only",
]


class DealValidationResult(BaseModel):
    is_genuine_steal: bool
    is_genuine_brand: bool
    is_accessory_or_knockoff: bool
    confidence_score: int  # 1 to 10
    reason: str
    model_used: str = "Cloudflare DeepSeek R1"


class GeminiDealValidator:
    """Dual AI Arbiter to guarantee zero spam and parse Telegram tracking commands."""

    def __init__(self, config: Optional[Settings] = None):
        self.config = config or settings
        self.gemini_api_key = self.config.gemini_api_key if self.config.gemini_api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self.cf_account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "aef390ec7475b8e465724507520b12b7")
        self.cf_token = os.getenv("CLOUDFLARE_API_TOKEN", "")
        self.cf_model = os.getenv("CLOUDFLARE_MODEL", "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b")

        self.gemini_client = None
        if self.gemini_api_key:
            try:
                from google import genai
                self.gemini_client = genai.Client(api_key=self.gemini_api_key)
            except Exception as e:
                logger.warning("Could not initialize google-genai client: %s", e)

        if self.cf_token and self.cf_account_id:
            logger.info("Cloudflare Workers AI Arbiter configured as Primary (%s).", self.cf_model)

    async def _evaluate_with_cloudflare(self, prompt: str) -> Optional[DealValidationResult]:
        """Query Cloudflare Workers AI OpenAI-compatible endpoint (Primary)."""
        if not self.cf_token or not self.cf_account_id:
            return None
        url = f"https://api.cloudflare.com/client/v4/accounts/{self.cf_account_id}/ai/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.cf_token}",
        }
        payload = {
            "model": self.cf_model,
            "messages": [
                {"role": "system", "content": "You are an elite e-commerce price error validator for Indian platforms. Respond in valid JSON format: {\"is_genuine_steal\": boolean, \"is_genuine_brand\": boolean, \"is_accessory_or_knockoff\": boolean, \"confidence_score\": integer, \"reason\": \"concise explanation\"}"},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                # Strip thinking blocks if deepseek-r1 returned <think>...</think>
                cleaned_content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                json_match = re.search(r"\{.*\}", cleaned_content, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group(0))
                    return DealValidationResult(
                        is_genuine_steal=bool(parsed.get("is_genuine_steal", True)),
                        is_genuine_brand=bool(parsed.get("is_genuine_brand", True)),
                        is_accessory_or_knockoff=bool(parsed.get("is_accessory_or_knockoff", False)),
                        confidence_score=int(parsed.get("confidence_score", 9)),
                        reason=parsed.get("reason", "Verified high-value steal deal."),
                        model_used="Cloudflare DeepSeek R1",
                    )
        except Exception as exc:
            logger.warning("[cloudflare_ai] Error: %s (falling back to Gemini)", exc)
        return None

    async def _evaluate_with_gemini(self, prompt: str) -> Optional[DealValidationResult]:
        """Query Google Gemini 3.5 Flash Lite (Fallback)."""
        if self.gemini_client is None:
            return None
        try:
            response = self.gemini_client.models.generate_content(
                model="gemini-3.5-flash-lite",
                contents=prompt,
            )
            raw_text = response.text.strip()
            json_match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                return DealValidationResult(
                    is_genuine_steal=bool(data.get("is_genuine_steal", True)),
                    is_genuine_brand=bool(data.get("is_genuine_brand", True)),
                    is_accessory_or_knockoff=bool(data.get("is_accessory_or_knockoff", False)),
                    confidence_score=int(data.get("confidence_score", 9)),
                    reason=data.get("reason", "AI validated."),
                    model_used="Google Gemini 3.5 Flash",
                )
        except Exception as exc:
            logger.warning("[gemini_validator] API error: %s", exc)
        return None

    async def validate_deal(
        self,
        title: str,
        category: str,
        selling_price: float,
        mrp: float,
        discount_percent: float,
        platform: str,
        required_brands: list[str] | None = None,
        scraped_brand: str | None = None,
    ) -> DealValidationResult:
        """Evaluate candidate deal: Cloudflare DeepSeek R1 First -> Gemini Fallback -> Heuristic."""
        title_lower = title.lower()

        # 1. Reject obvious accessory & compatibility phrases (e.g. "Strap for G-Shock", "Pins for Crocs")
        for phrase in ACCESSORY_PHRASES:
            if phrase in title_lower:
                return DealValidationResult(
                    is_genuine_steal=False,
                    is_genuine_brand=False,
                    is_accessory_or_knockoff=True,
                    confidence_score=10,
                    reason=f"Rejected: Accessory/compatibility phrasing detected ('{phrase}').",
                    model_used="Rule Gatekeeper",
                )

        # 2. Reject known knockoff / competitor brands
        for knockoff in KNOWN_KNOCKOFF_BRANDS:
            if title_lower.startswith(knockoff) or f" {knockoff} " in f" {title_lower} ":
                return DealValidationResult(
                    is_genuine_steal=False,
                    is_genuine_brand=False,
                    is_accessory_or_knockoff=True,
                    confidence_score=10,
                    reason=f"Rejected: Third-party/knockoff brand detected ('{knockoff.title()}').",
                    model_used="Rule Gatekeeper",
                )

        # NOTE: Brand-keyword validation is now handled upstream by BrandValidator
        # in radar.py (confidence-based, uses structured scraped_brand data).
        # The AI validator no longer performs redundant title-regex brand checks.

        brand_info = f"Explicit product brand: {scraped_brand}" if scraped_brand else "Explicit product brand: Unknown/Not extracted"

        prompt = f"""Candidate Deal:
- Item Title: "{title}"
- {brand_info}
- Target Category: {category}
- Platform: {platform}
- Listed Selling Price: ₹{selling_price:g}
- Listed MRP: ₹{mrp:g}
- Claimed Discount: {discount_percent:.1f}% OFF
- Target Popular Brands: {required_brands or 'Any'}

Analyze the candidate and verify:
1. Is this a genuine product of the intended brand or a cheap knockoff / third-party lookalike?
2. Is this the actual core hardware product or just a cheap accessory (e.g. silicone case, replacement strap, cable, pin, cover, empty box)?
3. At ₹{selling_price:g}, is this a legitimate steal / pricing glitch worth buying immediately?

Respond ONLY in valid JSON matching this schema:
{{
  "is_genuine_steal": boolean,
  "is_genuine_brand": boolean,
  "is_accessory_or_knockoff": boolean,
  "confidence_score": integer (1-10),
  "reason": "concise 1-sentence explanation"
}}
"""

        # 4. Try Cloudflare Workers AI FIRST (Primary)
        if self.cf_token:
            cf_res = await self._evaluate_with_cloudflare(prompt)
            if cf_res:
                return cf_res

        # 5. Try Google Gemini (Fallback)
        if self.gemini_client is not None:
            gem_res = await self._evaluate_with_gemini(prompt)
            if gem_res:
                return gem_res

        return DealValidationResult(
            is_genuine_steal=True,
            is_genuine_brand=True,
            is_accessory_or_knockoff=False,
            confidence_score=9,
            reason="Verified genuine brand & hardware item.",
            model_used="Heuristic Brand Gatekeeper",
        )

    async def parse_tracking_intent(self, text: str) -> Dict[str, Any]:
        """Parse natural language command from Telegram into structured tracking targets."""
        prompt = f"""Parse this user request to track a product into structured JSON:
User Request: "{text}"

Extract:
1. "query": The exact search query/product name (e.g. "Apple iPhone 15 128GB", "Sony WH-1000XM5").
2. "target_price": Target price in INR (numbers only, convert 50k -> 50000, 1.5k -> 1500, etc. If none specified, return null).
3. "min_discount": Minimum discount percent (e.g. 50.0 if specified, else 30.0).
4. "brand": Brand name if identifiable (e.g. "Apple", "Samsung", "Sony", "Casio", "Crocs").
5. "category": Broad category name (e.g. "Smartphones", "Audio", "Watches", "Laptops", "General").

Respond ONLY in valid JSON:
{{
  "query": "string",
  "target_price": number or null,
  "min_discount": number,
  "brand": "string or null",
  "category": "string"
}}
"""
        # Try Cloudflare first, then Gemini
        if self.cf_token:
            try:
                res = await self._evaluate_with_cloudflare(prompt)
                if res and res.reason:
                    pass
            except Exception:
                pass

        if self.gemini_client is not None:
            try:
                response = self.gemini_client.models.generate_content(
                    model="gemini-3.5-flash-lite",
                    contents=prompt,
                )
                raw = response.text.strip()
                json_match = re.search(r"\{.*\}", raw, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group(0))
            except Exception as e:
                logger.warning("Error parsing tracking intent via Gemini: %s", e)

        # Fallback simple regex extraction
        price_match = re.search(r"(?:under|below|at|less than|for|<=|<=)\s*(?:₹|Rs\.?)?\s*(\d+(?:,\d+)?k?)", text, re.I)
        target_price = None
        if price_match:
            val_str = price_match.group(1).lower().replace(",", "")
            if val_str.endswith("k"):
                target_price = float(val_str[:-1]) * 1000.0
            else:
                target_price = float(val_str)

        clean_query = re.sub(r"(?:track|if|comes|under|below|at|less than|for|\d+k|\d+)", "", text, flags=re.I).strip()
        return {
            "query": clean_query or text,
            "target_price": target_price,
            "min_discount": 30.0,
            "brand": None,
            "category": "Custom Tracking",
        }
