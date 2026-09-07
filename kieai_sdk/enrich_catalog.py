#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enrich ``catalog.json`` with live prices from the kie.ai pricing endpoint.

Usage
-----
    python enrich_catalog.py [--catalog catalog.json] [--config pricing_config.json]
                             [--force]

The pricing tokens (authorization / a-dkmt / uniqueid) are read from a JSON
config file (default ``pricing_config.json``) or from the environment
variables ``KIE_PRICING_AUTH``, ``KIE_PRICING_DKMT``, ``KIE_PRICING_UID``.

Prices are cached on disk (``prices_cache.json``); the API is only hit when
the cache is missing or stale. Pass ``--force`` to refresh from the API.

Matching strategy
-----------------
* Market models (they carry a ``model_ref`` like ``bytedance/seedream-...``)
  match the pricing ``modelDescription`` token exactly.
* Dedicated families without a model_ref are matched heuristically by
  platform/provider (flagged ``approx`` in the model's ``pricing`` block).

A separate ``prices.json`` (keyed by normalised model id) is also written for
manual lookups.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from kieai import Catalog, KiePricing, find_records  # noqa: E402


def load_tokens(config_path: str) -> dict:
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    return {
        "authorization": os.environ.get("KIE_PRICING_AUTH", ""),
        "a_dkmt": os.environ.get("KIE_PRICING_DKMT", ""),
        "uniqueid": os.environ.get("KIE_PRICING_UID", ""),
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=os.path.join(HERE, "catalog.json"))
    ap.add_argument("--config", default=os.path.join(HERE, "pricing_config.json"))
    ap.add_argument("--prices-out", default=os.path.join(HERE, "prices.json"))
    ap.add_argument("--cache", default=os.path.join(HERE, "prices_cache.json"))
    ap.add_argument("--force", action="store_true",
                    help="Ignore the cache and re-fetch prices from the API")
    args = ap.parse_args()

    tokens = load_tokens(args.config)
    missing = [k for k in ("authorization", "a_dkmt", "uniqueid") if not tokens.get(k)]
    if missing:
        print(f"Missing pricing tokens: {missing} (set them in {args.config} or env)")
        sys.exit(1)

    print("Fetching prices from kie.ai ..." + (" (forced)" if args.force else ""))
    client = KiePricing(
        tokens["authorization"], tokens["a_dkmt"], tokens["uniqueid"],
        cache_path=args.cache,
    )
    try:
        records = await client.fetch_all(force=args.force)
    except Exception as e:  # noqa: BLE001
        print(f"Price fetch failed: {e}")
        sys.exit(1)
    source = "cache" if (not args.force and os.path.exists(args.cache)) else "api"
    print(f"  {source}: {len(records)} pricing records")

    index = client.build_index(records)

    catalog = Catalog.load(args.catalog)
    matched = 0
    approx = 0
    for model in catalog.models:
        recs, is_approx = find_records(model, index, records)
        if not recs:
            continue
        matched += 1
        if is_approx:
            approx += 1
        rep = min(recs, key=lambda r: len(r.description))  # most generic variant
        model.official_price = rep.official_price or "N/A"
        model.kie_price = rep.kie_price or "N/A"
        model.pricing = {
            "official_price": rep.official_price,
            "kie_price": rep.kie_price,
            "credit_price": rep.credit_price,
            "credit_unit": rep.credit_unit,
            "discount_rate": rep.discount_rate,
            "provider": rep.provider,
            "interface_type": rep.interface_type,
            "example": rep.description,
            "anchor": rep.anchor,
            "variants": len(recs),
            "approx": is_approx,
        }

    catalog.save(args.catalog)
    print(f"Updated {matched}/{len(catalog)} models ({approx} heuristic/approx)")

    # standalone price map for manual lookup
    price_map = {
        r.norm_token: {
            "model_id": r.model_id,
            "description": r.description,
            "interface_type": r.interface_type,
            "provider": r.provider,
            "official_price": r.official_price,
            "kie_price": r.kie_price,
            "credit_price": r.credit_price,
            "credit_unit": r.credit_unit,
            "discount_rate": r.discount_rate,
            "anchor": r.anchor,
        }
        for r in records
    }
    with open(args.prices_out, "w", encoding="utf-8") as fh:
        json.dump(price_map, fh, ensure_ascii=False, indent=2)
    print(f"Wrote standalone price map -> {args.prices_out}")


if __name__ == "__main__":
    asyncio.run(main())
