# SPDX-License-Identifier: BSD-3-Clause-Eco
"""``python -m zap.schema SCHEMA.zap`` — generate Python bindings.

One schema emits one module, ``<schema>_zap.py``, next to the input unless
``--out`` says otherwise::

    python -m zap.schema chat.zap            # writes chat_zap.py beside it
    python -m zap.schema --out gen chat.zap  # writes gen/chat_zap.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import SchemaError, emit, parse


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m zap.schema",
        description="Read a .zap schema and emit its Python bindings.",
    )
    ap.add_argument("schema", type=Path, help="the .zap source file")
    ap.add_argument(
        "--out", type=Path, default=None, help="output directory (default: the schema's own)"
    )
    args = ap.parse_args(argv)

    try:
        file = parse(str(args.schema), args.schema.read_text(encoding="utf-8", errors="replace"))
        name, body = emit(file)
    except SchemaError as e:
        print(f"zap.schema: {e}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"zap.schema: {e}", file=sys.stderr)
        return 1

    out = args.out if args.out is not None else args.schema.parent
    out.mkdir(parents=True, exist_ok=True)
    (out / name).write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
