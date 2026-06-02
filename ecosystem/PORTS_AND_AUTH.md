# Ports + Auth

Service: `hapa-drama`

- Default host: `127.0.0.1`
- Default port: `8758`
- Token file: `.node_token`
- Runtime file: `artifacts/runtime/hapa_drama_runtime.json`
- Auth: bearer token for all endpoints except `/` and `/health`
- Local session bootstrap: `/local/session` is loopback-only and used by browser/Electron UI
- Query token auth: disabled by default; enable only with `HAPA_DRAMA_ALLOW_QUERY_TOKEN=1`

Environment variables:

- `HAPA_DRAMA_HOST`
- `HAPA_DRAMA_PORT`
- `HAPA_DRAMA_TOKEN`
- `HAPA_DRAMA_TOKEN_FILE`
- `HAPA_DRAMA_STORAGE_DIR`
- `HAPA_DRAMA_RUNTIME_FILE`
