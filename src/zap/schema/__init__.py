# SPDX-License-Identifier: BSD-3-Clause-Eco
"""Native ``.zap`` schema support: read a schema, generate Python bindings.

The ZAP schema is whitespace-significant — indentation, no braces::

    package chat

    struct Person
      name text
      email text
      phones list<Phone>

Reading it is two steps, exactly as in ``zap-proto/go``:
:func:`desugar` rewrites the whitespace form into the canonical brace form
(a near-identity that only ADDS the ``{``/``}`` and ``@offset`` tokens the
brace grammar requires), then the proven brace parser runs unchanged. A
pure-brace schema round-trips through :func:`desugar` byte-for-byte, so both
styles are one grammar, and the two languages read a schema the same way.

:func:`parse` gives the AST; :func:`emit` renders it to a Python module of
zero-copy views over :mod:`zap.wire` plus typed clients over
:mod:`zap.pipeline`. ``python -m zap.schema SCHEMA.zap`` does both.
"""

from __future__ import annotations

from ._ast import (
    Field,
    File,
    Interface,
    Kind,
    Method,
    Param,
    SchemaError,
    Struct,
    Type,
)
from ._desugar import desugar
from ._emit import emit, validate, validate_interface
from ._parse import parse_brace

__all__ = [
    "Field",
    "File",
    "Interface",
    "Kind",
    "Method",
    "Param",
    "SchemaError",
    "Struct",
    "Type",
    "desugar",
    "emit",
    "parse",
    "parse_brace",
    "validate",
    "validate_interface",
]


def parse(filename: str, src: str) -> File:
    """Read one ``.zap`` source — either style — into a :class:`File`."""
    return parse_brace(filename, desugar(src))
