# UDP sockets: Bun.udpSocket, and node:dgram over the same natives

Branch `feat/udp`, one commit on top of `feat/alpn`: open it after the TLS ALPN pull request,
which it is built and tested on.

## What

`Bun.udpSocket(options)` opens a UDP socket: `data(socket, bytes, port, address)` gets
each datagram with the sender's port and address, and `send(text | bytes, port, address)`
sends one. `node:dgram` works on the same natives, where it was a stub that threw.

## Why

Tov had no datagram sockets. Local-network discovery by UDP broadcast and by mDNS needs
them, as does any UDP protocol a gateway might speak. `node:dgram` is part of the Node
compatibility layer, which can't stay a stub for a module that is listed as available.

## API

```ts
const sock = await Bun.udpSocket({
  hostname: "0.0.0.0",
  port: 9999,
  broadcast: true,
  reusePort: true,
  socket: {
    data(s, bytes, port, address) { s.send("ack", port, address) },
  },
})
sock.send("hello", 9999, "255.255.255.255")
sock.addMembership("239.255.42.99")
```

`send` returns whether the datagram went. The other methods are as in Bun:
`setBroadcast`, `setTTL`, `setMulticastTTL`, `setMulticastLoopback`,
`setMulticastInterface`, `addMembership`, `dropMembership`, `hostname`, `port`, `ref`,
`unref` and `close`.

## Design

- A socket is an entry of a table in `runtime/net.c`, watched by the same loop as the TCP
  and Unix sockets. Each received datagram is one event, with the sender's address and
  port. A socket keeps the program running while it reads, unless it is unref'd.
- `reusePort` sets `SO_REUSEADDR` and `SO_REUSEPORT`, so several sockets can share a port
  (multicast listeners).
- `runtime/node/internal/bindings/udp_wrap.js` implements Node's `udp_wrap` binding over
  the natives: bind, send (also connected), membership, options, names, recv start and
  stop, and close. `runtime/node.c` exposes the natives to it.
- Failures are `-errno` in the natives and a `SocketError` (`ERR_SOCKET`, `ERR_SOCKET_BIND`)
  from `Bun.udpSocket`.

## Tests

- `tests/run/native_udp.tov`: two sockets on loopback (a datagram and its reply, with the
  sender's port and address), the send buffer's options, a multicast group joined and
  left, and a closed socket that sends nothing.
`node:dgram` is checked by the Raiju suite (`tov-patches/tests/udp_dgram.tov`: a CommonJS
check of bind, send, receive, close and multicast membership through `tov run`), and is not
part of this commit's tests.

## Limits

- No source-specific multicast (IGMPv3) and no `connect` in the Tov API (send takes the
  address).
- Each `recvfrom` loop is bounded to 64 datagrams per wake-up, so a flood can't starve the
  other sockets of the loop.
- A `send` that fails (for example with no route to a multicast group) returns `false` and
  is not retried.
