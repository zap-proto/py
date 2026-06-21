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
- `cap` — the capability runtime (signed, attenuable authority tokens). Faithful
  port of `zap-proto/go/cap` over the `capabilities.zap` v1.1 schema. `wrap`,
  `Cap` view, `canonical_bytes` (SPEC §3 signed scope — byte-identical to Go),
  `id` = `SHA-256(canonical_bytes ‖ Sig)` (SPEC §4). `Issuance`/`issue`/
  `attenuate` enforce the SPEC §2.3 delegation gate at MINT time (parent needs
  `PERM_ATTENUATE` or `CapKind.DELEGATE`), monotonic permission narrowing,
  holder→issuer linkage, and downward-only expiry. `Verifier.verify` /
  `verify_chain` enforce the full §2.3 invariants with FAIL-CLOSED scheme
  dispatch (reserved tag `0x00` and unknown tags refused — never downgraded).
  `Revocation`/`revoke`/`verify_revocation` (scheme-aware). Schemes: Ed25519
  (mandatory bootstrap), ML-DSA-65 (FIPS 204), secp256k1 ECDSA — all real and
  verified; a missing backend raises `SchemeUnavailable` (an
  `UnhandledSchemeError`, so fail-closed). Wire/canonical/CapID paths are pure
  stdlib; signing needs the `[crypto]` extra. Cross-language interop is pinned
  by `tests/testdata/cap_go_kat.{hex,json}` — a Go-signed cap that decodes,
  recomputes the same canonical bytes + CapID, and verifies in Python (and a
  deterministic Python re-issue is byte-identical to Go).
- `identity` — W3C DID (`did:lux`/`did:key`/`did:web`). `consensus` — voting.

Gates (CI in `.github/workflows/ci.yml`): `ruff check`, `ruff format --check`,
`mypy --strict src/zap/`, `pytest` — all green. Use `uv` for the venv.
