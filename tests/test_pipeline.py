"""Promise pipelining — the faithful Python mirror of Go's ``rpc/pipeline_test.go``.

Each test stands a real :class:`zap.pipeline.Pipeliner` over a real dispatch
function and drives it with a :class:`zap.pipeline.Session`; nothing is mocked.
The model is the canonical one: call A authenticates and returns an opaque org
token; call B (getResource) needs that token as its input. Pipelined, B sets
``target`` = A's ``promise_id`` and ships immediately — the server substitutes
A's resolved token for B's payload before dispatching B, so B never waits for A's
answer to round-trip back to the client.

The wire-encoding test additionally asserts byte-for-byte equality with the
canonical Go ``rpc.BuildRequest`` / ``rpc.BuildResponse`` output, so the interop
claim is proven, not asserted in prose.
"""

from __future__ import annotations

import struct
import threading

from zap.pipeline import (
    NO_TARGET,
    STATUS_BAD_REQUEST,
    STATUS_FORBIDDEN,
    STATUS_NOT_FOUND,
    STATUS_OK,
    STATUS_UNAUTHORIZED,
    Call,
    Pipeliner,
    Session,
    build_request,
    build_response,
    parse_request,
    parse_response,
)

# Method ordinals mirroring Go's pipeline_test.go.
M_AUTHENTICATE = 1  # () -> token
M_GET_RESOURCE = 2  # (token) -> "resource@<token>"


class _AuthServer:
    """A dispatch function: authenticate returns a fixed token; getResource returns
    a resource string keyed by the token it receives as payload. Records, in order,
    the payload every getResource call was dispatched with — the proof that the
    server fed A's result into B (mirrors Go's authServer)."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.got_input: list[bytes] = []
        self._lock = threading.Lock()

    def dispatch(self, envelope: bytes) -> bytes:
        call = parse_request(envelope)
        if call.method == M_AUTHENTICATE:
            return build_response(STATUS_OK, call.promise_id, self.token.encode())
        if call.method == M_GET_RESOURCE:
            with self._lock:
                self.got_input.append(call.payload)
            return build_response(STATUS_OK, call.promise_id, b"resource@" + call.payload)
        return build_response(STATUS_NOT_FOUND, call.promise_id)


def _handle(p: Pipeliner, c: Call):
    """Ship one Call through the Pipeliner and return the parsed Response."""
    return parse_response(p.handle(build_request(c)))


# ── resolves-target ──────────────────────────────────────────────────────────


def test_pipeline_resolves_target():
    """The core end-to-end proof: B pipelines on A's answer via target, the
    Pipeliner substitutes A's resolved token for B's payload before dispatch, and
    B's result reflects it — no round trip threads A's body back through the
    client."""
    srv = _AuthServer("org-7")
    p = Pipeliner(srv.dispatch)
    sess = Session()

    # A: authenticate, fresh promise_id, target = NO_TARGET.
    a = sess.next()
    a_resp = _handle(p, sess.origin(a, M_AUTHENTICATE))
    assert a_resp.body == b"org-7"

    # B: getResource pipelined on A. Its payload is supplied server-side by A's
    # resolved token — the client sends nothing.
    b = sess.next()
    b_resp = _handle(p, sess.pipeline(b, a, M_GET_RESOURCE))
    assert b_resp.body == b"resource@org-7"

    # The server must have dispatched B with A's token as the payload.
    assert srv.got_input == [b"org-7"]


# ── queues-until-resolved ────────────────────────────────────────────────────


def test_pipeline_queues_until_resolved():
    """Server-side queuing: B arrives BEFORE A and must park inside the Pipeliner
    until A resolves, then complete with A's result. We launch B first on its own
    thread, confirm it is still blocked, then handle A — which releases B."""
    srv = _AuthServer("org-42")
    p = Pipeliner(srv.dispatch)
    sess = Session()

    a = sess.next()
    b = sess.next()

    b_done: list = []
    b_event = threading.Event()

    def run_b() -> None:
        resp = _handle(p, sess.pipeline(b, a, M_GET_RESOURCE))
        b_done.append(resp)
        b_event.set()

    threading.Thread(target=run_b, daemon=True).start()

    # Give B a chance to park. It must NOT complete before A is handled.
    assert not b_event.wait(0.05), "B completed before A resolved — it was not queued"

    # Now resolve A; B must unblock with A's token fed in.
    _handle(p, sess.origin(a, M_AUTHENTICATE))
    assert b_event.wait(1.0), "B never resolved after A was handled"
    assert b_done[0].body == b"resource@org-42"


# ── chain-of-three ───────────────────────────────────────────────────────────


def test_pipeline_chain_of_three():
    """A chain deeper than two resolves: C pipelines on B which pipelines on A,
    all queued before A resolves. The server feeds A's answer into B and B's
    answer into C, each in turn. The chain server appends '>' so the depth is
    visible in the final result."""

    def dispatch(envelope: bytes) -> bytes:
        call = parse_request(envelope)
        if call.method == 1:
            return build_response(STATUS_OK, call.promise_id, b"a")
        if call.method == 2:
            return build_response(STATUS_OK, call.promise_id, call.payload + b">")
        return build_response(STATUS_NOT_FOUND, call.promise_id)

    p = Pipeliner(dispatch)
    sess = Session()
    a, b, c = sess.next(), sess.next(), sess.next()

    # Queue C (on B) and B (on A) BEFORE A — both must park, then cascade.
    results: dict[str, object] = {}
    c_event = threading.Event()
    b_event = threading.Event()

    def run_c() -> None:
        results["c"] = _handle(p, sess.pipeline(c, b, 2))
        c_event.set()

    def run_b() -> None:
        results["b"] = _handle(p, sess.pipeline(b, a, 2))
        b_event.set()

    threading.Thread(target=run_c, daemon=True).start()
    threading.Thread(target=run_b, daemon=True).start()
    # Let B and C park before A originates.
    assert not b_event.wait(0.03)

    _handle(p, sess.origin(a, 1))
    assert b_event.wait(1.0) and c_event.wait(1.0)
    assert results["b"].body == b"a>"  # type: ignore[union-attr]
    assert results["c"].body == b"a>>"  # type: ignore[union-attr]  (chained A->B->C)


# ── failure-refusal (immediate) ──────────────────────────────────────────────


def test_pipeline_target_failure_propagates():
    """A dependent whose target answered non-OK is refused (StatusBadRequest), not
    hung: there is no result to pipeline on. Here authenticate fails with
    Unauthorized."""

    def dispatch(envelope: bytes) -> bytes:
        call = parse_request(envelope)
        if call.method == M_AUTHENTICATE:
            return build_response(STATUS_UNAUTHORIZED, call.promise_id)
        return build_response(STATUS_OK, call.promise_id, b"resource@" + call.payload)

    p = Pipeliner(dispatch)
    sess = Session()

    a = sess.next()
    a_resp = _handle(p, sess.origin(a, M_AUTHENTICATE))
    assert a_resp.status == STATUS_UNAUTHORIZED

    b = sess.next()
    b_resp = _handle(p, sess.pipeline(b, a, M_GET_RESOURCE))
    assert b_resp.status == STATUS_BAD_REQUEST  # target never resolves


# ── failure-refusal (queued) ─────────────────────────────────────────────────


def test_pipeline_queued_failure_propagates():
    """The queued twin: B parks before A, then A fails — B must wake with
    StatusBadRequest, not hang."""

    def dispatch(envelope: bytes) -> bytes:
        call = parse_request(envelope)
        if call.method == M_AUTHENTICATE:
            return build_response(STATUS_FORBIDDEN, call.promise_id)
        return build_response(STATUS_OK, call.promise_id)

    p = Pipeliner(dispatch)
    sess = Session()
    a = sess.next()
    b = sess.next()

    b_done: list = []
    b_event = threading.Event()

    def run_b() -> None:
        b_done.append(_handle(p, sess.pipeline(b, a, M_GET_RESOURCE)))
        b_event.set()

    threading.Thread(target=run_b, daemon=True).start()
    assert not b_event.wait(0.02)  # let B park

    _handle(p, sess.origin(a, M_AUTHENTICATE))
    assert b_event.wait(1.0), "queued B never woke after A failed"
    assert b_done[0].status == STATUS_BAD_REQUEST


# ── finish-refusal ───────────────────────────────────────────────────────────


def test_pipeline_finish_drops_answer():
    """finish bounds the table: once a promise is finished, a later dependent
    targeting it is refused (BadRequest), exactly like a never-resolved target,
    instead of finding a stale cached answer."""
    srv = _AuthServer("org-9")
    p = Pipeliner(srv.dispatch)
    sess = Session()

    a = sess.next()
    _handle(p, sess.origin(a, M_AUTHENTICATE))

    # Before finish: the dependent resolves.
    b = sess.next()
    assert _handle(p, sess.pipeline(b, a, M_GET_RESOURCE)).body == b"resource@org-9"

    # After finish: A's answer is gone; a new dependent on A is refused.
    p.finish(a.id)
    c = sess.next()
    assert _handle(p, sess.pipeline(c, a, M_GET_RESOURCE)).status == STATUS_BAD_REQUEST


def test_pipeline_finish_wakes_parked_dependent():
    """Finishing a target with a dependent already parked on it wakes that
    dependent with a refusal instead of hanging it forever (the answer is gone and
    will never be re-produced) — the Finish-hang bug the Go/JS port found."""
    srv = _AuthServer("org-3")
    p = Pipeliner(srv.dispatch)
    sess = Session()
    a = sess.next()
    b = sess.next()

    b_done: list = []
    b_event = threading.Event()

    def run_b() -> None:
        b_done.append(_handle(p, sess.pipeline(b, a, M_GET_RESOURCE)))
        b_event.set()

    threading.Thread(target=run_b, daemon=True).start()
    assert not b_event.wait(0.02)  # let B park on A (A never originates)

    p.finish(a.id)  # A will never produce an answer — refuse B.
    assert b_event.wait(1.0), "parked B never woke after A finished"
    assert b_done[0].status == STATUS_BAD_REQUEST


# ── wire-encoding (+ byte-for-byte Go parity) ────────────────────────────────


def _wire_field(env: bytes, off: int) -> int:
    """Read the request struct's u32 field at struct offset ``off`` directly from
    the encoded message — proving the on-wire bytes (not just the in-memory Call)
    carry the value. Root object byte offset lives in the header at [8:12]."""
    parse_request(env)  # validate framing the way a peer would before trusting offsets
    (root,) = struct.unpack_from("<I", env, 8)
    pos = root + off
    assert pos + 4 <= len(env), f"field offset {pos} out of range (msg len {len(env)})"
    (val,) = struct.unpack_from("<I", env, pos)
    return val


def test_pipeline_wire_encoding():
    """The dependent call's target rides on the wire as the prior call's
    promise_id (byte-level), a non-pipelined call carries NO_TARGET, and the bytes
    round-trip through the decoder unchanged."""
    sess = Session()
    a = sess.next()
    b = sess.next()
    assert a.id != NO_TARGET and b.id != NO_TARGET and a.id != b.id

    # Struct field offsets: promise_id @4, target @8 (verbatim from Go envelope).
    req_promise_id_off, req_target_off = 4, 8

    # Originating call A: target field (@8) must be NO_TARGET on the wire.
    a_env = build_request(sess.origin(a, M_AUTHENTICATE))
    assert _wire_field(a_env, req_target_off) == NO_TARGET
    assert _wire_field(a_env, req_promise_id_off) == a.id

    # Dependent call B: target field (@8) must equal A's promise_id on the wire.
    b_env = build_request(sess.pipeline(b, a, M_GET_RESOURCE))
    assert _wire_field(b_env, req_target_off) == a.id
    assert _wire_field(b_env, req_promise_id_off) == b.id

    # And it round-trips through the decoder unchanged.
    call = parse_request(b_env)
    assert call.target == a.id and call.promise_id == b.id and call.method == M_GET_RESOURCE


def test_session_sequence_starts_at_one():
    """The promise_id sequence matches Go/JS exactly: the first id is 1, unique
    and monotonic, never NO_TARGET."""
    sess = Session()
    ids = [sess.next().id for _ in range(5)]
    assert ids == [1, 2, 3, 4, 5]
    assert NO_TARGET not in ids


def test_wire_bytes_byte_for_byte_identical_to_go():
    """PROOF of cross-language wire compatibility: the envelope bytes are
    byte-for-byte identical to the canonical Go ``rpc.BuildRequest`` /
    ``rpc.BuildResponse`` output. These golden hexes are produced by running
    ``rpc.BuildRequest``/``BuildResponse`` in the Go module (zap-proto/go) over
    the same fields; a Python envelope that does not reproduce them exactly would
    not interoperate with Go on the wire."""
    # Go rpc.BuildRequest(Call{Method:1, PromiseID:1, Target:0})
    go_origin = bytes.fromhex(
        "5a415000020000c8100000002c00000001000000010000000000000000000000000000000000000000000000"
    )
    # Go rpc.BuildRequest(Call{Method:2, PromiseID:2, Target:1, Payload:"org-7"})
    go_dep = bytes.fromhex(
        "5a415000020000c81000000031000000020000000200000001000000"
        "00000000000000000800000005000000"
        "6f72672d37"
    )
    # Go rpc.BuildResponse(StatusOK, 2, "resource@org-7")
    go_resp = bytes.fromhex(
        "5a415000020000c81000000032000000c800000002000000"
        "00000000080000000e0000007265736f75726365406f72672d37"
    )
    # Go rpc.BuildRequest(Call{Method:7, PromiseID:5, Target:3, Cap:"CAP", Payload:"P"})
    go_cappay = bytes.fromhex(
        "5a415000020000c8100000003000000007000000050000000300000010000000"
        "030000000b0000000100000043415050"
    )

    assert build_request(Call(method=1, promise_id=1, target=0)) == go_origin
    assert build_request(Call(method=2, promise_id=2, target=1, payload=b"org-7")) == go_dep
    assert build_response(STATUS_OK, 2, b"resource@org-7") == go_resp
    assert (
        build_request(Call(method=7, promise_id=5, target=3, cap=b"CAP", payload=b"P")) == go_cappay
    )
