# Security

- Bind local services to `127.0.0.1` by default.
- Require bearer auth for all non-public endpoints.
- Public endpoints are limited to `/` and `/health`.
- Store the node token in `.node_token` with restrictive permissions.
- Do not commit `.node_token`, API keys, model credentials, generated audio, SQLite databases, or model weights.
- LAN exposure must be explicit and should use trusted LAN, VPN, or SSH tunnel.
- Query-token auth is disabled by default and should only be enabled for local debugging.
