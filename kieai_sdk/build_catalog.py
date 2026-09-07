#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_catalog.py
================
Parse all kie.ai API documentation Markdown files (which embed OpenAPI 3.0 YAML
specifications) and produce a single machine-readable model catalog
(`catalog.json`) used by the kieai SDK.

The catalog is the *registry* that drives the SDK: each entry tells the client
which endpoint to call, how to build the request body, which endpoint to poll
for results, and which parameters the model accepts.

Usage:
    python build_catalog.py [DOCS_DIR] [OUT_JSON]

Defaults:
    DOCS_DIR = the folder containing the downloaded *.md docs
    OUT_JSON = ./catalog.json  (next to this script)

Note on pricing / dates:
    kie.ai/pricing is region-restricted and cannot be scraped from this
    environment, so `model_date`, `official_price` and `kie_price` are filled
    with "N/A" and `other_info_url` always points to https://kie.ai/pricing for
    manual lookup.
"""

import json
import os
import re
import sys
import glob
import yaml

# --------------------------------------------------------------------------- #
# Static knowledge: per-family base URL, poll endpoint and result semantics
# --------------------------------------------------------------------------- #

FAMILY_BASE = {
    "market": "https://api.kie.ai",
    "flux": "https://api.kie.ai",
    "4o": "https://api.kie.ai",
    "runway": "https://api.kie.ai",
    "veo3": "https://api.kie.ai",
    "suno": "https://api.kie.ai",
    "file-upload": "https://kieai.redpandaai.co",
}

FAMILY_POLL = {
    "market": "https://api.kie.ai/api/v1/jobs/recordInfo",
    "flux": "https://api.kie.ai/api/v1/flux/kontext/record-info",
    "runway": "https://api.kie.ai/api/v1/runway/record-detail",
    "veo3": "https://api.kie.ai/api/v1/veo/record-info",
    "4o": "https://api.kie.ai/api/v1/gpt4o-image/record-info",
    "suno": "https://api.kie.ai/api/v1/generate/record-info",
    "file-upload": None,  # synchronous, returns URL directly
}

# category for the dedicated API families (market category is inferred per file)
FAMILY_CATEGORY = {
    "flux": "image",
    "4o": "image",
    "runway": "video",
    "veo3": "video",
    "suno": "music",
    "file-upload": "file-upload",
}

# How to build the request body and how to read the async task id.
#   market  -> {"model": <model_ref>, "input": {<params>}}
#   direct  -> {<params>}  (model selection is a normal parameter)
#   upload  -> {<params>}  (synchronous file upload, no task id)
REQUEST_STYLE = {
    "market": "market",
    "flux": "direct",
    "4o": "direct",
    "runway": "direct",
    "veo3": "direct",
    "suno": "direct",
    "file-upload": "upload",
}

OTHER_INFO_URL = "https://kie.ai/pricing"

DOCS_DEFAULT = r"y:\VideoLingoLc\_backup\kieai文档"
OUT_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog.json")


# --------------------------------------------------------------------------- #
# YAML block extraction
# --------------------------------------------------------------------------- #

def extract_yaml_blocks(text):
    """Return every ```yaml ... ``` fenced block from a markdown document."""
    blocks = []
    for m in re.finditer(r"```ya?ml\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE):
        blocks.append(m.group(1))
    return blocks


def _norm_description(desc):
    if not isinstance(desc, str):
        return ""
    # collapse whitespace / newlines from YAML folded scalars
    desc = re.sub(r"\s+", " ", desc).strip()
    return desc


def resolve_ref(doc, node):
    """Resolve a local `#/components/schemas/Name` $ref into the actual schema.

    The node's own keys (other than $ref) override the referenced schema.
    """
    if isinstance(node, dict) and isinstance(node.get("$ref"), str):
        ref = node["$ref"]
        if ref.startswith("#/components/schemas/"):
            name = ref.split("/")[-1]
            schema = doc.get("components", {}).get("schemas", {}).get(name)
            if isinstance(schema, dict):
                merged = dict(schema)
                for k, v in node.items():
                    if k != "$ref":
                        merged[k] = v
                return merged
    return node


def parse_params(doc, properties, required):
    """Turn an OpenAPI properties mapping into a list of param dicts."""
    params = []
    if not isinstance(properties, dict):
        return params
    required = set(required or [])
    for name, spec in properties.items():
        if name in ("callBackUrl", "callbackUrl"):
            continue  # we never send callbacks
        spec = resolve_ref(doc, spec)
        if not isinstance(spec, dict):
            spec = {}
        ptype = spec.get("type", "string")
        if "$ref" in spec:
            ptype = "object"
        if ptype in (None, "null"):
            ptype = "string"
        # array of strings -> keep type "array<string>"
        if ptype == "array":
            items = spec.get("items", {})
            item_type = items.get("type", "string") if isinstance(items, dict) else "string"
            ptype = f"array<{item_type}>"
        params.append({
            "name": name,
            "type": ptype,
            "required": name in required,
            "default": spec.get("default"),
            "enum": spec.get("enum"),
            "description": _norm_description(spec.get("description", "")),
        })
    return params


# --------------------------------------------------------------------------- #
# Per-file entry builder
# --------------------------------------------------------------------------- #

def family_from_path(rel_path):
    """Map a doc file path to a family key."""
    parts = rel_path.replace("\\", "/").split("/")
    top = parts[0].lower() if parts else ""
    if top == "market":
        return "market"
    mapping = {
        "flux-kontext-api": "flux",
        "4o-image-api": "4o",
        "runway-api": "runway",
        "veo3-api": "veo3",
        "suno-api": "suno",
        "file-upload-api": "file-upload",
    }
    return mapping.get(top, top)


# Platform -> category hint for Market models (used as a fallback when the
# OpenAPI `tags` string does not contain an explicit Image/Video/Audio keyword).
MARKET_PLATFORM_CATEGORY = {
    # image
    "seedream": "image", "seedream-5-lite": "image", "flux2": "image",
    "google": "image", "ideogram": "image", "qwen": "image",
    "recraft": "image", "topaz": "image", "z-image": "image",
    "gpt-image": "image", "grok-imagine-image-2-0": "image",
    # video
    "kling": "video", "sora2": "video", "bytedance": "video",
    "hailuo": "video", "wan": "video", "pixverse": "video",
    "omnihuman-1-5": "video", "volcengine": "video",
    "happyhorse": "video", "happyhorse-1-1": "video", "minimax-h3": "video",
    "grok-imagine": "video",
    # audio
    "elevenlabs": "audio", "gemini-omni-audio": "audio",
    "gemini-omni-character": "audio", "gemini-omni-video": "video",
}


def infer_category(family, rel_path, tags_text):
    """Infer the user-facing category (image/video/music/audio/file-upload)."""
    if family in FAMILY_CATEGORY:
        return FAMILY_CATEGORY[family]
    low = (tags_text or "").lower()
    name = rel_path.lower().replace("\\", "/")
    parts = name.split("/")
    platform = parts[1] if len(parts) >= 2 else ""
    # 1) explicit tag keyword
    if "video" in low:
        return "video"
    if "image" in low or "upscale" in low:
        return "image"
    if "audio" in low or "speech" in low or "tts" in low:
        return "audio"
    # 2) platform hint
    if platform in MARKET_PLATFORM_CATEGORY:
        return MARKET_PLATFORM_CATEGORY[platform]
    # 3) filename keyword
    if "video" in name:
        return "video"
    if "image" in name or "upscale" in name:
        return "image"
    if "audio" in name or "speech" in name or "tts" in name or "music" in name:
        return "audio"
    return "other"


def infer_platform(family, rel_path):
    """Best-effort platform / vendor name."""
    parts = rel_path.replace("\\", "/").split("/")
    if family == "market":
        # market/<platform>/<file>.md  (or file directly under market/)
        if len(parts) >= 2 and parts[1]:
            return parts[1]
        return "market"
    return {
        "flux": "Flux Kontext",
        "4o": "GPT-4o Image",
        "runway": "Runway",
        "veo3": "Veo 3.1",
        "suno": "Suno",
        "file-upload": "File Upload",
    }.get(family, family)


def build_entry(rel_path, doc, post_path, post_op):
    family = family_from_path(rel_path)
    base = FAMILY_BASE.get(family, "https://api.kie.ai")

    summary = _norm_description(post_op.get("summary", ""))
    description = _norm_description(post_op.get("description", ""))
    tags_text = " ".join(post_op.get("tags", [])) if isinstance(post_op.get("tags"), list) else ""

    # ---- request body schema ----
    body_schema = None
    try:
        rb = post_op["requestBody"]["content"]["application/json"]["schema"]
        body_schema = rb
    except Exception:
        body_schema = None

    model_ref = None
    model_options = None
    params = []
    request_style = REQUEST_STYLE.get(family, "direct")

    if isinstance(body_schema, dict):
        body_schema = resolve_ref(doc, body_schema)
        props = body_schema.get("properties", {}) or {}
        required = body_schema.get("required", []) or []
        enum_model = resolve_ref(doc, props.get("model", {}))
        if isinstance(enum_model, dict) and enum_model.get("enum"):
            model_options = enum_model["enum"]
            if len(model_options) == 1:
                model_ref = model_options[0]

        # Market pattern: real params live inside `input`
        input_spec = resolve_ref(doc, props.get("input"))
        if isinstance(input_spec, dict) and isinstance(input_spec.get("properties"), dict):
            params = parse_params(
                doc, input_spec["properties"], input_spec.get("required", []) or []
            )
        else:
            # dedicated pattern: params are top-level (keep `model` if present)
            filtered = {k: v for k, v in props.items() if k not in ("callBackUrl", "callbackUrl")}
            params = parse_params(doc, filtered, required)
            if model_options and "model" not in filtered:
                # represent the model selector as a first-class parameter
                params.insert(0, {
                    "name": "model",
                    "type": "string",
                    "required": "model" in required or model_ref is None,
                    "default": (enum_model.get("default")
                                or model_ref
                                or (model_options[0] if model_options else None)),
                    "enum": model_options,
                    "description": _norm_description(enum_model.get("description", "Model selector")),
                })

    # ---- identity / id ----
    op_id = post_op.get("operationId")
    if model_ref:
        entry_id = model_ref
    elif op_id:
        entry_id = op_id
    else:
        entry_id = os.path.splitext(os.path.basename(rel_path))[0]

    category = infer_category(family, rel_path, tags_text)
    platform = infer_platform(family, rel_path)

    doc_url = "https://docs.kie.ai/" + rel_path[:-3] if rel_path.endswith(".md") else rel_path

    endpoint = base + post_path
    poll_endpoint = FAMILY_POLL.get(family)

    return {
        "id": entry_id,
        "name": summary or entry_id,
        "platform": platform,
        "category": category,
        "family": family,
        "model_ref": model_ref,
        "model_options": model_options,
        "request_style": request_style,
        "description": description or summary,
        "endpoint": endpoint,
        "method": "POST",
        "poll_endpoint": poll_endpoint,
        "poll_id_param": "taskId" if poll_endpoint else None,
        "params": params,
        "model_date": "N/A",
        "official_price": "N/A",
        "kie_price": "N/A",
        "other_info_url": OTHER_INFO_URL,
        "doc_url": doc_url,
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main():
    docs_dir = sys.argv[1] if len(sys.argv) > 1 else DOCS_DEFAULT
    out_json = sys.argv[2] if len(sys.argv) > 2 else OUT_DEFAULT

    md_files = sorted(glob.glob(os.path.join(docs_dir, "**", "*.md"), recursive=True))
    entries = {}
    skipped = 0
    errors = []

    for fpath in md_files:
        rel = os.path.relpath(fpath, docs_dir)
        fname = os.path.basename(fpath)
        if "callback" in fname.lower():
            skipped += 1
            continue
        if fname.lower().endswith("-quickstart.md"):
            # overview pages with possibly incomplete specs -> skip to avoid dupes
            skipped += 1
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as fh:
                text = fh.read()
        except Exception as e:
            errors.append((rel, f"read: {e}"))
            continue

        blocks = extract_yaml_blocks(text)
        if not blocks:
            skipped += 1
            continue

        found_post = False
        for block in blocks:
            try:
                doc = yaml.safe_load(block)
            except Exception as e:
                errors.append((rel, f"yaml: {e}"))
                continue
            if not isinstance(doc, dict):
                continue
            paths = doc.get("paths")
            if not isinstance(paths, dict):
                continue
            for path, methods in paths.items():
                if not isinstance(methods, dict):
                    continue
                post = methods.get("post")
                if not isinstance(post, dict):
                    continue
                found_post = True
                entry = build_entry(rel, doc, path, post)
                # de-duplicate by id (keep first / most specific)
                if entry["id"] not in entries:
                    entries[entry["id"]] = entry

        if not found_post:
            skipped += 1

    catalog = {
        "version": 1,
        "generated_from": "kie.ai API docs (OpenAPI YAML)",
        "note": (
            "model_date / official_price / kie_price are 'N/A' because "
            "kie.ai/pricing is region-restricted and cannot be scraped here. "
            "See other_info_url for manual lookup."
        ),
        "families": {
            k: {
                "base_url": FAMILY_BASE[k],
                "poll_endpoint": FAMILY_POLL[k],
                "request_style": REQUEST_STYLE[k],
                "category": FAMILY_CATEGORY.get(k),
            }
            for k in FAMILY_BASE
        },
        "models": list(entries.values()),
    }

    os.makedirs(os.path.dirname(out_json) or ".", exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, ensure_ascii=False, indent=2)

    n = len(catalog["models"])
    by_cat = {}
    for m in catalog["models"]:
        by_cat[m["category"]] = by_cat.get(m["category"], 0) + 1
    print(f"Wrote {out_json}")
    print(f"Total models: {n}")
    print(f"By category: {by_cat}")
    print(f"Skipped (no POST / callbacks): {skipped}")
    if errors:
        print(f"Parse warnings: {len(errors)} (first 5):")
        for e in errors[:5]:
            print("  -", e)


if __name__ == "__main__":
    main()
