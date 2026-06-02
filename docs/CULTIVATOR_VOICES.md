# Cultivator Voices

Cultivator voices are persistent voice profiles with measurable entanglement state.

Current scaffold fields:

- `voice_id`
- `display_name`
- `entanglement_level`
- `xp`
- `generation_count`
- `traits`
- `created_at`
- `updated_at`

Current progression:

- `voice.create` creates a profile.
- Synthesis with `payload.voice_id` adds 10 XP.
- `voice.entangle` adds explicit XP.
- Entanglement level is `floor(xp / 100)`.

Integrity rule: only persisted metrics should be described as improvement.
