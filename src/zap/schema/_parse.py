# SPDX-License-Identifier: BSD-3-Clause-Eco
"""The brace-form ``.zap`` parser.

Faithful peer of ``zap-proto/go``'s ``cmd/zapgen/parser.go`` — same grammar,
same errors, same acceptance. Whitespace-significant source is rewritten into
this brace form first (see :mod:`zap.schema._desugar`); pure-brace source
passes through that step byte-for-byte, so this grammar is the whole story::

    File   := 'package' Ident (Alias | Struct | Interface)*
    Alias  := 'type' Ident '=' Type
    Struct := 'struct' Ident '{' Field* '}'
    Field  := Ident Type '@' Int
    Interface := 'interface' Ident '{' Method* '}'
    Method := Ident '(' Param? ')' ('returns' '(' Param? ')')?
    Param  := Ident ':' Ident
    Type   := 'list' '<' Type '>' | 'bytes_fixed' '[' Int ']' | Primitive | Ident
"""

from __future__ import annotations

import unicodedata

from ._ast import Field, File, Interface, Kind, Method, Param, SchemaError, Struct, Type

#: Primitive spellings, longest first so ``u8`` never shadows a longer name.
#: Order is irrelevant here because :meth:`_Parser._keyword` requires the
#: match to end on a non-identifier rune, but the table stays sorted by
#: spelling for reading.
_PRIMITIVE: dict[str, Kind] = {
    "bool": Kind.BOOL,
    "u8": Kind.U8,
    "u16": Kind.U16,
    "u32": Kind.U32,
    "u64": Kind.U64,
    "i8": Kind.I8,
    "i16": Kind.I16,
    "i32": Kind.I32,
    "i64": Kind.I64,
    "f32": Kind.F32,
    "f64": Kind.F64,
    "bytes": Kind.BYTES,
    "text": Kind.TEXT,
}


def _is_letter(c: str) -> bool:
    """Unicode category L — the peer of Go's ``unicode.IsLetter``."""
    return unicodedata.category(c).startswith("L")


def _is_digit(c: str) -> bool:
    """Unicode category Nd — the peer of Go's ``unicode.IsDigit``."""
    return unicodedata.category(c) == "Nd"


def is_ident_start(c: str) -> bool:
    return c == "_" or _is_letter(c)


def is_ident_rune(c: str) -> bool:
    return c == "_" or _is_letter(c) or _is_digit(c)


def base_name(path: str) -> str:
    """Final path element of ``path`` (both separators, no import needed)."""
    for i in range(len(path) - 1, -1, -1):
        if path[i] in "/\\":
            return path[i + 1 :]
    return path


class _Parser:
    """A cursor over one desugared source, plus the recursive-descent rules."""

    __slots__ = ("src", "pos", "line", "filename", "file")

    def __init__(self, src: str, filename: str = "", file: File | None = None) -> None:
        self.src = src
        self.pos = 0
        self.line = 1
        self.filename = filename
        self.file = file if file is not None else File()

    # ── cursor primitives ──────────────────────────────────────────────

    def fail(self, msg: str) -> SchemaError:
        return SchemaError(f"{self.filename}:{self.line}: {msg}")

    def skip_space(self) -> None:
        """Advance past whitespace and ``#`` comments."""
        src, n = self.src, len(self.src)
        while self.pos < n:
            c = src[self.pos]
            if c == "\n":
                self.line += 1
                self.pos += 1
            elif c in " \t\r":
                self.pos += 1
            elif c == "#":
                while self.pos < n and src[self.pos] != "\n":
                    self.pos += 1
            else:
                return

    def peek(self) -> str:
        return self.src[self.pos] if self.pos < len(self.src) else ""

    def keyword(self, word: str) -> bool:
        """Do the upcoming runes spell ``word`` followed by a non-ident rune?"""
        end = self.pos + len(word)
        if end > len(self.src) or self.src[self.pos : end] != word:
            return False
        return end == len(self.src) or not is_ident_rune(self.src[end])

    def take(self, word: str) -> None:
        """Consume a keyword already matched by :meth:`keyword`."""
        self.pos += len(word)

    def ident(self) -> str:
        """Read an identifier, or return ``""`` when none is here."""
        start = self.pos
        if self.pos >= len(self.src) or not is_ident_start(self.src[self.pos]):
            return ""
        self.pos += 1
        while self.pos < len(self.src) and is_ident_rune(self.src[self.pos]):
            self.pos += 1
        return self.src[start : self.pos]

    def integer(self) -> int:
        start = self.pos
        while self.pos < len(self.src) and "0" <= self.src[self.pos] <= "9":
            self.pos += 1
        if self.pos == start:
            raise self.fail("expected integer")
        return int(self.src[start : self.pos])

    def expect(self, lit: str) -> None:
        end = self.pos + len(lit)
        if end > len(self.src) or self.src[self.pos : end] != lit:
            raise self.fail(f'expected "{lit}"')
        self.line += lit.count("\n")
        self.pos = end

    # ── grammar ───────────────────────────────────────────────────────

    def file_decl(self) -> File:
        self.skip_space()
        if not self.keyword("package"):
            raise self.fail("expected `package` declaration")
        self.take("package")
        self.skip_space()
        name = self.ident()
        if not name:
            raise self.fail("expected package name after `package`")
        self.file.package = name

        while True:
            self.skip_space()
            if self.pos >= len(self.src):
                return self.file
            if self.keyword("struct"):
                self.file.structs.append(self.struct())
            elif self.keyword("interface"):
                self.file.interfaces.append(self.interface())
            elif self.keyword("type"):
                self.alias()
            else:
                raise self.fail("expected `struct`, `interface`, or `type` at top level")

    def alias(self) -> None:
        self.take("type")
        self.skip_space()
        name = self.ident()
        if not name:
            raise self.fail("expected alias name after `type`")
        self.skip_space()
        self.expect("=")
        self.skip_space()
        t = self.type()
        if name in self.file.aliases:
            raise self.fail(f'duplicate type alias "{name}"')
        self.file.aliases[name] = t

    def struct(self) -> Struct:
        self.take("struct")
        self.skip_space()
        name = self.ident()
        if not name:
            raise self.fail("expected struct name")
        self.skip_space()
        self.expect("{")
        s = Struct(name=name)
        while True:
            self.skip_space()
            if self.pos >= len(self.src):
                raise self.fail(f'unterminated struct "{name}"')
            if self.src[self.pos] == "}":
                self.pos += 1
                return s
            s.fields.append(self.field())

    def interface(self) -> Interface:
        self.take("interface")
        self.skip_space()
        name = self.ident()
        if not name:
            raise self.fail("expected interface name")
        self.skip_space()
        self.expect("{")
        iface = Interface(name=name)
        ordinal = 1
        while True:
            self.skip_space()
            if self.pos >= len(self.src):
                raise self.fail(f'unterminated interface "{name}"')
            if self.src[self.pos] == "}":
                self.pos += 1
                return iface
            iface.methods.append(self.method(ordinal))
            ordinal += 1

    def method(self, ordinal: int) -> Method:
        name = self.ident()
        if not name:
            raise self.fail("expected method name")
        self.skip_space()
        request = self.params()
        self.skip_space()
        response = None
        if self.keyword("returns"):
            self.take("returns")
            self.skip_space()
            response = self.params()
        return Method(name=name, ordinal=ordinal, request=request, response=response)

    def params(self) -> Param | None:
        """``( name : StructType )`` or ``()``; one payload per direction."""
        self.expect("(")
        self.skip_space()
        if self.pos < len(self.src) and self.src[self.pos] == ")":
            self.pos += 1
            return None
        pname = self.ident()
        if not pname:
            raise self.fail("expected parameter name")
        self.skip_space()
        self.expect(":")
        self.skip_space()
        tname = self.ident()
        if not tname:
            raise self.fail("expected parameter type")
        self.skip_space()
        if self.pos < len(self.src) and self.src[self.pos] == ",":
            raise self.fail("method params carry exactly one struct payload per direction")
        self.expect(")")
        return Param(name=pname, struct_name=tname)

    def field(self) -> Field:
        name = self.ident()
        if not name:
            raise self.fail("expected field name")
        self.skip_space()
        t = self.type()
        self.skip_space()
        self.expect("@")
        self.skip_space()
        return Field(name=name, type=t, offset=self.integer())

    def type(self) -> Type:
        if self.keyword("list"):
            self.take("list")
            self.skip_space()
            self.expect("<")
            self.skip_space()
            inner = self.type()
            self.skip_space()
            self.expect(">")
            return Type(kind=Kind.LIST, elem=inner)
        if self.keyword("bytes_fixed"):
            self.take("bytes_fixed")
            self.skip_space()
            self.expect("[")
            self.skip_space()
            n = self.integer()
            if n <= 0:
                raise self.fail("bytes_fixed[N] must have N > 0")
            self.skip_space()
            self.expect("]")
            return Type(kind=Kind.BYTES_FIXED, fixed_size=n)
        for word, kind in _PRIMITIVE.items():
            if self.keyword(word):
                self.take(word)
                return Type(kind=kind)
        name = self.ident()
        if not name:
            raise self.fail(f'expected type, got "{self.peek()}"')
        alias = self.file.aliases.get(name)
        if alias is not None:
            return alias
        return Type(kind=Kind.STRUCT, struct_name=name)


def parse_brace(filename: str, src: str) -> File:
    """Parse already-desugared brace-form ``src`` into a :class:`File`."""
    return _Parser(src, filename, File(source=base_name(filename))).file_decl()


def parse_type(expr: str) -> Type:
    """Parse one standalone type expression (no aliases in scope).

    The single source of truth for how wide a type is — the desugarer sizes
    an auto-assigned field offset through this, so layout is never computed
    twice.
    """
    return _Parser(expr).type()
