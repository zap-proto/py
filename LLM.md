# zap-proto (Python) — ZAP zero-copy app proto

Python ZAP implementation. Full docs in README.md. PyPI dist name `zap-proto`,
import `zap`. The core is pure stdlib — `import zap` pulls no third-party dep.

`src/zap/`:

- `wire` — the zero-copy codec. Pure-stdlib port of the canonical Go runtime
  (`zap-proto/go`: zap.go + builder.go + accessors.go + list_cursor.go).
  `Message`/`Object`/`List` reads + `Builder`/`ObjectBuilder`/`ListBuilder`
  writes; 16-byte `ZAP\x00` header; Version1+2 accept; reader hardening
  (reject backward pointers into the header, clamp list length). Byte-faithful
  to Go — pinned by the shared golden vector in `tests/test_wire.py`.
- `rpc` — real TCP request/response transport. `Server` dispatches the `Zap`
  interface method ordinals (`Method` enum, @0..@8 from `zap.zap`); `Client`
  calls them. JSON body, magic-framed envelope (reuses `protocol`).
- `frame` — the `zapd` router-envelope codec, byte-compatible with
  `zap-proto/zapd/src/frame.rs` + `ZapClient` (connect / hello / providers.list
  / route). Used by `hanzo-tools-browser`'s `zapd_consumer`.
- `protocol` — magic-framed JSON framing (`ZAP\x01` + type + length + JSON);
  `decode_stream` demuxes back-to-back frames.
- `app` — FastMCP-style decorator app (`ZAP`); `run()` serves real `rpc`.
  Needs the `[app]` extra (pydantic). Lazy-imported from `zap/__init__.py`.
- `client` — `Client` (sync RPC over `rpc`) + `ZapClient` (router UDS).
- `crypto` — real ML-KEM-768 / ML-DSA-65 (pqcrypto) + X25519 (cryptography),
  hybrid HKDF-SHA256 KEX. Needs the `[crypto]` extra. Hard-fails with
  `CryptoError` when a backend is missing — never fabricates bytes.
- `identity` — W3C DID (`did:lux`/`did:key`/`did:web`). `consensus` — voting.

Gates (CI in `.github/workflows/ci.yml`): `ruff check`, `ruff format --check`,
`mypy --strict src/zap/`, `pytest` — all green. Use `uv` for the venv.
