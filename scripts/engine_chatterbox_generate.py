#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


def _device(raw: str | None) -> str:
    value = str(raw or "auto").strip().lower()
    if value != "auto":
        return value
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _patch_torch_load(device: str) -> None:
    import torch

    map_location = torch.device("cpu" if device in {"cpu", "mps"} else device)
    original_load = torch.load

    def patched_torch_load(*args, **kwargs):
        if "map_location" not in kwargs:
            kwargs["map_location"] = map_location
        return original_load(*args, **kwargs)

    torch.load = patched_torch_load


def _load_model(model_name: str, device: str):
    normalized = str(model_name or "standard").strip().lower()
    if normalized in {"turbo", "chatterbox-turbo", "resembleai/chatterbox-turbo"}:
        from chatterbox.tts_turbo import ChatterboxTurboTTS

        return "ResembleAI/chatterbox-turbo", ChatterboxTurboTTS.from_pretrained(device=device)
    if normalized in {"standard", "tts", "chatterbox", "resembleai/chatterbox"}:
        from chatterbox.tts import ChatterboxTTS

        return "ResembleAI/chatterbox", ChatterboxTTS.from_pretrained(device=device)
    raise RuntimeError(f"unsupported Chatterbox model option: {model_name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a WAV with Chatterbox for Hapa Drama.")
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--voice-sample")
    parser.add_argument("--device", default="auto", choices=["auto", "cuda", "mps", "cpu"])
    parser.add_argument("--model", default="standard")
    parser.add_argument("--exaggeration", type=float, default=0.55)
    parser.add_argument("--cfg-weight", type=float, default=0.5)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--seed", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = time.monotonic()
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    import torch
    import torchaudio as ta

    if args.seed:
        torch.manual_seed(args.seed)
    device = _device(args.device)
    _patch_torch_load(device)
    repo_id, model = _load_model(args.model, device)

    generate_kwargs = {
        "audio_prompt_path": args.voice_sample,
        "exaggeration": args.exaggeration,
        "cfg_weight": args.cfg_weight,
        "temperature": args.temperature,
    }
    wav = model.generate(args.text, **generate_kwargs)
    out_path = Path(args.output).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    ta.save(str(out_path), wav.detach().cpu(), int(model.sr), encoding="PCM_S", bits_per_sample=16)
    metadata = {
        "ok": True,
        "engine": "chatterbox",
        "repo_id": repo_id,
        "model": args.model,
        "device": device,
        "sample_rate": int(model.sr),
        "output_path": str(out_path),
        "voice_sample": args.voice_sample,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }
    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        raise
