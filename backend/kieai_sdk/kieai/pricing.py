#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Price-fetching interface for kie.ai.

kie.ai exposes pricing through an internal endpoint (not the public docs):

    POST https://api.kie.ai/client/v1/model-pricing/page
    body: {"pageNum": 1, "pageSize": 100, "modelDescription": "", "interfaceType": "Video"}

The response is paginated and grouped by ``interfaceType``
(``Image`` / ``Video`` / ``Music`` / ``Audio``).  Each record carries:
  * ``modelDescription`` — ``"<model_id>, <category>, <spec>"``
  * ``falPrice``         — the upstream/official price  -> ``official_price``
  * ``usdPrice``         — the price kie actually charges -> ``kie_price``
  * ``creditPrice`` / ``creditUnit`` / ``discountRate`` / ``provider`` / ``anchor``

This module fetches those records and normalises them into :class:`PriceRecord`.
It is intentionally independent of the catalog so it can be used standalone.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import aiohttp

from .exceptions import KieRequestError
from .models import ModelEntry

PRICING_URL = "https://api.kie.ai/client/v1/model-pricing/page"
DEFAULT_INTERFACE_TYPES = ("Image", "Video", "Music", "Audio")
DEFAULT_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "prices_cache.json"
)

# category -> keywords that identify the "base" variant in a description
_CATEGORY_KEYWORD = {
    "image": ("image", "text to image", "image to image"),
    "video": ("video", "text to video"),
    "music": ("music", "speech"),
    "audio": ("speech", "audio"),
}

_GENERIC_WORDS = {"image", "video", "audio", "music", "api", "ai"}


def _norm(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


_CAP_SUFFIX = re.compile(
    r"-(text-to-image|image-to-image|text-to-video|image-to-video|"
    r"video-to-video|text-to-speech|video-to-audio|upscale|edit|generate)$",
    re.IGNORECASE,
)


def _clean_ref(ref: str) -> str:
    """Strip a vendor prefix (``bytedance/``) and a capability suffix."""
    ref = ref.split("/", 1)[-1] if "/" in ref else ref
    return _CAP_SUFFIX.sub("", ref)


@dataclass
class PriceRecord:
    """A single normalised pricing row."""

    model_id: str
    description: str
    interface_type: str
    provider: str
    official_price: str       # upstream / fal.ai price
    kie_price: str            # price kie charges (usdPrice)
    credit_price: str
    credit_unit: str
    discount_rate: float
    anchor: str

    @property
    def norm_token(self) -> str:
        """Normalised leading model id (first comma segment)."""
        return _norm(self.model_id)

    @property
    def norm_full(self) -> str:
        return _norm(self.description)

    @classmethod
    def from_raw(cls, rec: Dict[str, Any]) -> "PriceRecord":
        fal = (rec.get("falPrice") or "").strip()
        usd = (rec.get("usdPrice") or "").strip()
        official = fal or usd
        try:
            discount = float(rec.get("discountRate") or 0)
        except (TypeError, ValueError):
            discount = 0.0
        return cls(
            model_id=(rec.get("modelDescription") or "").split(",", 1)[0].strip(),
            description=(rec.get("modelDescription") or "").strip(),
            interface_type=(rec.get("interfaceType") or "").lower(),
            provider=rec.get("provider") or "",
            official_price=official,
            kie_price=usd,
            credit_price=str(rec.get("creditPrice", "")),
            credit_unit=rec.get("creditUnit") or "",
            discount_rate=discount,
            anchor=rec.get("anchor") or "",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "description": self.description,
            "interface_type": self.interface_type,
            "provider": self.provider,
            "official_price": self.official_price,
            "kie_price": self.kie_price,
            "credit_price": self.credit_price,
            "credit_unit": self.credit_unit,
            "discount_rate": self.discount_rate,
            "anchor": self.anchor,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PriceRecord":
        return cls(
            model_id=d.get("model_id", ""),
            description=d.get("description", ""),
            interface_type=d.get("interface_type", ""),
            provider=d.get("provider", ""),
            official_price=d.get("official_price", ""),
            kie_price=d.get("kie_price", ""),
            credit_price=d.get("credit_price", ""),
            credit_unit=d.get("credit_unit", ""),
            discount_rate=float(d.get("discount_rate", 0) or 0),
            anchor=d.get("anchor", ""),
        )


class KiePricing:
    """Async client for the kie.ai pricing endpoint."""

    def __init__(
        self,
        authorization: str,
        a_dkmt: str,
        uniqueid: str,
        *,
        user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
        ),
        timeout: float = 30.0,
        cache_path: Optional[str] = DEFAULT_CACHE_PATH,
        ttl: Optional[float] = None,
    ):
        # These tokens come from a browser session (see pricing.txt).
        # The a-dkmt / uniqueid tokens may expire; refresh them as needed.
        self.headers = {
            "authorization": authorization,
            "a-dkmt": a_dkmt,
            "uniqueid": uniqueid,
            "content-type": "application/json",
            "origin": "https://kie.ai",
            "referer": "https://kie.ai/",
            "accept": "application/json, text/plain, */*",
            "user-agent": user_agent,
        }
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        # Disk cache: when set, fetch_all() serves cached records instead of
        # hitting the API. ``ttl`` (seconds) controls freshness; None = no expiry.
        self.cache_path = cache_path
        self.ttl = ttl

    async def fetch_page(
        self,
        interface_type: str,
        page_num: int = 1,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        body = {
            "pageNum": page_num,
            "pageSize": page_size,
            "modelDescription": "",
            "interfaceType": interface_type,
        }
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.post(PRICING_URL, json=body, timeout=self.timeout) as resp:
                data = await resp.json()
                if resp.status >= 400 or data.get("code") != 200:
                    raise KieRequestError(
                        f"Pricing request failed ({resp.status}): {data.get('msg', data)}",
                        status=resp.status,
                        body=data,
                    )
                return data["data"]

    # ------------------------------------------------------------------ cache
    def _load_cache(self) -> Optional[List[PriceRecord]]:
        if not self.cache_path or not os.path.exists(self.cache_path):
            return None
        try:
            with open(self.cache_path, encoding="utf-8") as fh:
                blob = json.load(fh)
        except (OSError, ValueError):
            return None
        fetched_at = blob.get("fetched_at")
        if self.ttl is not None and fetched_at:
            try:
                ts = datetime.fromisoformat(fetched_at).timestamp()
                if (time.time() - ts) > self.ttl:
                    return None
            except ValueError:
                return None
        return [PriceRecord.from_dict(r) for r in blob.get("records", [])]

    def _save_cache(self, records: List[PriceRecord]) -> None:
        if not self.cache_path:
            return
        blob = {
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
            "count": len(records),
            "records": [r.to_dict() for r in records],
        }
        tmp = self.cache_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(blob, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.cache_path)

    async def fetch_all(
        self,
        interface_types: Sequence[str] = DEFAULT_INTERFACE_TYPES,
        page_size: int = 100,
        *,
        use_cache: bool = True,
        force: bool = False,
    ) -> List[PriceRecord]:
        """Fetch every pricing record across the given interface types.

        With caching enabled (default) the results are served from
        ``cache_path`` when fresh, otherwise fetched live and stored.
        Pass ``force=True`` to bypass the cache.
        """
        if use_cache and not force:
            cached = self._load_cache()
            if cached is not None:
                return cached
        records: List[PriceRecord] = []
        for it in interface_types:
            page = 1
            while True:
                data = await self.fetch_page(it, page, page_size)
                for rec in data.get("records", []):
                    records.append(PriceRecord.from_raw(rec))
                total_pages = data.get("pages", 1) or 1
                if page >= total_pages or not data.get("records"):
                    break
                page += 1
        if use_cache:
            self._save_cache(records)
        return records

    @staticmethod
    def build_index(records: List[PriceRecord]) -> Dict[str, List[PriceRecord]]:
        index: Dict[str, List[PriceRecord]] = {}
        for r in records:
            index.setdefault(r.norm_token, []).append(r)
        return index


def find_records(
    model: ModelEntry,
    index: Dict[str, List[PriceRecord]],
    all_records: List[PriceRecord],
) -> Tuple[List[PriceRecord], bool]:
    """Find pricing records for a catalog model.

    Returns ``(records, approx)`` where ``approx`` is True when the match was
    made heuristically (platform/provider) rather than by exact model id.
    """
    candidates = []
    if model.model_ref:
        candidates.append(_norm(model.model_ref))
        candidates.append(_norm(_clean_ref(model.model_ref)))
    candidates.append(_norm(model.id))
    candidates.append(_norm(model.name))
    candidates = [c for c in candidates if c]

    # Tier 1a: exact normalised model id
    for c in candidates:
        if c in index:
            return index[c], False

    # Tier 1b: candidate substring of a record's full description
    for c in candidates:
        for r in all_records:
            if c and c in r.norm_full:
                return [r], False

    # Tier 1c: record token substring of a candidate
    for c in candidates:
        for r in all_records:
            if r.norm_token and r.norm_token in c:
                return [r], False

    # Tier 2: platform / keyword heuristic (approximate).
    # Match against the *original* (non-normalised) description using the
    # platform's natural words, so "Flux Kontext" matches "Black Forest Labs
    # Flux 2 Flex" (the normalised "fluxkontext" would not).
    pkws = [
        w for w in re.split(r"[\s\-/]+", model.platform)
        if len(w) >= 2 and w.lower() not in _GENERIC_WORDS
    ]
    cat_kws = _CATEGORY_KEYWORD.get(model.category, ())
    if pkws and cat_kws:
        hits = [
            r for r in all_records
            if any(pk.lower() in (r.description or "").lower() for pk in pkws)
            and any(ck.lower() in (r.description or "").lower() for ck in cat_kws)
        ]
        if hits:
            return [min(hits, key=lambda r: len(r.description))], True

    return [], False


async def fetch_prices(
    authorization: str,
    a_dkmt: str,
    uniqueid: str,
    interface_types: Sequence[str] = DEFAULT_INTERFACE_TYPES,
    *,
    cache_path: Optional[str] = DEFAULT_CACHE_PATH,
    ttl: Optional[float] = None,
    use_cache: bool = True,
    force: bool = False,
) -> List[PriceRecord]:
    """Convenience coroutine: fetch all pricing records in one call."""
    client = KiePricing(
        authorization, a_dkmt, uniqueid,
        cache_path=cache_path, ttl=ttl,
    )
    return await client.fetch_all(
        interface_types, use_cache=use_cache, force=force,
    )


if __name__ == "__main__":  # pragma: no cover
    import os
    import sys

    async def _main():
        recs = await fetch_prices(
            os.environ["KIE_PRICING_AUTH"],
            os.environ["KIE_PRICING_DKMT"],
            os.environ["KIE_PRICING_UID"],
        )
        print(f"fetched {len(recs)} pricing records")
        for r in recs[:5]:
            print(r.model_id, "| official", r.official_price, "| kie", r.kie_price)

    asyncio.run(_main())
