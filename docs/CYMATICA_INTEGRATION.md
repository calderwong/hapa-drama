# Cymatica Integration

`hapa-drama` writes a Cymatica-ready voice bundle when `payload.output.cymatica_bundle` is true.

Bundle layout:

```text
artifacts/generations/<generation_id>/voice.wav
artifacts/cymatica/<generation_id>/
  cymatica_manifest.json
  stems/voice.wav
  hapa_bundle/
    bundle_manifest.json
    cards/stem_0.json
    assets/<audio_sha256>.wav
  <generation_id>.hapaBundle.zip
```

The legacy manifest includes:

- `generation_id`
- `stems[].path`
- `stems[].start_seconds`
- `stems[].bpm`
- `alignment.target_duration_seconds`
- source node metadata

Local validation:

```bash
PYTHONPATH=python python3 -m hapa_drama_node.cli cymatica-validate --bundle-path artifacts/cymatica/<generation_id>
```

The validator checks the bundle directory, `cymatica_manifest.json`, manifest type/version, generation id, relative stem paths, bundle path confinement, stem existence, non-empty stem bytes, and WAV signatures.

Cymatica handoff validation:

```bash
PYTHONPATH=python python3 -m hapa_drama_node.cli cymatica-handoff-validate --path artifacts/cymatica/<generation_id>/hapa_bundle
PYTHONPATH=python python3 -m hapa_drama_node.cli cymatica-handoff-validate --path artifacts/cymatica/<generation_id>/<generation_id>.hapaBundle.zip
```

The handoff bundle mirrors Cymatica's existing ingest contract: `bundle_manifest.json` with `card_paths`, stem cards under `cards/`, content-addressed audio under `assets/`, SHA-256 artifact hashes, and `spec_hash` computed from sorted minified JSON to match `HapaBundleValidator`.

The authenticated API endpoint `GET /v1/generations/{generation_id}/cymatica-handoff` returns the `.hapaBundle.zip` for direct Cymatica drag/drop or open/import flows.

Next integration pass should add measured stem alignment tests.
