# Socket TLS: offer ALPN protocols and read the one picked

Branch `feat/alpn` (one commit on c2048582).

## What

`Bun.connect` takes `tls: { alpn: string[] }`, the protocols a TLS client offers, and
`Socket.alpnProtocol` reads the protocol the server picked (`""` when none, and for
plaintext sockets).

## Why

A TLS client couldn't ask a server for HTTP/2. gRPC over TLS needs `h2` in ALPN, so a
gRPC client could only reach a plaintext server (h2c). Tov's `fetch` speaks HTTP/1.1 only,
so gRPC runs on a raw socket, and the socket has to offer the protocol itself.

## API

```ts
const s = try await Bun.connect({
  hostname: "collector",
  port: 4317,
  tls: { alpn: ["h2"], ca: pem },
  socket: {},
})
if (s.alpnProtocol !== "h2") s.terminate()
```

Without `alpn` the TLS context keeps its default protocols, as before.

## Design

- `runtime/tls.c`: the offer is written as the length-prefixed list of RFC 7301 and set with
  `SSL_set_alpn_protos`. A list with an empty or over-long name sends no offer. The session cache key
  includes a hash of the list, so a session is resumed only for the same offer.
- `runtime/tls.c`: `alpnProtocol` copies `SSL_get0_alpn_selected` once the handshake is done.
- `runtime/net.c`: `netConnect` takes the offer as a NUL-separated list; `netAlpn` reads the
  protocol of a socket.
- Changes: `runtime/net.c`, `runtime/tls.c`, `runtime/tov.c`, `runtime/tov.h`, `runtime/ws.c`
  (the new `netConnect` argument), `check/builtins.rs` (the signatures), `std/http.tov`
  (`SocketTLSOptions.alpn`, `Socket.alpnProtocol`), `docs/spec.md`.

## Tests

`tests/run/native_alpn.tov`: a TLS listener (its own self-signed certificate, as in
`native_sockets.tov`) and two clients. One offers `h2` and `http/1.1`, and one offers
nothing. Each checks that the handshake succeeds and that `alpnProtocol` is `""`, because
`Bun.listen` has no ALPN and picks none.

## Limits

- Tov's listeners don't select a protocol. Selecting one on the server side is a separate
  change; this one covers the client's offer and read.
- `alpn` on a `WebSocket` client is not exposed; it goes through the same `netConnect`
  with no offer.
