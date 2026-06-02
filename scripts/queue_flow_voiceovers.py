#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8758"
DEFAULT_HAPA_ROOT = Path(os.environ.get("HAPA_ROOT") or (Path.home() / "Desktop" / "hapa"))
SAFE_ID_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


BUILTIN_FLOWS: dict[str, dict[str, Any]] = {
    "atlas-heal": {
        "flow_id": "atlas-heal",
        "flow_name": "Atlas Healing Sweep",
        "summary": "Atlas inventories cards, media, docs, wiki entries, orphan assets, and analysis queues, then pushes clean records back into retrieval and telemetry.",
        "steps": [
            {"source": "overwatch", "target": "hapa-master-dashboard", "layer": "CLI", "label": "Operator standards trigger a controlled health sweep."},
            {"source": "hapa-master-dashboard", "target": "hapa-atlas", "layer": "API", "label": "Master View launches Atlas healing and watches source-of-record state."},
            {"source": "world-building-wiki", "target": "hapa-atlas", "layer": "DATA", "label": "Wiki canon and documentation are indexed with provenance."},
            {"source": "hapa-library", "target": "hapa-atlas", "layer": "DATA", "label": "Card and media records replay into the inventory."},
            {"source": "hapa-media-node", "target": "hapa-atlas", "layer": "DATA", "label": "Image assets report analysis metadata for reuse."},
            {"source": "hapa-ltx-node", "target": "hapa-atlas", "layer": "DATA", "label": "Loop videos attach generation and recognition metadata."},
            {"source": "hapa-atlas", "target": "hapa-lance-node", "layer": "DATA", "label": "Clean entities bridge into retrieval indexes."},
            {"source": "hapa-atlas", "target": "hapa-telemetry-node", "layer": "API", "label": "Health, size, queue, and orphan counts return to ops telemetry."},
        ],
    },
}


def http_json(method: str, url: str, token: str | None = None, payload: dict[str, Any] | None = None, timeout: float = 1200.0) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as res:
        raw = res.read()
    return json.loads(raw.decode("utf-8")) if raw else {}


def sidecar_payload(path: Path) -> dict[str, Any]:
    flow = json.loads(path.read_text(encoding="utf-8"))
    return {
        "flow": flow,
        "flow_id": flow.get("id"),
        "flow_name": flow.get("name"),
        "summary": flow.get("summary"),
        "steps": flow.get("steps") or [],
    }


def safe_id(value: str) -> str:
    return SAFE_ID_RE.sub("-", str(value or "").strip()).strip("-._").lower()


def apply_flow_id_suffix(payload: dict[str, Any], suffix: str) -> dict[str, Any]:
    cleaned = safe_id(suffix)
    if not cleaned:
        return payload
    out = dict(payload)
    base_id = str(out.get("flow_id") or out.get("id") or (out.get("flow") or {}).get("id") or out.get("flow_name") or "flow").strip()
    variant_id = safe_id(f"{base_id}-{cleaned}")
    out["flow_id"] = variant_id
    out["id"] = variant_id
    if isinstance(out.get("flow"), dict):
        out["flow"] = {**out["flow"], "id": variant_id}
    return out


def load_payloads(args: argparse.Namespace) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for name in args.builtin:
        if name not in BUILTIN_FLOWS:
            raise SystemExit(f"Unknown builtin flow: {name}. Known: {', '.join(sorted(BUILTIN_FLOWS))}")
        payloads.append(dict(BUILTIN_FLOWS[name]))
    for raw_path in args.flow_json:
        payloads.append(sidecar_payload(Path(raw_path).expanduser().resolve()))
    if args.all_saved:
        flow_dir = Path(args.hapa_root).expanduser().resolve() / "site" / "generated" / "protocol-flows"
        for path in sorted(flow_dir.glob("*.json")):
            payloads.append(sidecar_payload(path))
    if not payloads:
        payloads.append(dict(BUILTIN_FLOWS["atlas-heal"]))
    return payloads


def main() -> int:
    parser = argparse.ArgumentParser(description="Queue Hapa Node Space flow narratives in Hapa Drama.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--hapa-root", default=str(DEFAULT_HAPA_ROOT))
    parser.add_argument("--builtin", action="append", default=[], help="Built-in flow id to queue, e.g. atlas-heal")
    parser.add_argument("--flow-json", action="append", default=[], help="Path to a protocol-flow sidecar JSON file")
    parser.add_argument("--all-saved", action="store_true", help="Queue every saved protocol-flow sidecar in the Hapa app")
    parser.add_argument("--no-process", action="store_true", help="Create queue entries without generating audio immediately")
    parser.add_argument("--force", action="store_true", help="Regenerate existing successful step voiceovers")
    parser.add_argument("--flow-id-suffix", default="", help="Queue as a variant id, e.g. default-voice")
    parser.add_argument("--no-default-voice", action="store_true", help="Do not attach the saved default voice/profile; use DramaBox's native/default voice route")
    parser.add_argument("--dramabox-cfg-scale", type=float, help="DramaBox/MLX guidance scale")
    parser.add_argument("--dramabox-stg-scale", type=float, help="DramaBox/MLX STG scale")
    parser.add_argument("--dramabox-stg-block", type=int, help="DramaBox/MLX STG transformer block")
    parser.add_argument("--dramabox-rescale-scale", help="DramaBox/MLX CFG rescale value, e.g. auto or 0.7")
    parser.add_argument("--dramabox-steps", type=int, help="DramaBox/MLX generation steps")
    parser.add_argument("--dramabox-duration-multiplier", type=float, help="DramaBox/MLX duration multiplier")
    parser.add_argument("--dramabox-seed", type=int, help="DramaBox/MLX seed for reproducible trials")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    session = http_json("GET", f"{base_url}/local/session", timeout=10.0)
    token = session.get("token")
    if not token:
        raise SystemExit("Could not obtain Hapa Drama loopback token from /local/session")

    results = []
    for payload in load_payloads(args):
        payload = apply_flow_id_suffix(payload, args.flow_id_suffix)
        payload.update({"mode": "drama", "tts_engine": "dramabox", "process": not args.no_process, "force": args.force})
        if args.no_default_voice:
            payload["use_default_voice"] = False
        for key, value in {
            "dramabox_cfg_scale": args.dramabox_cfg_scale,
            "dramabox_stg_scale": args.dramabox_stg_scale,
            "dramabox_stg_block": args.dramabox_stg_block,
            "dramabox_rescale_scale": args.dramabox_rescale_scale,
            "dramabox_steps": args.dramabox_steps,
            "dramabox_duration_multiplier": args.dramabox_duration_multiplier,
            "dramabox_seed": args.dramabox_seed,
        }.items():
            if value is not None:
                payload[key] = value
        print(f"Queueing {payload.get('flow_id') or payload.get('flow', {}).get('id')} ({len(payload.get('steps') or [])} steps)...", flush=True)
        result = http_json("POST", f"{base_url}/v1/flow-voiceovers/queue", token=token, payload=payload)
        flow_voiceover = result.get("flow_voiceover") or {}
        results.append(flow_voiceover)
        ready = len([item for item in flow_voiceover.get("items", []) if item.get("status") == "succeeded"])
        total = len(flow_voiceover.get("items", []))
        print(f"  {flow_voiceover.get('status')} {ready}/{total} ready")
        print(f"  manifest: {flow_voiceover.get('manifest_url')}")
    print(json.dumps({"ok": True, "flows": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
