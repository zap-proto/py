# SPDX-License-Identifier: BSD-3-Clause-Eco
"""Whitespace-significant ``.zap`` source → the canonical brace form.

Faithful peer of ``zap-proto/go``'s ``cmd/zapgen/desugar.go``. It runs BEFORE
the parser so the proven brace grammar stays untouched, and the transform is
deliberately a near-identity: it only ADDS the two tokens the brace grammar
requires where the whitespace form omits them.

- A block header (``struct <Id>``) not already terminated by ``{`` gets a
  trailing ``{``, and a matching ``}`` is inserted (at the header's indent)
  where the indented body ends.
- A field written ``Name Type`` (no trailing ``@N``) gets ``@<off>``
  appended, where ``<off>`` is the running byte offset accumulated from the
  declared slot width of the preceding fields in the same struct. An
  explicit ``@N`` is preserved and resets the cursor to ``N + slot``.

Consequence: a pure-brace file — every header ends in ``{``, every field
carries ``@N`` — round-trips byte-for-byte unchanged. Styles may be mixed
per top-level declaration.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from ._ast import SchemaError
from ._parse import parse_type

#: A field's declared byte offset is bounded: an offset far beyond any real
#: message size is a typo, not a layout. Rejecting it keeps parsing total.
MAX_OFFSET = 1 << 31

#: The keywords that open a whitespace-mode block. A struct body holds
#: fields (offsets auto-assigned); an interface body holds methods (passed
#: through verbatim — they carry no ``@N``).
_OPENERS = ("struct", "interface")

#: The one token that begins a file-scope construct and therefore can never
#: be a field name. ``struct``/``interface``/``type``/``enum`` ARE valid
#: field names (``struct u8 @0``, ``type u8 @0``): a real header is claimed
#: by :func:`_header_keyword` first, and a top-level alias is excluded by
#: the ``=`` test in :func:`_is_field`.
_RESERVED = frozenset({"package"})


class _Kind(enum.Enum):
    TRANSPARENT = enum.auto()  # blank or full-line '#' comment
    OTHER = enum.auto()  # package, type alias, brace lines, …
    HEADER = enum.auto()  # whitespace-mode block header
    FIELD = enum.auto()  # whitespace-mode field (Name Type …)


class _Mode(enum.Enum):
    FILE = enum.auto()  # file scope: no enclosing block
    STRUCT = enum.auto()  # struct body: fields, offsets auto-assigned
    IFACE = enum.auto()  # interface body: methods, passed through verbatim


@dataclass(frozen=True, slots=True)
class _Line:
    """One physical source line plus its derived facts."""

    raw: str
    indent: int
    body: str
    kind: _Kind
    keyword: str = ""


# ── line-level helpers (comment-aware, string-level) ──────────────────────


def _strip_comment(body: str) -> str:
    """Drop a trailing ``#`` comment and the space around it."""
    i = body.find("#")
    return body[:i].strip() if i >= 0 else body


def _after(body: str, word: str) -> str | None:
    """Text following ``word``, or ``None`` when ``body`` does not open with it."""
    if not body.startswith(word):
        return None
    rest = body[len(word) :]
    if rest == "" or rest[0] not in " \t":
        return None  # bare keyword, or `structFoo` — one identifier
    return rest.strip()


def _first(s: str) -> tuple[str, str]:
    """Split the leading whitespace-delimited token from the rest."""
    s = s.lstrip(" \t")
    for i, c in enumerate(s):
        if c in " \t":
            return s[:i], s[i:].lstrip(" \t")
    return s, ""


def _is_ident(s: str) -> bool:
    """``[A-Za-z_]\\w*`` — the ASCII identifier the header rule matches."""
    if not s:
        return False
    if not (s[0].isascii() and (s[0].isalpha() or s[0] == "_")):
        return False
    return all(c.isascii() and (c.isalnum() or c == "_") for c in s[1:])


def _header_keyword(body: str) -> str:
    """The opener keyword when ``body`` is a braceless block header, else ``""``.

    A braceless header is EXACTLY ``<opener>`` + one identifier +
    end-of-line. It deliberately does NOT match a field whose NAME is
    ``struct``/``interface`` and that carries a type and/or ``@offset``
    (``struct u8 @0``), nor ``structFoo``, nor a brace header ``struct S {``.
    """
    body = _strip_comment(body)
    if body.endswith("{"):
        return ""
    for word in _OPENERS:
        rest = _after(body, word)
        if rest is None:
            continue
        name, tail = _first(rest)
        if _is_ident(name) and tail == "":
            return word
    return ""


def _is_field(body: str) -> bool:
    """Is ``body`` a whitespace-mode field, i.e. at least ``Name Type``?"""
    stripped = _strip_comment(body)
    if any(c in stripped for c in "{}="):
        return False
    name, tail = _first(stripped)
    if not name or not tail or name in _RESERVED:
        return False
    return _first(tail)[0] != ""


def _classify(raw: str) -> _Line:
    body = raw.strip()
    indent = len(raw) - len(raw.lstrip(" \t"))
    if body == "" or body.startswith("#"):
        return _Line(raw, indent, body, _Kind.TRANSPARENT)
    word = _header_keyword(body)
    if word:
        return _Line(raw, indent, body, _Kind.HEADER, word)
    if _is_field(body):
        return _Line(raw, indent, body, _Kind.FIELD)
    return _Line(raw, indent, body, _Kind.OTHER)


def _split_lines(src: str) -> list[_Line]:
    """Split on ``\\n``, dropping one trailing empty element."""
    parts = src.split("\n")
    if parts and parts[-1] == "":
        parts.pop()
    return [_classify(p) for p in parts]


def _brace_delta(raw: str) -> int:
    """Net ``{`` minus ``}`` on a line, ignoring text after a ``#``."""
    d = 0
    for c in raw:
        if c == "#":
            return d
        if c == "{":
            d += 1
        elif c == "}":
            d -= 1
    return d


def _offset(text: str) -> int:
    """Parse an unsigned decimal offset, rejecting anything else.

    An unchecked accumulator turns ``@18446744073709551616`` into 0, which
    silently aliases onto field offset 0 in the zero-copy layout.
    """
    if not text or not all("0" <= c <= "9" for c in text):
        raise SchemaError(f'not a number: "{text}"' if text else "empty integer")
    n = int(text)
    if n > MAX_OFFSET:
        raise SchemaError(f'offset "{text}" out of range (max {MAX_OFFSET})')
    return n


def _split_field(body: str) -> tuple[str, str, int, bool]:
    """``Name Type [@N]`` → ``(name, type, offset, offset_was_explicit)``."""
    body = _strip_comment(body)
    name, rest = _first(body)
    if not name or not rest:
        raise SchemaError(f'malformed field "{body}"')
    typ, rest = _first(rest)
    if not typ:
        raise SchemaError(f'field "{name}" missing type')
    rest = rest.strip()
    if rest == "":
        return name, typ, 0, False
    if not rest.startswith("@"):
        raise SchemaError(f'field "{name}": unexpected trailing "{rest}"')
    try:
        return name, typ, _offset(rest[1:].strip()), True
    except SchemaError as e:
        raise SchemaError(f'field "{name}": bad @offset: {e}') from None


def _block_end(lines: list[_Line], start: int, end: int, header_indent: int) -> int:
    """One past the last line belonging to a block opened at ``header_indent``.

    Blank/comment lines are absorbed so they neither open nor close a block,
    then trimmed back out so a blank line between two top-level structs
    closes the first cleanly.
    """
    i = start
    while i < end:
        ln = lines[i]
        if ln.kind is _Kind.TRANSPARENT:
            i += 1
            continue
        if ln.indent <= header_indent:
            break
        i += 1
    while i > start and lines[i - 1].kind is _Kind.TRANSPARENT:
        i -= 1
    return i


def _collect_aliases(lines: list[_Line]) -> dict[str, str]:
    """Record top-level ``type X = <expr>`` so field offsets can size them.

    A type alias is ONLY a top-level construct, so a struct field literally
    named ``type`` is not scanned as an alias — it stays a field.
    """
    out: dict[str, str] = {}
    depth = 0
    for ln in lines:
        top = depth == 0 and ln.indent == 0
        depth += _brace_delta(ln.raw)
        if not top:
            continue
        body = _strip_comment(ln.body)
        rest = _after(body, "type")
        if rest is None:
            continue
        if "=" not in rest:
            raise SchemaError(f'alias "{body}" missing "="')
        name, _, expr = rest.partition("=")
        name, expr = name.strip(), expr.strip()
        if not name or not expr:
            raise SchemaError(f'malformed alias "{body}"')
        out[name] = expr
    return out


class _Rewriter:
    """Accumulates the brace-form output line by line."""

    __slots__ = ("aliases", "out")

    def __init__(self, aliases: dict[str, str]) -> None:
        self.aliases = aliases
        self.out: list[str] = []

    def walk(self, lines: list[_Line], start: int, end: int, mode: _Mode) -> None:
        """Rewrite the run of lines belonging to one block.

        A struct header recurses with a FRESH offset cursor (offsets reset
        per struct); an interface header recurses in method mode.
        """
        cursor = 0
        i = start
        while i < end:
            ln = lines[i]
            if ln.kind is _Kind.TRANSPARENT:
                self.out.append(ln.raw)
                i += 1
                continue
            # A line that opens a literal brace block is brace syntax: copy
            # it and everything up to its matching '}' verbatim.
            if _brace_delta(ln.raw) > 0:
                i = self._copy_braces(lines, i, end)
                continue
            # A whitespace header opens a sub-block ONLY at file scope.
            # Inside a struct body `interface text` is a field named
            # `interface`; inside an interface body it is a method.
            if ln.kind is _Kind.HEADER and mode is _Mode.FILE:
                i = self._open(lines, i, end, ln)
                continue
            if mode is _Mode.STRUCT:
                name, typ, off, explicit = _split_field(ln.body)
                if not explicit:
                    off = cursor
                cursor = off + self._slot(name, typ)
                self.out.append(f"{' ' * ln.indent}{name} {typ} @{off}")
            else:
                # File scope or interface body: verbatim. At file scope an
                # un-headered field-shaped line is left for the parser to
                # diagnose precisely; interface methods carry no @N.
                self.out.append(ln.raw)
            i += 1

    def _open(self, lines: list[_Line], i: int, end: int, ln: _Line) -> int:
        """Open a whitespace block, rewrite its body, close the brace."""
        self.out.append(f"{' ' * ln.indent}{_strip_comment(ln.body)} {{")
        body_end = _block_end(lines, i + 1, end, ln.indent)
        mode = _Mode.IFACE if ln.keyword == "interface" else _Mode.STRUCT
        self.walk(lines, i + 1, body_end, mode)
        self.out.append(f"{' ' * ln.indent}}}")
        return body_end

    def _copy_braces(self, lines: list[_Line], i: int, end: int) -> int:
        depth = 0
        while i < end:
            self.out.append(lines[i].raw)
            depth += _brace_delta(lines[i].raw)
            i += 1
            if depth <= 0:
                break
        return i

    def _slot(self, name: str, typ: str) -> int:
        """Fixed-section byte width of ``typ``, through the real type parser."""
        expr = self.aliases.get(typ, typ)
        try:
            width = parse_type(expr).slot
        except SchemaError as e:
            raise SchemaError(f'field "{name}": {e}') from None
        if width == 0:
            raise SchemaError(f'field "{name}": type "{typ}" has zero slot width')
        return width


def desugar(src: str) -> str:
    """Rewrite whitespace-significant ``src`` into canonical brace form."""
    lines = _split_lines(src)
    r = _Rewriter(_collect_aliases(lines))
    r.walk(lines, 0, len(lines), _Mode.FILE)
    out = "\n".join(r.out)
    # Preserve the source's final-newline state so pure-brace files
    # round-trip byte-for-byte (_split_lines dropped one trailing "").
    return out + "\n" if src.endswith("\n") else out
