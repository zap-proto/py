# SPDX-License-Identifier: BSD-3-Clause-Eco
"""``zap.schema`` — the whitespace-significant reader and the code it emits.

The desugar cases below are the VERBATIM golden corpus of ``zap-proto/go``'s
``cmd/zapgen/desugar_test.go``: same inputs, same byte-for-byte outputs. Two
runtimes that agree on these agree on how a schema is READ, which is what
keeps them from drifting on what it MEANS.

The generated-binding vectors are hexes produced by the GO generator's own
output (``NewPing`` / ``NewBaseTx`` compiled against ``zap-proto/go``); the
Python bindings generated from the same schema must write the same bytes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from zap.schema import Kind, SchemaError, desugar, emit, parse

SCHEMA = Path(__file__).parent / "testdata" / "schema"


# ── desugar: whitespace-significant source → canonical brace form ─────────

DESUGAR: list[tuple[str, str, str]] = [
    (
        "brace input is identity",
        "package p\nstruct S {\n    A u8 @0\n}\n",
        "package p\nstruct S {\n    A u8 @0\n}\n",
    ),
    (
        "header gets brace, fields get auto offsets",
        "package p\nstruct S\n    A u8\n    B u32\n",
        "package p\nstruct S {\n    A u8 @0\n    B u32 @1\n}\n",
    ),
    (
        "explicit offset preserved and resets cursor",
        "package p\nstruct S\n    A u8 @4\n    B u32\n",
        "package p\nstruct S {\n    A u8 @4\n    B u32 @5\n}\n",
    ),
    (
        "alias type sized for auto offset",
        "package p\ntype id32 = bytes_fixed[32]\nstruct S\n    A id32\n    B u32\n",
        "package p\ntype id32 = bytes_fixed[32]\nstruct S {\n    A id32 @0\n    B u32 @32\n}\n",
    ),
    (
        "list and bytes are 8-byte pointers",
        "package p\nstruct S\n    L list<Foo>\n    M bytes\n    N u8\n",
        "package p\nstruct S {\n    L list<Foo> @0\n    M bytes @8\n    N u8 @16\n}\n",
    ),
    (
        "nested struct pointer is 4 bytes",
        "package p\nstruct S\n    F Foo\n    G u32\n",
        "package p\nstruct S {\n    F Foo @0\n    G u32 @4\n}\n",
    ),
    (
        "blank lines and comments are transparent",
        "package p\n\nstruct S\n    # leading comment\n    A u8\n\n    B u8\n",
        "package p\n\nstruct S {\n    # leading comment\n    A u8 @0\n\n    B u8 @1\n}\n",
    ),
    (
        "two structs each reset the cursor",
        "package p\nstruct A\n    X u32\nstruct B\n    Y u32\n",
        "package p\nstruct A {\n    X u32 @0\n}\nstruct B {\n    Y u32 @0\n}\n",
    ),
    (
        "inline field comment stripped before offset, kept off output",
        "package p\nstruct S\n    A u8  # the a field\n",
        "package p\nstruct S {\n    A u8 @0\n}\n",
    ),
    (
        "brace and whitespace structs coexist in one file",
        "package p\nstruct A {\n    X u8 @0\n}\nstruct B\n    Y u8\n",
        "package p\nstruct A {\n    X u8 @0\n}\nstruct B {\n    Y u8 @0\n}\n",
    ),
    (
        "no trailing newline is preserved",
        "package p\nstruct S\n    A u8",
        "package p\nstruct S {\n    A u8 @0\n}",
    ),
    # A field whose NAME is a keyword is an ordinary field, never a phantom
    # block header and never an alias: a braceless header is EXACTLY the
    # keyword + one identifier + end-of-line.
    (
        "field named struct with explicit offset",
        "package p\nstruct S\n    struct u8 @0\n",
        "package p\nstruct S {\n    struct u8 @0\n}\n",
    ),
    (
        "field named interface with explicit offset",
        "package p\nstruct S\n    interface text @8\n",
        "package p\nstruct S {\n    interface text @8\n}\n",
    ),
    (
        "field named interface auto offset",
        "package p\nstruct S\n    interface text\n    B u8\n",
        "package p\nstruct S {\n    interface text @0\n    B u8 @8\n}\n",
    ),
    (
        "field named type with explicit offset",
        "package p\nstruct S\n    type u8 @0\n",
        "package p\nstruct S {\n    type u8 @0\n}\n",
    ),
    (
        "field named type auto offset advances cursor",
        "package p\nstruct S\n    type u32\n    B u8\n",
        "package p\nstruct S {\n    type u32 @0\n    B u8 @4\n}\n",
    ),
    (
        "field named type inside brace struct",
        "package p\nstruct S {\n    type u8 @0\n}\n",
        "package p\nstruct S {\n    type u8 @0\n}\n",
    ),
    (
        "top-level alias coexists with type-named field",
        "package p\ntype id32 = bytes_fixed[32]\nstruct S\n    type id32\n    B u8\n",
        "package p\ntype id32 = bytes_fixed[32]\nstruct S {\n    type id32 @0\n    B u8 @32\n}\n",
    ),
    (
        "struct plus bare identifier is still a header",
        "package p\nstruct S\n    A u8\n",
        "package p\nstruct S {\n    A u8 @0\n}\n",
    ),
    # An unrecognized header keeps its body: the desugarer passes it through
    # and the PARSER owns the precise diagnostic.
    (
        "glued identifier then body passes through",
        "package p\nstructFoo\n    A u8\n",
        "package p\nstructFoo\n    A u8\n",
    ),
    (
        "bare struct keyword then body passes through",
        "package p\nstruct\n    A u8\n",
        "package p\nstruct\n    A u8\n",
    ),
]


@pytest.mark.parametrize(("name", "src", "want"), DESUGAR, ids=[c[0] for c in DESUGAR])
def test_desugar(name: str, src: str, want: str) -> None:
    assert desugar(src) == want


def test_desugar_then_parse() -> None:
    src = "package p\ntype id32 = bytes_fixed[32]\nstruct S\n    A u32\n    B id32\n    C bytes\n"
    f = parse("s.zap", src)
    assert len(f.structs) == 1
    assert [(x.name, x.offset) for x in f.structs[0].fields] == [("A", 0), ("B", 4), ("C", 36)]


def test_keyword_named_fields_parse() -> None:
    """A keyword-named field survives the whole read, name and offset intact."""
    src = "package p\nstruct S\n    type u32\n    struct u8 @4\n    interface text\n"
    f = parse("s.zap", src)
    assert [(x.name, x.offset) for x in f.structs[0].fields] == [
        ("type", 0),
        ("struct", 4),
        ("interface", 5),
    ]


@pytest.mark.parametrize(
    "src",
    [
        "package p\nstruct S\n    A u8 @x\n",
        "package p\nstruct S\n    A bytes_fixed[\n",
    ],
)
def test_desugar_rejects_malformed(src: str) -> None:
    with pytest.raises(SchemaError):
        desugar(src)


@pytest.mark.parametrize(
    "src",
    [
        # 20 nines: overflows uint64 in an unguarded accumulator.
        "package p\nstruct S\n    A u8 @99999999999999999999\n",
        # Exactly 2^64: wraps to 0, aliasing onto field offset 0.
        "package p\nstruct S\n    A u8 @18446744073709551616\n",
        # Above the bound but inside uint64.
        "package p\nstruct S\n    A u8 @9999999999\n",
    ],
)
def test_desugar_rejects_out_of_range_offset(src: str) -> None:
    with pytest.raises(SchemaError, match="out of range"):
        desugar(src)


def test_desugar_accepts_offset_at_the_bound() -> None:
    assert desugar("package p\nstruct S\n    A u8 @2147483647\n")


@pytest.mark.parametrize(
    "src",
    [
        "package p\nstructFoo\n    A u8\n",
        "package p\nstruct\n    A u8\n",
    ],
)
def test_parser_owns_the_diagnostic(src: str) -> None:
    """Desugar passes an unrecognized header through; the parser rejects it."""
    assert desugar(src) == src
    with pytest.raises(SchemaError, match="expected"):
        parse("t.zap", src)


# ── parse: the two styles are one grammar ────────────────────────────────


def test_both_styles_read_the_same_schema() -> None:
    """The braceless twin of basetx.zap parses to the identical layout."""
    brace = parse("basetx.zap", (SCHEMA / "basetx.zap").read_text())
    ws = parse("basetx.zap", (SCHEMA / "basetx_ws.zap").read_text())
    assert brace.package == ws.package == "xvm"
    assert [(f.name, f.offset, f.type) for f in brace.structs[0].fields] == [
        (f.name, f.offset, f.type) for f in ws.structs[0].fields
    ]
    assert [(f.name, f.offset) for f in ws.structs[0].fields] == [
        ("NetworkID", 0),
        ("BlockchainID", 4),
        ("Outs", 36),
        ("Ins", 44),
        ("Memo", 52),
    ]
    assert ws.structs[0].size == 60


def test_interface_ordinals_follow_declaration_order() -> None:
    f = parse("echo.zap", (SCHEMA / "echo.zap").read_text())
    iface = f.interfaces[0]
    assert iface.name == "Echo"
    assert [(m.name, m.ordinal) for m in iface.methods] == [
        ("ping", 1),
        ("notify", 2),
        ("health", 3),
        ("shutdown", 4),
    ]
    assert iface.methods[0].request is not None
    assert iface.methods[0].request.struct_name == "Ping"
    assert iface.methods[3].request is None and iface.methods[3].response is None


def test_alias_sizes_a_field() -> None:
    f = parse("basetx.zap", (SCHEMA / "basetx.zap").read_text())
    assert f.aliases["id32"].kind is Kind.BYTES_FIXED
    assert f.aliases["id32"].fixed_size == 32


@pytest.mark.parametrize(
    ("src", "match"),
    [
        ("struct S {\n A u8 @0\n}\n", "expected `package`"),
        ("package p\nenum E {\n}\n", "top level"),
        ("package p\nstruct S {\n A u8 @0\n B u8 @0\n}\n", "overlaps"),
        ("package p\nstruct S {\n}\n", "no fields"),
        ("package p\ninterface I {\n}\n", "no methods"),
        ("package p\ninterface I {\n m(r: Missing)\n}\n", "unknown struct"),
        ("package p\ntype a = u8\ntype a = u8\nstruct S {\n A u8 @0\n}\n", "duplicate"),
    ],
)
def test_unsound_schemas_are_rejected(src: str, match: str) -> None:
    with pytest.raises(SchemaError, match=match):
        emit(parse("t.zap", src))


# ── emit: the generated bindings read what Go's generated bindings write ──


def _load(schema: str, module: str) -> ModuleType:
    """Generate bindings for a fixture and import them as a live module."""
    src = (SCHEMA / schema).read_text()
    name, body = emit(parse(schema, src))
    assert name.endswith("_zap.py")
    spec = importlib.util.spec_from_loader(module, loader=None)
    assert spec is not None
    m = importlib.util.module_from_spec(spec)
    m.__file__ = name
    sys.modules[module] = m
    exec(compile(body, name, "exec"), m.__dict__)  # noqa: S102 — the point of the test
    return m


#: Built by the GO generator's output (``echo.NewPing`` / ``xvm.NewBaseTx``
#: compiled against ``zap-proto/go``). The Python bindings must match byte
#: for byte — same schema, same layout, same wire.
GO_PING = "5a4150000100000010000000180000000700000000000000"
GO_BASETX = (
    "5a41500001000000100000006500000071780100000102030405060708090a0b0c0d0e0f"
    "101112131415161718191a1b1c1d1e1f1c0000000200000000000000000000001c000000"
    "05000000000000000300000001020302000000040500000068656c6c6f"
)


def test_generated_bindings_match_go_bytes() -> None:
    echo = _load("echo.zap", "zap_test_echo")
    assert echo.Ping.build(Seq=7).hex() == GO_PING

    xvm = _load("basetx.zap", "zap_test_xvm")
    buf = xvm.BaseTx.build(
        NetworkID=96369,
        BlockchainID=bytes(range(32)),
        Outs=[bytes([1, 2, 3]), bytes([4, 5])],
        Ins=(),
        Memo=b"hello",
    )
    assert buf.hex() == GO_BASETX


def test_generated_view_reads_what_it_wrote() -> None:
    xvm = _load("basetx.zap", "zap_test_xvm_read")
    buf = xvm.BaseTx.build(
        NetworkID=96369,
        BlockchainID=bytes(range(32)),
        Outs=[b"\x01\x02\x03", b"\x04\x05"],
        Memo=b"hello",
    )
    v = xvm.BaseTx.wrap(buf)
    assert v.NetworkID == 96369
    assert v.BlockchainID == bytes(range(32))
    assert v.Memo == b"hello"
    assert len(v.Outs) == 2
    assert bytes(v.Outs.bytes_at(0)) == b"\x01\x02\x03"


def test_whitespace_form_generates_the_same_module() -> None:
    """Braceless source emits byte-identical bindings to its brace twin."""
    brace = emit(parse("basetx.zap", (SCHEMA / "basetx.zap").read_text()))
    ws = emit(parse("basetx.zap", (SCHEMA / "basetx_ws.zap").read_text()))
    assert brace == ws


def test_generated_service_dispatches_by_ordinal() -> None:
    from zap import pipeline

    echo = _load("echo.zap", "zap_test_echo_rpc")

    class Handler:
        def ping(self, req: bytes) -> bytes:
            return echo.Pong.build(Seq=echo.Ping.wrap(req).Seq + 1)

        def notify(self, req: bytes) -> None:
            return None

        def health(self) -> bytes:
            return echo.Pong.build(Seq=0)

        def shutdown(self) -> None:
            raise RuntimeError("down")

    h = Handler()
    call = pipeline.Call(method=echo.EchoMethod.ping, promise_id=1, payload=echo.Ping.build(Seq=41))
    resp = pipeline.parse_response(echo.dispatch_echo(h, pipeline.build_request(call)))
    assert resp.status == pipeline.STATUS_OK
    assert echo.Pong.wrap(resp.body).Seq == 42

    # A handler that raises answers INTERNAL; an unknown ordinal, NOT_FOUND.
    down = pipeline.Call(method=echo.EchoMethod.shutdown, promise_id=2)
    assert (
        pipeline.parse_response(echo.dispatch_echo(h, pipeline.build_request(down))).status
        == pipeline.STATUS_INTERNAL
    )
    unknown = pipeline.Call(method=9999, promise_id=3)
    assert (
        pipeline.parse_response(echo.dispatch_echo(h, pipeline.build_request(unknown))).status
        == pipeline.STATUS_NOT_FOUND
    )


def test_client_ships_ordinals_and_pipelines() -> None:
    from zap import pipeline

    echo = _load("echo.zap", "zap_test_echo_client")
    seen: list[pipeline.Call] = []

    class Loop:
        def call(self, envelope: bytes) -> pipeline.Response:
            c = pipeline.parse_request(envelope)
            seen.append(c)
            return pipeline.parse_response(
                pipeline.build_response(pipeline.STATUS_OK, c.promise_id, b"ok")
            )

    c = echo.EchoClient(Loop(), b"cap")
    p, body = c.ping(echo.Ping.build(Seq=1))
    assert body == b"ok"
    assert seen[0].method == 1 and seen[0].target == pipeline.NO_TARGET and seen[0].cap == b"cap"

    c.health_on(p)
    assert seen[1].method == 3 and seen[1].target == p.id and seen[1].payload == b""


def test_keyword_field_takes_the_pep8_underscore() -> None:
    """A schema field named ``from`` is reachable as ``from_``."""
    _, body = emit(parse("t.zap", "package p\nstruct S\n    from u32\n    to u32\n"))
    assert "def from_(self) -> int:" in body
    assert "_fromOff = 0" in body
    compile(body, "t_zap.py", "exec")
