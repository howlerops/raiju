#!/usr/bin/env python3
"""A WebRTC browser built on aiortc, a second implementation next to libdatachannel: the end-to-end test
for POST /v1/live/sessions uses it (when aiortc is importable) to check that the gateway's peer connection
interoperates with a stack that is not its own. Usage:

    webrtc_aiortc.py GATEWAY_ORIGIN [AUTHORIZATION]

It creates a session with an audio track and the "oai-events" data channel, sends session.update, sends
audio, asks the (fake) provider to speak, closes the session, and prints one JSON line: the events it
received, how many audio frames came back and how the session ended."""
import asyncio
import json
import sys
import urllib.request

from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration
from aiortc.mediastreams import AudioStreamTrack
from av import AudioFrame
import fractions
import time
import math
import struct


class Tone(AudioStreamTrack):
    """Audio frames of a quiet sine tone, 20 ms each, at 48 kHz."""

    def __init__(self):
        super().__init__()
        self._n = 0
        self._start = None

    async def recv(self):
        if self._start is None:
            self._start = time.time()
        samples = 960
        wave = struct.pack("<%dh" % samples, *[int(math.sin(2 * math.pi * 440 * (i + self._n) / 48000.0) * 3000) for i in range(samples)])
        frame = AudioFrame(format="s16", layout="mono", samples=samples)
        frame.planes[0].update(wave)
        frame.sample_rate = 48000
        frame.pts = self._n
        frame.time_base = fractions.Fraction(1, 48000)
        self._n += samples
        wait = self._start + self._n / 48000.0 - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
        return frame


async def main(origin, auth):
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    events = []
    frames = {"n": 0}
    pc.addTrack(Tone())
    channel = pc.createDataChannel("oai-events")
    opened = asyncio.Event()

    @channel.on("open")
    def on_open():
        opened.set()

    @channel.on("message")
    def on_message(m):
        events.append(json.loads(m))

    @pc.on("track")
    def on_track(track):
        async def drain():
            try:
                while True:
                    await track.recv()
                    frames["n"] += 1
            except Exception:
                pass
        asyncio.ensure_future(drain())

    await pc.setLocalDescription(await pc.createOffer())
    body = json.dumps({"session": {"model": "openai/gpt-4o-mini"}, "transport": {"type": "webrtc", "sdp": pc.localDescription.sdp}}).encode()
    headers = {"content-type": "application/json"}
    if auth:
        headers["authorization"] = auth
    req = urllib.request.Request(origin + "/v1/live/sessions", data=body, headers=headers, method="POST")
    loop = asyncio.get_running_loop()
    try:
        res = await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=20))
        status, text = res.status, res.read().decode()
    except urllib.error.HTTPError as e:
        status, text = e.code, e.read().decode()
    if status != 201:
        print(json.dumps({"status": status, "body": text}))
        await pc.close()
        return
    reply = json.loads(text)
    await pc.setRemoteDescription(RTCSessionDescription(sdp=reply["transport"]["sdp"], type="answer"))
    await asyncio.wait_for(opened.wait(), 15)

    def wait_for(kind, count=1, limit=8.0):
        async def go():
            t0 = time.time()
            while time.time() - t0 < limit:
                if len([e for e in events if e.get("type") == kind]) >= count:
                    return True
                await asyncio.sleep(0.02)
            return False
        return go()

    channel.send(json.dumps({"type": "session.update", "session": {"instructions": "be brief"}}))
    await wait_for("echo")
    await asyncio.sleep(1.0)  # some audio each way
    channel.send(json.dumps({"type": "test.speak", "text": "the quick brown fox"}))
    await wait_for("session.output_transcript.delta", 4)
    channel.send(json.dumps({"type": "session.close", "mock_seconds": 4}))
    closed = await wait_for("session.closed")
    print(json.dumps({"status": status, "session": reply["session"]["id"], "events": events, "frames": frames["n"], "closed": closed, "state": pc.connectionState}))
    await pc.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else ""))
