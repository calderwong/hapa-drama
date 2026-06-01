<!-- HAPA-CONNECTIVITY-DOC:BEGIN -->
# Hapa Connectivity

Generated: 2026-06-01T01:03:18.083Z

This file is a publication-safe cross-link for humans and AIs. It describes how this repo fits into the Hapa system without embedding private local paths, secrets, heavy assets, DB payloads, or generated media.

## Identity

- Node id: `hapa-drama`
- Repo name: `hapa-drama`
- Hapa system group: `nodes/generation` (Nodes / Generation)
- Target assembly path: `hapa-system/nodes/generation/hapa-drama`
- Link mode: `local_workspace_pointer_until_remote_exists`

## Role

This node participates in generation workflows and should read private prompts/assets from the vault while keeping generated outputs out of source Git.

## Reads From

- Hapa ecosystem docs and node manifests.
- Wiki pages or operations docs when this node needs canonical human context.
- Second Brain relation exports or memory summaries when this node needs durable recall.
- Private assets and generated media through `$HAPA_VAULT_ROOT`, not checked-in binaries.

## Writes To

- Source-safe docs, schemas, manifests, or small fixtures that can pass publication preflight.
- Generated media metadata and vault pointer manifests; heavy outputs remain in `$HAPA_VAULT_ROOT`.

## Related Hapa Nodes

| Node | Relationship |
| --- | --- |
| `hapa` | Front door and ecosystem map. |
| `Hapa_Worldbuilding_Wiki` | Canonical wiki and operations knowledge. |
| `hapa_second_brain` | Durable memory, SQLite relation exports, and recall surface. |
| `hapa-overwatch-kanban` | Append-only project board and event protocol. |
| `hapa-quest-keeper` | Consolidated Quest board overview and board coverage audit. |
| `hapa-avatar-node` | Shares the Nodes / Generation module group. |
| `hapa-lito` | Shares the Nodes / Generation module group. |
| `hapa-llada-node` | Shares the Nodes / Generation module group. |
| `hapa-luminastem-station` | Shares the Nodes / Generation module group. |
| `hapa-mlx-station` | Shares the Nodes / Generation module group. |

## Shared Control Surfaces

- `hapa`: front door, operator map, and ecosystem entry point.
- `Hapa_Worldbuilding_Wiki`: canonical human-readable lore, operations, and node documentation.
- `hapa_second_brain`: durable memory, relation exports, and local-first recall surface.
- `hapa-overwatch-kanban`: append-only board/event protocol for node work.
- `hapa-quest-keeper`: consolidated board overview and app coverage audit.
- `$HAPA_VAULT_ROOT`: private companion root for heavy assets, runtime DBs, generated media, and relation exports.

## Publication Boundary

- Publication strategy: `prepublish_secret_filename_review_required`
- Publication wave: `wave_2_small_dirty_no_remote`
- Current assembly gate: `local_pointer_after_review`

Source code, docs, schemas, and tiny fixtures are Git candidates after preflight. Runtime DBs, WAL/SHM files, local tokens, generated media, model weights, logs, app bundles, and vault exports stay out of public Git and should be represented by pointer manifests or rebuild instructions.

## Open Gates

- Review 21 dirty working-tree entries before pinning.
- Choose GitHub owner, repo name, and private/public visibility before remote creation.

## Safe Next Commands

- `git status --short`
- `Commit only intentional docs/source changes after reviewing the dirty worktree.`
- `Choose GitHub owner, repo name, and private/public visibility before remote creation.`
- `Run gitleaks/history scan before public release.`
- `Do not move repos, create remotes, push, purge, copy heavy assets, or rewrite history without the matching approval gate.`

## Verification

Run the fastest local checks that exist for this repo before publication or assembly:

```bash
git status --short
python -m compileall .
```

<!-- HAPA-CONNECTIVITY-DOC:END -->
