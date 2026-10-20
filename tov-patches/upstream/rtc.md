# std/rtc: WebRTC peer connections, data channels and RTP audio on libdatachannel

Branch `feat/rtc` (one commit on c2048582). Series: [rtc/](rtc/). Raiju patch: `0006-libdatachannel.patch`.

Depends on: nothing; it applies to c2048582 on its own. (In Raiju's series it comes after the
WebAssembly patch only because both add lines to the same lists: the native table, `tov.h`,
`STD_MODULES` and codegen. Whichever of the two merges second needs that one-line rebase.)

## What

`import { RTCPeerConnection } from "std/rtc"` makes a program a WebRTC peer: it can answer a
browser's SDP offer or make its own, open data channels (text and bytes), and send and receive
RTP audio packets. Callbacks run on Tov's event loop, like a browser's.

## Why

Tov had no WebRTC, so a program could not terminate a browser's WebRTC session. A server that
relays a browser's realtime audio session to another peer (and meters, guards or logs its data
channel events) needs all three: the SDP exchange, data channels and RTP.

## API

```ts
import { RTCPeerConnection } from "std/rtc"

const pc = try new RTCPeerConnection({ iceServers: ["stun:stun.example.test:3478"], bindAddress: "127.0.0.1" })
pc.ondatachannel = (ch) => { ch.onmessage = (m) => ch.send(m) }        // text or bytes
pc.ontrack = (t) => { t.onpacket = (rtp) => other.sendRtp(rtp, ssrc, pt) }
pc.onlocaldescription = (sdp, type) => {}      // an answer to a remote offer is made on its own
pc.ongatheringchange = (s) => { if (s === "complete") reply(pc.localDescription) }
pc.onstatechange = (s) => {}                   // new, connecting, connected, disconnected, failed, closed
pc.setRemoteDescription(offer, "offer")        // "" or the error
pc.addTrack({ codec: "opus", direction: "sendrecv" })
pc.createDataChannel("events")
pc.setLocalDescription()                       // an offer, from the channels and tracks added
pc.close()                                     // frees it, its channels and tracks; no callback fires after
```

`RTCDataChannel` has `send`, `bufferedAmount`, `onopen`, `onmessage`, `onclose`, `onerror`,
`onbufferedamountlow` and `close`. `RTCTrack` has `sendRtp(packet, ssrc?, payloadType?)` (a
negative or missing value keeps the packet's own; otherwise the header is rewritten, which is how a
relay puts one leg's packets on the other's stream), `onpacket`, `payloadType` and `direction`.
`RTCPeerConnection` also has `localDescription`, `localDescriptionType`, `state` and
`selectedCandidatePair`. `TOV_RTC_LOG=debug|info|warning|none` sets the library's log level
(default: errors, to stderr).

## Design

- libdatachannel v0.24.6 is vendored under `vendor/rtc/` with the libraries it is built from, at
  the commits it pins, minus tests, examples, docs and build scripts (table below).
  `vendor/rtc/srtp/config.h` is the one file of Tov's own (what libsrtp's CMake writes for the
  OpenSSL backend, with the platform chosen by compiler macros). `vendor/rtc/TOV.md` lists the
  commits, the files and the flags. WebSockets in libdatachannel are compiled out
  (`RTC_ENABLE_WEBSOCKET=0`).
- The crypto library is the vendored BoringSSL that `fetch()` already links: libdatachannel's
  OpenSSL backend and libsrtp's OpenSSL provider compile and run against it (DTLS 1.2 with the
  SRTP profiles, X.509 fingerprints), so a program carries one TLS library. Programs that use
  `std/rtc` link it.
- `runtime/rtc.c` is the bridge, over libdatachannel's C API. The library calls back on threads of
  its own and nothing there touches the Tov runtime: each callback appends an event to a
  mutex-protected queue and writes a byte to a pipe the event loop watches (`tv_io_add` in
  `runtime/net.c`); the loop pops the events and runs one Tov closure per event
  (`(kind, id, n, bytes, text)`), which `std/rtc` routes to the objects. A callback installs the
  callbacks of a channel or track the remote side made before it returns, so none of its events is
  missed. RTP packets are dropped, not queued, once 4,096 events wait. A live peer connection
  keeps the program running; at exit the connections still open are closed (`atexit`), so the
  library's threads do not hold the process.
- The natives (`rtc*` in `runtime/net.c`, declared in `tov.h`, signatures in `builtins.rs`) go
  through a table of operations (`tv_rtc_impl`) that only `rtc.c` fills, so programs without
  `std/rtc` carry none of it. Codegen adds `tv_rtc_install()` to a program that calls `rtcPeer`;
  the build then links the rtc archive in front of the TLS ones, with `-lstdc++`.
- The archive is compiled the first time a program needs it (about four minutes on four cores at
  `-O2`) by `crates/tov/src/build/rtc.rs`, from sources the compiler embeds (as it embeds the TLS
  ones), and cached by a hash of the sources, the compiler and the flags.

## Changes

- `runtime/rtc.c`, `runtime/net.c`, `runtime/tov.h`: the bridge, the natives, the operations table.
- `crates/tov/src/std/rtc.tov`, `crates/tov/src/driver.rs`: the module and its registration.
- `crates/tov/src/check/builtins.rs`: the native signatures.
- `crates/tov/src/codegen/mod.rs`, `crates/tov/src/build.rs`, `crates/tov/src/build/rtc.rs`,
  `crates/tov/build.rs`: the install call, the archive, its cache and its link.
- `vendor/rtc/`: the libraries and `TOV.md`.
- `docs/spec.md`: the `std/rtc` line in §7a.

## Vendored code

| Directory | Library | Version (as pinned by libdatachannel v0.24.6) | Licence |
|---|---|---|---|
| `vendor/rtc/datachannel/` | [libdatachannel](https://github.com/paullouisageneau/libdatachannel) | v0.24.6, commit `55f93686c01528224f448c19128836e7df245f72` | MPL-2.0 (`datachannel/LICENSE`) |
| `vendor/rtc/juice/` | [libjuice](https://github.com/paullouisageneau/libjuice) (ICE, STUN, TURN) | commit `b89c792e3612faf2f12cf35bcc56857313a06be3` | MPL-2.0 (`juice/LICENSE`) |
| `vendor/rtc/usrsctp/` | [usrsctp](https://github.com/sctplab/usrsctp) (SCTP for data channels) | commit `fec583d54493f879d2ae44a743423bf8a04371ab` | BSD-3-Clause (`usrsctp/LICENSE.md`) |
| `vendor/rtc/srtp/` | [libsrtp](https://github.com/cisco/libsrtp) | 2.8.0, commit `24b3bf8f19b6f5ab4cd2bcceb4f4064efca86fd5` | BSD-3-Clause (`srtp/LICENSE`) |
| `vendor/rtc/plog/` | [plog](https://github.com/SergiusTheBest/plog) (headers) | commit `94899e0b926ac1b0f4750bfbd495167b4a6ae9ef` | MIT (`plog/LICENSE`) |

MPL-2.0 is file-level copyleft: the libdatachannel and libjuice files stay under MPL-2.0 and
their source must remain available (it is, vendored), while the rest of Tov and the programs it
builds keep their own licences. A maintainer may still prefer not to carry MPL code in an MIT
repository; the alternative is linking a system libdatachannel, which this change does not do.

## Tests

`tests/run/native_rtc.tov` (20 checks): two peers in one program on the loopback address. An offer
made from a track and a channel (it holds `m=audio`, `m=application` and candidates), the answer
made from it, both descriptions accepted, the channel opened on both sides, text and bytes both
ways, the track opened, Opus negotiated (payload type 111), five RTP packets arriving with the SSRC
and payload type rewritten, a selected candidate pair, the connected state, and close. The first
build of the test compiles the rtc archive (a few minutes; cached after). Checked by building the
branch and running the program (output equal to `native_rtc.stdout`).

## Limits

- Audio only (Opus, PCMU, PCMA); no video.
- No media handlers (packetizers, NACK, bandwidth estimation): RTP passes as it is, with the
  library's receiver reports.
- No WebSocket or TURN-over-TCP use of the library; no Windows.
- The macOS flags for usrsctp and the C++ link follow its documentation and are untested.
- The test notes one compiler fault it works around (an inner closure that captures the outer
  closure's class-typed parameter does not compile; see `compiler-bugs.md`).
