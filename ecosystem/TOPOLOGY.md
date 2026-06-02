# Hapa Drama Topology

`hapa-drama` is a local voice synthesis node.

Control plane:

- Authenticated loopback HTTP API.
- Other Hapa nodes call `POST /v1/commands` with the standard command envelope.

Data/provenance plane:

- Append-only JSONL event log scaffold.
- SQLite projection for voices/generations/events.
- Card JSON minting scaffold for generated audio.
- Future Hypercore integration should mirror every command/event and card index entry.

Peers:

- Cards service
- Cymatica
- Avatars
- Phamiliars
- Comms
- LLM
