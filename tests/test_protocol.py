"""ZAP magic-framed JSON protocol — encode/decode + stream demux."""

from zap.protocol import MSG_REQUEST, decode, decode_stream, encode


def test_encode_decode_roundtrip():
    frame = encode(MSG_REQUEST, {"method": "ping", "id": 1})
    msg_type, payload = decode(frame)
    assert msg_type == MSG_REQUEST
    assert payload == {"method": "ping", "id": 1}


def test_decode_rejects_bad_magic():
    assert decode(b"XXXX\x10\x00\x00\x00\x00") is None


def test_decode_rejects_short():
    assert decode(b"\x5a\x41") is None


def test_decode_stream_reports_consumed():
    f1 = encode(MSG_REQUEST, {"n": 1})
    f2 = encode(MSG_REQUEST, {"n": 2})
    buf = f1 + f2
    r1 = decode_stream(buf)
    assert r1 is not None
    t1, p1, consumed = r1
    assert (t1, p1) == (MSG_REQUEST, {"n": 1})
    assert consumed == len(f1)
    # Second frame is recoverable — the old decode() dropped it.
    r2 = decode_stream(buf[consumed:])
    assert r2 is not None
    _t2, p2, _c2 = r2
    assert p2 == {"n": 2}


def test_decode_stream_needs_more_bytes():
    """A partial frame returns None so a stream consumer waits for more data."""
    full = encode(MSG_REQUEST, {"hello": "world"})
    assert decode_stream(full[:-3]) is None
