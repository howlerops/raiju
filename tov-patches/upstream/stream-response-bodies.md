# Stream response bodies from Bun.serve

Branch `feat/stream-response-bodies` (one commit on c2048582).

## What

`new Response(stream)` in `Bun.serve` now accepts a `ReadableStream` made with an
underlying source. The head goes out with `transfer-encoding: chunked`, and each chunk
is sent as soon as it is enqueued. `text()` and `bytes()` on such a response read the
stream to the end.

## Why

`Bun.serve` answered only with a body that was complete when the handler returned. A
handler could not send server-sent events or any other incremental output. A program
that needed streaming had to run its own HTTP server on `Bun.listen`, which can't use
`workers: n`.

## API

As in Bun and the web platform:

```ts
const body = new ReadableStream({
  start(controller) {        // enqueue(bytes | string), close(), error(e)
    controller.enqueue("data: hi\n\n")
    controller.close()
  },
  cancel() {},               // the client went away before the end
})
return new Response(body, { headers: { "content-type": "text/event-stream" } })
```

`ReadableStreamDefaultController` is a new global. `controller.desiredSize` is the
number of queued bytes, negated.

## Design

- `ReadableStream` takes an optional underlying source. Chunks enqueued by the source
  queue in the stream. `pull()` waits on a promise that the next `enqueue` or `close`
  resolves.
- `Response` accepts a `ReadableStream` body. For a handler's response, `Bun.serve`
  defers the request, writes the head and then each chunk with the existing
  `tv_native_httpWriteRaw`, and finishes with the zero-length chunk. Sending stays on
  the worker's own connection, so it works in every forked worker.
- A client that disconnects (`httpBuffered` reports it gone) cancels the stream, and
  the source's `cancel` runs.
- Changes: `runtime/tov.c`, `runtime/tov.h` (two natives), `check/builtins.rs` (their
  signatures), `std/http.tov` (source, controller, stream body, `pump`), `driver.rs`
  (the controller global), `docs/spec.md`.

## Tests

- `tests/http.rs`, against `tests/http/app.tov`:
  - `/stream` (three chunks, 100 ms apart): `transfer-encoding: chunked`, no
    `content-length`, the three chunks in order, and the first chunk reaches the client
    at least 150 ms before the last.
  - `/endless` (a chunk every 50 ms): a client that reads one chunk and leaves causes
    `cancel` to run (checked on the server's stdout), and the next request is served.
  - Twelve streams at once on three workers all complete.
- `tests/run/native_stream_response.tov`: `text()` and `bytes()` drain a pushed stream,
  an empty stream gives `""`, and a stream that errors makes `text()` reject with that
  error.

`cargo test --release --test http` passes. `--test run` passes except the npm case,
which needs JavaScriptCore installed.

If the source calls `error(e)` after the head has gone out, the connection is closed
without the terminating chunk (`httpStreamAbort`), so the client sees a cut-off body,
as with Bun.

## Limits

- There is no backpressure: chunks enqueued faster than the client reads queue in
  memory.
- Only the underlying source's `start` and `cancel` are supported; there is no `pull`,
  no `type: "bytes"`, and no `tee`/`pipeThrough`.
- Request bodies are not streams yet.
