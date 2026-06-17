# zap-proto (Python) — ZAP zero-copy app proto

Python ZAP implementation. Full docs in README.md. PyPI dist name `zap-proto`,
import `zap`.

- `src/zap/` — runtime: `frame` (the router-envelope codec, mirrors
  `zap-proto/zapd/src/frame.rs`) + `ZapClient` (connect / hello / providers.list /
  route). Used by `hanzo-tools-browser`'s `zapd_consumer`.
