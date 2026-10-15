#!/usr/bin/env python3
"""A Kafka broker stand-in for the e2e test of the Kafka log sink.

Answers ApiVersions (v0), Metadata (v1) and Produce (v3), checks each record
batch's CRC-32C, and appends every produced batch to OUTFILE as one JSON line:
{"topic", "partition", "offset", "records": [{"key", "value", "ts", "off"}]}.

Usage: kafka_stub.py PORT OUTFILE
"""
import json
import socket
import struct
import sys
import threading

PORT = int(sys.argv[1])
OUT = sys.argv[2]
LOCK = threading.Lock()
NEXT_OFFSET = {}  # (topic, partition) -> next offset


def crc32c(data):
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x82F63B78 if crc & 1 else crc >> 1
    return crc ^ 0xFFFFFFFF


def read_varint(buf, pos):
    shift = 0
    n = 0
    while True:
        b = buf[pos]
        pos += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            break
        shift += 7
    return (n >> 1) ^ -(n & 1), pos


def string_at(buf, pos):
    (n,) = struct.unpack(">h", buf[pos:pos + 2])
    pos += 2
    if n < 0:
        return None, pos
    return buf[pos:pos + n].decode(), pos + n


def decode_batch(b):
    """One record batch (magic 2). The CRC covers attributes to the end and is checked first."""
    (crc,) = struct.unpack(">I", b[17:21])
    if crc32c(b[21:]) != crc:
        raise ValueError("bad CRC-32C")
    (first_ts,) = struct.unpack(">q", b[27:35])
    (count,) = struct.unpack(">i", b[57:61])
    pos = 61
    out = []
    for _ in range(count):
        length, pos = read_varint(b, pos)
        end = pos + length
        pos += 1  # record attributes
        ts_delta, pos = read_varint(b, pos)
        off_delta, pos = read_varint(b, pos)
        klen, pos = read_varint(b, pos)
        key = None
        if klen >= 0:
            key = b[pos:pos + klen].decode()
            pos += klen
        vlen, pos = read_varint(b, pos)
        value = b[pos:pos + vlen].decode()
        pos += vlen
        _headers, pos = read_varint(b, pos)
        if pos != end:
            raise ValueError("record length mismatch")
        out.append({"key": key, "value": value, "ts": first_ts + ts_delta, "off": off_delta})
    return out


def metadata_response(body):
    """Metadata v1: this process as the one broker, and two partitions for each requested topic."""
    (n,) = struct.unpack(">i", body[:4])
    pos = 4
    topics = []
    for _ in range(n):
        name, pos = string_at(body, pos)
        topics.append(name)
    host = b"127.0.0.1"
    out = struct.pack(">i", 1) + struct.pack(">i", 1) + struct.pack(">h", len(host)) + host + struct.pack(">i", PORT) + struct.pack(">h", -1)
    out += struct.pack(">i", 1)  # controller id
    out += struct.pack(">i", len(topics))
    for name in topics:
        raw = name.encode()
        out += struct.pack(">h", 0) + struct.pack(">h", len(raw)) + raw + b"\x00"  # error, name, is_internal
        out += struct.pack(">i", 2)
        for p in (0, 1):
            out += struct.pack(">h", 0) + struct.pack(">i", p) + struct.pack(">i", 1)  # error, partition, leader
            out += struct.pack(">i", 1) + struct.pack(">i", 1)  # replicas
            out += struct.pack(">i", 1) + struct.pack(">i", 1)  # isr
    return out


def produce_response(body):
    """Produce v3: stores each partition's batch in OUTFILE and answers with its base offset."""
    _tid, pos = string_at(body, 0)
    pos += 6  # acks and timeout
    (nt,) = struct.unpack(">i", body[pos:pos + 4])
    pos += 4
    answers = []
    for _ in range(nt):
        topic, pos = string_at(body, pos)
        (np_,) = struct.unpack(">i", body[pos:pos + 4])
        pos += 4
        parts = []
        for _ in range(np_):
            (part,) = struct.unpack(">i", body[pos:pos + 4])
            (blen,) = struct.unpack(">i", body[pos + 4:pos + 8])
            pos += 8
            batch = body[pos:pos + blen]
            pos += blen
            recs = decode_batch(batch)
            with LOCK:
                base = NEXT_OFFSET.get((topic, part), 0)
                NEXT_OFFSET[(topic, part)] = base + len(recs)
                with open(OUT, "a") as f:
                    f.write(json.dumps({"topic": topic, "partition": part, "offset": base, "records": recs}) + "\n")
            parts.append((part, base))
        answers.append((topic, parts))
    out = struct.pack(">i", len(answers))
    for topic, parts in answers:
        raw = topic.encode()
        out += struct.pack(">h", len(raw)) + raw + struct.pack(">i", len(parts))
        for part, base in parts:
            out += struct.pack(">i", part) + struct.pack(">h", 0) + struct.pack(">q", base) + struct.pack(">q", -1)
    return out + struct.pack(">i", 0)  # throttle time


def api_versions_response():
    keys = [(0, 0, 3), (3, 0, 1), (18, 0, 0)]  # Produce 0-3, Metadata 0-1, ApiVersions 0
    out = struct.pack(">h", 0) + struct.pack(">i", len(keys))
    for key, lo, hi in keys:
        out += struct.pack(">hhh", key, lo, hi)
    return out


def recv_exact(conn, n):
    buf = b""
    while len(buf) < n:
        chunk = conn.recv(n - len(buf))
        if not chunk:
            raise EOFError()
        buf += chunk
    return buf


def handle(conn):
    try:
        while True:
            (size,) = struct.unpack(">i", recv_exact(conn, 4))
            req = recv_exact(conn, size)
            api, _ver, corr = struct.unpack(">hhi", req[:8])
            (cid_len,) = struct.unpack(">h", req[8:10])
            body = req[10 + max(cid_len, 0):]
            if api == 18:
                resp = api_versions_response()
            elif api == 3:
                resp = metadata_response(body)
            elif api == 0:
                resp = produce_response(body)
            else:
                break  # not a request this stub speaks: close the connection
            frame = struct.pack(">i", corr) + resp
            conn.sendall(struct.pack(">i", len(frame)) + frame)
    except (EOFError, ConnectionError, OSError, ValueError, struct.error):
        pass
    finally:
        conn.close()


def main():
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", PORT))
    s.listen(8)
    while True:
        conn, _ = s.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
