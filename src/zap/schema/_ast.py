# SPDX-License-Identifier: BSD-3-Clause-Eco
"""The parsed shape of one ``.zap`` source file.

Faithful peer of ``zap-proto/go``'s ``cmd/zapgen/schema.go``: same names,
same slot widths, same meaning. One source file produces one :class:`File`
carrying a package name (``package foo``), a set of type aliases
(``type sig96 = bytes_fixed[96]``), and the declared structs and interfaces.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class Kind(enum.Enum):
    """The schema's primitive type tags.

    ``str(kind)`` is the schema spelling, used in error messages.
    """

    BOOL = "bool"
    U8 = "u8"
    U16 = "u16"
    U32 = "u32"
    U64 = "u64"
    I8 = "i8"
    I16 = "i16"
    I32 = "i32"
    I64 = "i64"
    F32 = "f32"
    F64 = "f64"
    BYTES = "bytes"
    BYTES_FIXED = "bytes_fixed"
    TEXT = "text"
    LIST = "list"
    STRUCT = "struct"

    def __str__(self) -> str:
        return self.value


#: Byte width of each fixed-width slot in an object's fixed section.
#: A variable-length tail (bytes/text/list) stores ``{rel_off u32, len u32}``
#: = 8 bytes; a nested-struct pointer stores ``{rel_off u32}`` = 4 bytes.
_WIDTH: dict[Kind, int] = {
    Kind.BOOL: 1,
    Kind.U8: 1,
    Kind.I8: 1,
    Kind.U16: 2,
    Kind.I16: 2,
    Kind.U32: 4,
    Kind.I32: 4,
    Kind.F32: 4,
    Kind.U64: 8,
    Kind.I64: 8,
    Kind.F64: 8,
    Kind.BYTES: 8,
    Kind.TEXT: 8,
    Kind.LIST: 8,
    Kind.STRUCT: 4,
}


@dataclass(frozen=True, slots=True)
class Type:
    """A field's resolved type.

    Exactly one detail field carries meaning: ``fixed_size`` for
    ``bytes_fixed[N]``, ``elem`` for ``list<T>``, ``struct_name`` for a
    nested struct reference.
    """

    kind: Kind
    fixed_size: int = 0
    elem: Type | None = None
    struct_name: str = ""

    @property
    def slot(self) -> int:
        """Byte width of this type in the fixed section (0 = unsupported)."""
        if self.kind is Kind.BYTES_FIXED:
            return self.fixed_size
        return _WIDTH.get(self.kind, 0)


@dataclass(slots=True)
class Field:
    """One struct field. ``offset`` is author-controlled (the ``@N``)."""

    name: str
    type: Type
    offset: int


@dataclass(slots=True)
class Struct:
    """One declared struct."""

    name: str
    fields: list[Field] = field(default_factory=list)

    @property
    def size(self) -> int:
        """Fixed-section size: ``max(offset + slot)`` over the fields."""
        return max((f.offset + f.type.slot for f in self.fields), default=0)


@dataclass(frozen=True, slots=True)
class Param:
    """One method parameter (``name: StructName``); payloads are structs."""

    name: str
    struct_name: str


@dataclass(slots=True)
class Method:
    """One service method.

    ``ordinal`` is the 1-based wire id assigned by declaration order, so
    appending a method never renumbers the earlier ones.
    """

    name: str
    ordinal: int
    request: Param | None = None
    response: Param | None = None


@dataclass(slots=True)
class Interface:
    """One declared RPC service."""

    name: str
    methods: list[Method] = field(default_factory=list)


@dataclass(slots=True)
class File:
    """The parsed contents of one ``.zap`` source file."""

    package: str = ""
    source: str = ""
    aliases: dict[str, Type] = field(default_factory=dict)
    structs: list[Struct] = field(default_factory=list)
    interfaces: list[Interface] = field(default_factory=list)


class SchemaError(ValueError):
    """A ``.zap`` source is malformed, or its layout is unsound."""
