# SPDX-License-Identifier: BSD-3-Clause-Eco
"""``.zap`` schema → Python bindings over :mod:`zap.wire` and :mod:`zap.pipeline`.

The peer of ``zap-proto/go``'s ``cmd/zapgen/emit.go``: the same validation
(offset overlap, unsupported type, unknown method payload) and the same
generated shape, spelled in Python.

Each struct becomes a zero-copy view class — ``wrap`` parses a buffer,
properties read fields IN PLACE at their schema offsets, ``build`` writes a
message. Each interface becomes an ordinal enum, a handler ``Protocol``, a
``dispatch`` function, and a typed client.

One schema emits ONE module: a Python module is the unit a Go package is
here, so cross-struct references (a nested view, a method payload) resolve
without any import between generated files.
"""

from __future__ import annotations

import keyword

from ._ast import File, Interface, Kind, Method, SchemaError, Struct, Type

#: Names the generated view already owns. A field spelled like one of these
#: takes the same trailing underscore a Python keyword does.
_CLAIMED = frozenset({"wrap", "build"})

#: Reader accessor and Python result type, per primitive kind.
_READ: dict[Kind, tuple[str, str]] = {
    Kind.BOOL: ("bool", "bool"),
    Kind.U8: ("uint8", "int"),
    Kind.U16: ("uint16", "int"),
    Kind.U32: ("uint32", "int"),
    Kind.U64: ("uint64", "int"),
    Kind.I8: ("int8", "int"),
    Kind.I16: ("int16", "int"),
    Kind.I32: ("int32", "int"),
    Kind.I64: ("int64", "int"),
    Kind.F32: ("float32", "float"),
    Kind.F64: ("float64", "float"),
    Kind.TEXT: ("text", "str"),
    Kind.BYTES: ("bytes", "bytes"),
}

#: Writer setter, per primitive kind.
_WRITE: dict[Kind, str] = {
    Kind.BOOL: "set_bool",
    Kind.U8: "set_uint8",
    Kind.U16: "set_uint16",
    Kind.U32: "set_uint32",
    Kind.U64: "set_uint64",
    Kind.I8: "set_int8",
    Kind.I16: "set_int16",
    Kind.I32: "set_int32",
    Kind.I64: "set_int64",
    Kind.F32: "set_float32",
    Kind.F64: "set_float64",
    Kind.TEXT: "set_text",
    Kind.BYTES: "set_bytes",
}

#: Python parameter type and default literal for a build() keyword.
_INPUT: dict[Kind, tuple[str, str]] = {
    Kind.BOOL: ("bool", "False"),
    Kind.U8: ("int", "0"),
    Kind.U16: ("int", "0"),
    Kind.U32: ("int", "0"),
    Kind.U64: ("int", "0"),
    Kind.I8: ("int", "0"),
    Kind.I16: ("int", "0"),
    Kind.I32: ("int", "0"),
    Kind.I64: ("int", "0"),
    Kind.F32: ("float", "0.0"),
    Kind.F64: ("float", "0.0"),
    Kind.TEXT: ("str", '""'),
    Kind.BYTES: ("bytes", 'b""'),
    Kind.BYTES_FIXED: ("bytes", 'b""'),
    Kind.LIST: ("_Sequence[bytes]", "()"),
    Kind.STRUCT: ("bytes", 'b""'),
}


def py_name(name: str) -> str:
    """The Python spelling of a schema identifier.

    Schema names are carried through verbatim — a generated binding that
    renames its own schema is a second source of truth. The one exception is
    a name already spoken for, either by Python (``from``, ``class``, …) or
    by the view itself (``wrap``, ``build``): that one takes the trailing
    underscore PEP 8 prescribes, which leaves the schema name readable.
    """
    return name + "_" if keyword.iskeyword(name) or name in _CLAIMED else name


def snake(name: str) -> str:
    """CamelCase → snake_case, for module and function names."""
    out: list[str] = []
    for i, c in enumerate(name):
        if i > 0 and c.isupper():
            out.append("_")
        out.append(c.lower())
    return "".join(out)


def validate(s: Struct) -> None:
    """Reject an unsound layout: no fields, bad type, overlap, or a name twice.

    Two fields that answer to the same name is the one place this reader is
    stricter than ``zap-proto/go``, which accepts the schema and emits a Go
    file that does not compile. Silently keeping one of the two would hide a
    schema defect behind generated code.
    """
    size = s.size
    if size == 0:
        raise SchemaError(f"struct {s.name}: no fields")
    owner: list[str] = [""] * size
    taken: dict[str, str] = {}
    for f in s.fields:
        seat = py_name(f.name)
        if seat in taken:
            raise SchemaError(
                f"struct {s.name}: field {f.name} and field {taken[seat]} are both {seat}"
            )
        taken[seat] = f.name
        width = f.type.slot
        if width == 0:
            raise SchemaError(f"struct {s.name} field {f.name}: unsupported type {f.type.kind}")
        if f.offset < 0:
            raise SchemaError(f"struct {s.name} field {f.name}: negative offset {f.offset}")
        for i in range(f.offset, f.offset + width):
            if owner[i]:
                raise SchemaError(
                    f"struct {s.name}: field {f.name} at offset {i} overlaps field {owner[i]}"
                )
            owner[i] = f.name


def validate_interface(f: File, iface: Interface) -> None:
    """Every method payload must name a struct declared in the same file."""
    if not iface.methods:
        raise SchemaError(f"interface {iface.name}: no methods")
    known = {s.name for s in f.structs}
    seen: dict[str, str] = {}
    for m in iface.methods:
        seat = py_name(m.name)
        if seat in seen:
            raise SchemaError(
                f"interface {iface.name}: method {m.name} and method {seen[seat]} are both {seat}"
            )
        seen[seat] = m.name
        for p in (m.request, m.response):
            if p is None:
                continue
            if p.struct_name not in known:
                raise SchemaError(
                    f"interface {iface.name} method {m.name}: "
                    f'unknown struct "{p.struct_name}" in param "{p.name}"'
                )


def _read_type(t: Type) -> str:
    if t.kind is Kind.LIST:
        return "_wire.List"
    if t.kind is Kind.STRUCT:
        return py_name(t.struct_name)
    if t.kind is Kind.BYTES_FIXED:
        return "bytes"
    return _READ[t.kind][1]


def _off(name: str) -> str:
    return f"_{name}Off"


def _struct(w: list[str], s: Struct) -> None:
    validate(s)
    name = py_name(s.name)
    w.append(f"class {name}:")
    w.append(f'    """Zero-copy view into a ZAP-encoded {s.name} message."""')
    w.append("")
    w.append('    __slots__ = ("_o",)')
    w.append("")
    w.append(f"    _Size = {s.size}")
    for f in s.fields:
        w.append(f"    {_off(f.name)} = {f.offset}")
    w.append("")
    w.append("    def __init__(self, o: _wire.Object) -> None:")
    w.append("        self._o = o")
    w.append("")
    w.append("    @classmethod")
    w.append(f"    def wrap(cls, buf: bytes) -> {name}:")
    w.append(f'        """Parse buf into a {s.name} view (raises ZapError on bad wire)."""')
    w.append("        return cls(_wire.parse(buf).root())")

    for f in s.fields:
        w.append("")
        w.append("    @property")
        w.append(f"    def {py_name(f.name)}(self) -> {_read_type(f.type)}:")
        off = f"self.{_off(f.name)}"
        if f.type.kind is Kind.LIST:
            w.append(f"        return self._o.list({off})")
        elif f.type.kind is Kind.STRUCT:
            w.append(f"        return {py_name(f.type.struct_name)}(self._o.object({off}))")
        elif f.type.kind is Kind.BYTES_FIXED:
            w.append(f"        return self._o.bytes_fixed({off}, {f.type.fixed_size})")
        else:
            w.append(f"        return self._o.{_READ[f.type.kind][0]}({off})")

    _build(w, s)
    w.append("")
    w.append("")


def _build(w: list[str], s: Struct) -> None:
    """Emit ``build``.

    Offsets go in as literals, not as ``Cls._XOff``: a keyword parameter takes
    the schema's own field name, and a field named after its own struct would
    otherwise shadow the class for the whole body. The constants above stay
    the readable copy; both come from the one schema.
    """
    w.append("")
    w.append("    @staticmethod")
    w.append("    def build(")
    w.append("        *,")
    for f in s.fields:
        ptype, default = _INPUT[f.type.kind]
        w.append(f"        {py_name(f.name)}: {ptype} = {default},")
    w.append("    ) -> bytes:")
    w.append(f'        """Write a ZAP-encoded {s.name} message and return the bytes."""')
    w.append("        b = _wire.Builder(256)")
    w.append(f"        ob = b.start_object({s.size})")
    for f in s.fields:
        off = str(f.offset)
        val = py_name(f.name)
        kind = f.type.kind
        if kind is Kind.BYTES_FIXED:
            w.append(f"        ob.set_bytes_fixed({off}, {val})")
        elif kind is Kind.LIST:
            lb = f"_list{f.offset}"
            w.append(f"        {lb} = b.start_list(0)")
            w.append(f"        for _elem in {val}:")
            w.append(f"            {lb}.add_object_bytes(_elem)")
            w.append(f"        ob.set_list({off}, {lb}.finish_offset(), len({val}))")
        elif kind is Kind.STRUCT:
            w.append(f"        if {val}:")
            w.append(f"            _nested = b.start_object(len({val}))")
            w.append(f"            _nested.set_bytes_fixed(0, {val})")
            w.append(f"            ob.set_object({off}, _nested.finish())")
        else:
            w.append(f"        ob.{_WRITE[kind]}({off}, {val})")
    w.append("        ob.finish_as_root()")
    w.append("        return b.finish()")


def _args(m: Method) -> tuple[str, str]:
    """The client method's parameter list and its payload expression."""
    if m.request is None:
        return "", 'b""'
    arg = py_name(m.request.name)
    return f", {arg}: bytes", arg


def _interface(w: list[str], f: File, iface: Interface) -> None:
    validate_interface(f, iface)
    name = py_name(iface.name)

    w.append(f"class {name}Method(_enum.IntEnum):")
    w.append(f'    """Method ordinals for the {iface.name} service (stable 1-based wire ids)."""')
    w.append("")
    for m in iface.methods:
        w.append(f"    {py_name(m.name)} = {m.ordinal}")
    w.append("")
    w.append("")

    # Handler: the abstract server contract.
    w.append(f"class {name}Handler(_Protocol):")
    w.append(f'    """Server contract for {iface.name}.')
    w.append("")
    w.append(f"    Route one envelope to it with dispatch_{snake(iface.name)}.")
    w.append('    """')
    w.append("")
    for m in iface.methods:
        arg = f", {py_name(m.request.name)}: bytes" if m.request else ""
        ret = "bytes" if m.response else "None"
        w.append(f"    def {py_name(m.name)}(self{arg}) -> {ret}: ...")
    w.append("")
    w.append("")

    # Dispatch: decode the envelope, route by ordinal, build the response.
    w.append(f"def dispatch_{snake(iface.name)}(h: {name}Handler, envelope: bytes) -> bytes:")
    w.append(f'    """Route one {iface.name} Call envelope to h and return the response.')
    w.append("")
    w.append("    An unknown ordinal answers NOT_FOUND; a handler that raises answers")
    w.append("    INTERNAL.")
    w.append('    """')
    w.append("    call = _pipeline.parse_request(envelope)")
    w.append("    _id = call.promise_id")
    for i, m in enumerate(iface.methods):
        branch = "if" if i == 0 else "elif"
        w.append(f"    {branch} call.method == {name}Method.{py_name(m.name)}:")
        arg = "call.payload" if m.request else ""
        w.append("        try:")
        if m.response:
            w.append(f"            _body = h.{py_name(m.name)}({arg})")
        else:
            w.append(f"            h.{py_name(m.name)}({arg})")
            w.append('            _body = b""')
        w.append("        except Exception:")
        w.append("            return _pipeline.build_response(_pipeline.STATUS_INTERNAL, _id)")
        w.append("        return _pipeline.build_response(_pipeline.STATUS_OK, _id, _body)")
    w.append("    return _pipeline.build_response(_pipeline.STATUS_NOT_FOUND, _id)")
    w.append("")
    w.append("")

    # Client: one originating form and one pipelined form per method.
    w.append(f"class {name}Client:")
    w.append(f'    """Typed client for {iface.name} over a ZAP call channel.')
    w.append("")
    w.append("    Each call takes a fresh promise from the session; the ``_on`` form of a")
    w.append("    method targets a prior call's promise, so the server substitutes that")
    w.append("    answer for this call's payload and the two ship without a round trip.")
    w.append('    """')
    w.append("")
    w.append('    __slots__ = ("_ch", "_cap", "_sess")')
    w.append("")
    w.append('    def __init__(self, channel: _pipeline.Channel, capability: bytes = b"") -> None:')
    w.append("        self._ch = channel")
    w.append("        self._cap = capability")
    w.append("        self._sess = _pipeline.Session()")
    w.append("")
    w.append("    def _invoke(")
    w.append("        self, method: int, target: int, payload: bytes")
    w.append("    ) -> tuple[_pipeline.Promise, bytes]:")
    w.append("        p = self._sess.next()")
    w.append("        resp = self._ch.call(")
    w.append("            _pipeline.build_request(")
    w.append("                _pipeline.Call(")
    w.append("                    method=method,")
    w.append("                    promise_id=p.id,")
    w.append("                    target=target,")
    w.append("                    cap=self._cap,")
    w.append("                    payload=payload,")
    w.append("                )")
    w.append("            )")
    w.append("        )")
    w.append("        if resp.status != _pipeline.STATUS_OK:")
    w.append("            raise _pipeline.CallFailed(resp.status)")
    w.append("        return p, resp.body")

    for m in iface.methods:
        arg, payload = _args(m)
        mname = py_name(m.name)
        ordinal = f"{name}Method.{mname}"
        if m.response:
            ret, tail = "tuple[_pipeline.Promise, bytes]", ""
        else:
            ret, tail = "_pipeline.Promise", "[0]"
        w.append("")
        w.append(f"    def {mname}(self{arg}) -> {ret}:")
        w.append(f"        return self._invoke({ordinal}, _pipeline.NO_TARGET, {payload}){tail}")
        w.append("")
        w.append(f"    def {mname}_on(self, on: _pipeline.Promise) -> {ret}:")
        w.append(f'        """Issue {m.name} pipelined on the answer of ``on``."""')
        w.append(f'        return self._invoke({ordinal}, on.id, b""){tail}')
    w.append("")
    w.append("")


def emit(f: File) -> tuple[str, str]:
    """Render one schema into ``(module_basename, source)``.

    A schema that declares nothing renders a module that declares nothing —
    the reader is total, so only an unsound layout is an error. Raises
    :class:`~zap.schema.SchemaError` if a struct's layout is unsound or an
    interface names an undeclared payload.
    """
    source = f.source or f"{f.package}.zap"
    base = source.rsplit(".", 1)[0]

    has_list = any(x.type.kind is Kind.LIST for s in f.structs for x in s.fields)
    w: list[str] = [
        "# Code generated by zap.schema; DO NOT EDIT.",
        f"# source: {source}",
        "#",
        "# Names are the schema's own. Everything this module borrows is bound under a",
        "# leading underscore, so a schema is free to name a type Sequence or wire.",
        "# ruff: noqa: E501 — line width follows the schema's identifiers.",
        "",
        "from __future__ import annotations",
        "",
    ]
    if f.interfaces:
        w.append("import enum as _enum")
    if has_list:
        w.append("from collections.abc import Sequence as _Sequence")
    if f.interfaces:
        w.append("from typing import Protocol as _Protocol")
    if f.interfaces or has_list:
        w.append("")
    borrowed = sorted(
        m for m, need in (("wire", bool(f.structs)), ("pipeline", bool(f.interfaces))) if need
    )
    for m in borrowed:
        w.append(f"from zap import {m} as _{m}")
    if borrowed:
        w.append("")
        w.append("")

    for s in f.structs:
        _struct(w, s)
    for iface in f.interfaces:
        _interface(w, f, iface)

    while w and w[-1] == "":
        w.pop()
    return f"{snake(base)}_zap.py", "\n".join(w) + "\n"
