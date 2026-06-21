"""Promise pipelining over the ZAP call envelope (the ONE canonical ZAP model).

This is the faithful Python peer of Go's ``github.com/zap-proto/go/rpc``
(``Session`` + ``Pipeliner``) and the TypeScript ``@zap-proto/zap`` ``promise.ts``
— the same model, the same wire bytes.

A call carries a caller-assigned ``promise_id`` (the id its answer resolves to).
A *dependent* call sets ``target`` = a prior call's ``promise_id``, meaning
"before you dispatch me, substitute the resolved Body of the call that answered
to that promise_id as my Payload." The result of A is the input to B, so B ships
back-to-back with A and the server chains them — no round trip threads A's answer
back through the client first.

Two pieces implement it, each in one place (orthogonal, no braiding):

* :class:`Session` (client side) allocates ``promise_id`` s and stamps ``target``
  onto a dependent :class:`Call`, so a caller can reference a prior in-flight
  answer. The first id is ``1`` (matching Go/JS exactly).
* :class:`Pipeliner` (server side) is the promise table: it resolves ``target``
  before dispatch (substituting the resolved Body for the dependent Payload),
  records every OK answer under its ``promise_id``, queues a dependent whose
  target has not resolved yet until it does, and refuses (StatusBadRequest) one
  whose target answered non-OK or was finished — never hangs.

Both are transport-agnostic: they operate on :class:`Call` / :class:`Response`
and a raw ``DispatchFn`` (``envelope -> response envelope``), so the exact same
model works in-process and over a real socket without change.

The wire envelope is **byte-for-byte identical to Go and TypeScript**: it is
the binary ZAP call envelope encoded with :mod:`zap.wire` (the same zero-copy
codec), NOT the JSON ``{"id","method","params"}`` envelope of :mod:`zap.rpc`.
``target`` rides at struct offset @8; ``NO_TARGET`` (0) is a non-pipelined call,
so a :class:`Pipeliner` and a plain dispatcher are byte-compatible on the wire
and a non-pipelining peer (any other runtime) interoperates by sending
``target = NO_TARGET``. A request built here parses through Go's ``ParseRequest``
and vice versa (verified byte-for-byte in the tests).

Pure stdlib — :mod:`zap.wire` + :mod:`threading`. No third-party dependency.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from zap.wire import VERSION2, Builder, parse

# ── Envelope constants (verbatim from Go rpc/envelope.go) ────────────────────

#: This service's ZAP message-type slot, carried in the high byte of the header
#: flags word (``MsgTypeRouterBase << 8``). Matches Go ``rpc.MsgTypeRouterBase``.
MSG_TYPE_ROUTER_BASE = 200

#: The ``target`` value for a call that does not pipeline off an earlier promise
#: (the call targets the bootstrap object). Matches Go ``rpc.NoTarget``.
NO_TARGET = 0

# Status codes carried in a Response (verbatim from Go rpc/envelope.go).
STATUS_OK = 200
STATUS_BAD_REQUEST = 400
STATUS_UNAUTHORIZED = 401
STATUS_FORBIDDEN = 403
STATUS_NOT_FOUND = 404
STATUS_INTERNAL = 500

# Request field offsets (fixed object size 28) — verbatim from Go.
_REQ_METHOD_OFF = 0
_REQ_PROMISE_ID_OFF = 4
_REQ_TARGET_OFF = 8
_REQ_CAP_OFF = 12
_REQ_PAYLOAD_OFF = 20
_REQ_FIXED_SIZE = 28

# Response field offsets (fixed object size 20) — verbatim from Go.
_RESP_STATUS_OFF = 0
_RESP_PROMISE_ID_OFF = 4
_RESP_BODY_OFF = 12
_RESP_FIXED_SIZE = 20

_EMPTY = b""


def _builder_v2(capacity: int) -> Builder:
    """A :class:`zap.wire.Builder` that emits a Version2 header.

    Go's rpc envelope uses ``NewBuilderV2`` (the header the ZAP transport framing
    uses by default); the data segment is byte-identical to Version1, only header
    byte 4 differs. We build with the stdlib codec and stamp the version so the
    bytes match Go/TS exactly.
    """
    b = Builder(capacity)
    # Builder writes the magic + VERSION (v1) at construction; override byte 4
    # to VERSION2 to match Go's NewBuilderV2. (Builder has no public version
    # arg; this single byte is the only difference, by design — see builder.go.)
    b._buf[4] = VERSION2  # noqa: SLF001  (intentional: mirror Go NewBuilderV2)
    return b


# ── Call / Response (the wire envelope) ─────────────────────────────────────


@dataclass(frozen=True)
class Call:
    """One outbound request's fields (the Python peer of Go's ``rpc.Call``)."""

    method: int
    promise_id: int
    target: int = NO_TARGET
    cap: bytes = _EMPTY
    payload: bytes = _EMPTY


@dataclass(frozen=True)
class Response:
    """A decoded response envelope (the Python peer of Go's ``rpc.Response``)."""

    status: int
    promise_id: int
    body: bytes = _EMPTY


def build_request(c: Call) -> bytes:
    """Encode a :class:`Call` into a router-tagged ZAP message.

    Byte-for-byte identical to Go ``rpc.BuildRequest`` / TS ``buildRequest``.
    """
    b = _builder_v2(len(c.cap) + len(c.payload) + _REQ_FIXED_SIZE + 64)
    ob = b.start_object(_REQ_FIXED_SIZE)
    ob.set_uint32(_REQ_METHOD_OFF, c.method)
    ob.set_uint32(_REQ_PROMISE_ID_OFF, c.promise_id)
    ob.set_uint32(_REQ_TARGET_OFF, c.target)
    ob.set_bytes(_REQ_CAP_OFF, c.cap)
    ob.set_bytes(_REQ_PAYLOAD_OFF, c.payload)
    ob.finish_as_root()
    return b.finish_with_flags(MSG_TYPE_ROUTER_BASE << 8)


def parse_request(msg: bytes) -> Call:
    """Decode a router-tagged request message into a :class:`Call`.

    Byte-for-byte the inverse of Go ``rpc.ParseRequest`` / TS ``parseRequest``.
    """
    r = parse(msg).root()
    return Call(
        method=r.uint32(_REQ_METHOD_OFF),
        promise_id=r.uint32(_REQ_PROMISE_ID_OFF),
        target=r.uint32(_REQ_TARGET_OFF),
        cap=bytes(r.bytes(_REQ_CAP_OFF)),
        payload=bytes(r.bytes(_REQ_PAYLOAD_OFF)),
    )


def build_response(status: int, promise_id: int, body: bytes = _EMPTY) -> bytes:
    """Encode a status + body into a router-tagged response.

    Byte-for-byte identical to Go ``rpc.BuildResponse`` / TS ``buildResponse``.
    """
    b = _builder_v2(len(body) + _RESP_FIXED_SIZE + 64)
    ob = b.start_object(_RESP_FIXED_SIZE)
    ob.set_uint32(_RESP_STATUS_OFF, status)
    ob.set_uint32(_RESP_PROMISE_ID_OFF, promise_id)
    ob.set_bytes(_RESP_BODY_OFF, body)
    ob.finish_as_root()
    return b.finish_with_flags(MSG_TYPE_ROUTER_BASE << 8)


def parse_response(msg: bytes) -> Response:
    """Decode a router-tagged response message into a :class:`Response`."""
    r = parse(msg).root()
    return Response(
        status=r.uint32(_RESP_STATUS_OFF),
        promise_id=r.uint32(_RESP_PROMISE_ID_OFF),
        body=bytes(r.bytes(_RESP_BODY_OFF)),
    )


# ── Client-side origination ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Promise:
    """A handle to the answer of an in-flight call.

    Use its :attr:`id` as the ``target`` of a dependent :class:`Call` to pipeline
    on it. The id is the ``promise_id`` the originating call's answer resolves to
    (never :data:`NO_TARGET`). The Python peer of Go's ``rpc.Promise`` /
    TS ``PromiseHandle``.
    """

    id: int


class Session:
    """The client half of pipelining: a monotonic ``promise_id`` allocator.

    Scoped to one transport connection (the peer of Go's ``rpc.Session`` /
    TS ``Session``). The first call of a pipeline takes a fresh ``promise_id``
    via :meth:`next`; a dependent call sets ``target`` to that id via
    :meth:`pipeline`.

    ``promise_id`` s are unique and non-zero within a session (0 is
    :data:`NO_TARGET`); the sequence matches Go/JS — the first id is ``1``.
    """

    def __init__(self) -> None:
        self._next = 0
        self._lock = threading.Lock()

    def next(self) -> Promise:
        """Allocate a fresh, unique, non-zero ``promise_id`` and return its handle."""
        with self._lock:
            self._next = (self._next + 1) & 0xFFFFFFFF
            if self._next == NO_TARGET:  # wrapped past 2**32-1 back to 0 — skip it
                self._next = (self._next + 1) & 0xFFFFFFFF
            return Promise(id=self._next)

    def origin(
        self,
        p: Promise,
        method: int,
        cap: bytes = _EMPTY,
        payload: bytes = _EMPTY,
    ) -> Call:
        """Build the originating :class:`Call` of a pipeline.

        It carries a fresh ``promise_id`` (from ``p``) and ``target`` =
        :data:`NO_TARGET`. ``cap`` / ``payload`` are this call's own arguments.
        """
        return Call(method=method, promise_id=p.id, target=NO_TARGET, cap=cap, payload=payload)

    def pipeline(
        self,
        p: Promise,
        target: Promise,
        method: int,
        cap: bytes = _EMPTY,
        payload: bytes = _EMPTY,
    ) -> Call:
        """Build a dependent :class:`Call` that pipelines on ``target``'s answer.

        It carries its own fresh ``promise_id`` (from ``p``) and ``target`` =
        ``target.id``. The server substitutes ``target``'s resolved Body for this
        call's Payload before dispatch, so ``payload`` here is only the part of
        the request NOT supplied by the upstream answer (often empty — the whole
        input is the upstream result).
        """
        return Call(method=method, promise_id=p.id, target=target.id, cap=cap, payload=payload)


# ── Server-side promise table ─────────────────────────────────────────────────

#: A server entry point: decode a Call envelope, dispatch, return a Response
#: envelope. A :class:`Pipeliner` wraps one of these. The peer of Go's
#: ``DispatchFunc`` / TS ``DispatchFn``.
DispatchFn = Callable[[bytes], bytes]


@dataclass
class _Pending:
    """A dependent call parked until its ``target`` resolves.

    ``done`` is set once ``result`` is populated (the dependent's own response
    envelope) or ``err`` is set (a dispatch failure).
    """

    call: Call
    done: threading.Event = field(default_factory=threading.Event)
    result: bytes | None = None
    err: BaseException | None = None


class Pipeliner:
    """A server-side promise table for one session (one transport connection).

    The Python peer of Go's ``rpc.Pipeliner`` / TS ``Pipeliner``. Feed each
    inbound request envelope to :meth:`handle`; it resolves ``target``
    references, records OK answers, and queues a dependent whose target has not
    resolved yet until a later :meth:`handle` resolves it.

    Safe for concurrent :meth:`handle` calls — a transport that reads frames on
    multiple threads may call it from each (mirrors Go's mutex-guarded table).
    """

    def __init__(self, dispatch: DispatchFn) -> None:
        self._dispatch = dispatch
        self._lock = threading.Lock()
        self._resolved: dict[int, bytes] = {}  # promise_id -> resolved OK Body
        self._failed: set[int] = set()  # promise_id -> answered non-OK (no result)
        self._finished: set[int] = set()  # promise_id -> Finished (answer dropped)
        self._waiters: dict[int, list[_Pending]] = {}  # target -> calls queued on it

    def handle(self, envelope: bytes) -> bytes:
        """Process one inbound request envelope and return its response envelope.

        A request with ``target`` = :data:`NO_TARGET` dispatches straight
        through. Otherwise the ``target`` decides:

        * resolved (OK): the resolved Body is substituted for the request's
          Payload and it dispatches immediately.
        * failed (non-OK) or finished: refused with :data:`STATUS_BAD_REQUEST` —
          the target can never produce a result to pipeline on.
        * unknown: parked until a later :meth:`handle` on the same Pipeliner
          resolves it (the dependent legitimately arrived before its origin), or
          a :meth:`finish` on the target refuses it.
        """
        return self._handle_call(parse_request(envelope))

    def _handle_call(self, call: Call) -> bytes:
        if call.target == NO_TARGET:
            return self._dispatch_and_record(call)

        # Dependent call: resolve, refuse, or park under its target.
        with self._lock:
            body = self._resolved.get(call.target)
            if body is not None:
                resolved_call = Call(
                    method=call.method,
                    promise_id=call.promise_id,
                    target=call.target,
                    cap=call.cap,
                    payload=body,
                )
            elif call.target in self._failed or call.target in self._finished:
                # A target that answered non-OK, or was already finished, can
                # never resolve — refuse rather than park forever.
                return build_response(STATUS_BAD_REQUEST, call.promise_id)
            else:
                # Unknown target: assume its originating call is still in flight
                # (the dependent legitimately arrived first) and park until a
                # future handle resolves it. finish() on the target wakes a
                # parked dependent with a refusal so it never hangs.
                pc = _Pending(call=call)
                self._waiters.setdefault(call.target, []).append(pc)
                resolved_call = None

        if resolved_call is not None:
            return self._dispatch_and_record(resolved_call)

        pc.done.wait()
        if pc.err is not None:
            raise pc.err
        assert pc.result is not None
        return pc.result

    def finish(self, id: int) -> None:
        """Drop the cached answer for ``id`` once no further call will pipeline on it.

        The ZAP analogue of capnp's Finish message. Optional: without it, a
        Pipeliner retains each OK answer for the session's lifetime so a
        dependent that arrives after its target resolves still finds it. A
        long-lived connection that pipelines heavily should finish each promise
        it is done with to bound the table.

        After ``finish``, ``id`` is terminal: any dependent that targets it —
        whether already parked or arriving later — is refused
        (:data:`STATUS_BAD_REQUEST`) rather than hung, since the answer is gone
        and will never be re-produced.
        """
        with self._lock:
            self._resolved.pop(id, None)
            self._failed.discard(id)
            self._finished.add(id)
            woken = self._waiters.pop(id, [])
        for pc in woken:
            pc.result = build_response(STATUS_BAD_REQUEST, pc.call.promise_id)
            pc.done.set()

    def _dispatch_and_record(self, call: Call) -> bytes:
        """Run one resolved call, record its OK answer, release parked dependents."""
        try:
            resp_bytes = self._dispatch(build_request(call))
        except BaseException as err:  # noqa: BLE001 — a dispatch failure poisons this id
            # A transport-level dispatch failure poisons this promise_id: any
            # dependent parked on it can never resolve.
            self._poison(call.promise_id, err)
            raise
        resp = parse_response(resp_bytes)
        self._record(call.promise_id, resp)
        return resp_bytes

    def _record(self, id: int, resp: Response) -> None:
        """Cache an OK answer (waking dependents with it) or mark id failed (refuse them).

        An OK answer caches its Body (the value future dependents pipeline on)
        and re-dispatches every parked dependent with that Body as its Payload;
        a non-OK answer marks ``id`` failed so its dependents are refused, not
        hung.
        """
        with self._lock:
            if resp.status == STATUS_OK:
                self._resolved[id] = resp.body
                woken = self._waiters.pop(id, [])
                ok = True
            else:
                self._failed.add(id)
                woken = self._waiters.pop(id, [])
                ok = False

        if not ok:
            for pc in woken:
                pc.result = build_response(STATUS_BAD_REQUEST, pc.call.promise_id)
                pc.done.set()
            return

        body = resp.body
        for pc in woken:
            resolved_call = Call(
                method=pc.call.method,
                promise_id=pc.call.promise_id,
                target=pc.call.target,
                cap=pc.call.cap,
                payload=body,
            )
            try:
                pc.result = self._dispatch_and_record(resolved_call)
            except BaseException as err:  # noqa: BLE001 — propagate to the parked caller
                pc.err = err
            pc.done.set()

    def _poison(self, id: int, err: BaseException) -> None:
        """Wake every dependent parked on ``id`` with ``err`` (dispatch itself failed)."""
        with self._lock:
            self._failed.add(id)
            woken = self._waiters.pop(id, [])
        for pc in woken:
            pc.err = err
            pc.done.set()
