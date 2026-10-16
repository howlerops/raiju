# Native client spike (L99)

Two small clients for the management API, built with the same scope: a window with the
provider list on the left (`GET /api/providers`) and a scrolling live log on the right, newest
on top, with model, status, latency and tokens (the `/ws` log feed). One is built with gpui
(`gpui-spike/`), one with Slint (`slint-spike/`). Each is its own Cargo project and shares
nothing with the other except `src/data.rs`, which is copied unchanged into both.

- `src/data.rs`: the data layer. Blocking HTTP (ureq) for the provider list, a blocking WebSocket
  client (tungstenite) for `/ws`, the models (`Provider`, `LogEvent`, `Msg`), and `run_feed`, the
  loop a UI runs on a background thread (providers first, then the log stream, provider refresh
  every 10 s, reconnect after a failure). Unit-tested: `cargo test`.
- `src/main.rs`: the UI, plus `--headless` (no window: fetch the providers, wait for one live log
  event, print both).

## Running

Configuration (both clients): `RAIJU_URL` (default `http://127.0.0.1:18171`, plain http only)
and `RAIJU_TOKEN` (default `admin-secret`, the admin token of the e2e config). The `/ws` socket
takes the same bearer token. Start a gateway first, e.g. `build/raiju -port 18171 -config <cfg>`.

```
cd clients/gpui-spike  && cargo build --release && ./target/release/raiju-gpui-spike
cd clients/slint-spike && cargo build --release && ./target/release/raiju-slint-spike
```

Headless check (no display needed): `raiju-gpui-spike --headless` or `raiju-slint-spike --headless`
prints the providers and the first live log event, exits 0 on success, 1 otherwise.
Unit tests: `cargo test` in either project.

Slint also renders one frame without a display: `raiju-slint-spike --screenshot out.png`
collects the feed for 4 s, draws with the software renderer (its own window-less platform) and
writes a PNG. `slint-spike/screenshot.png` is from a run against a gateway that had served
a few chat requests.

### Build requirements (Linux)

gpui needs system libraries on Linux. Installed here with apt (Ubuntu 24.04):
`libxkbcommon-dev libxkbcommon-x11-dev libwayland-dev libvulkan-dev libxcb1-dev libxcb-xkb-dev
libxcb-render0-dev libxcb-shape0-dev libxcb-xfixes0-dev libx11-xcb-dev libxcb-randr0-dev
libxcb-cursor-dev libfontconfig-dev libfreetype-dev libasound2-dev cmake`.
Slint's winit backend needs only the display stack at run time (X11 or Wayland), no extra
packages to build.

gpui 0.2.2 (the crates.io release) pulls `xattr 0.2.3` through `zed-async-tar`, which uses
`libc::ENOATTR`. The libc versions this build resolves to (0.2.182 and later, required by rustix
1.1.5) no longer define it on Linux, so `gpui-spike/vendor/xattr` is the same 0.2.3 crate with
`ENOATTR = ENODATA` (the Linux value), wired in with `[patch.crates-io]`. Remove the patch once
libc or xattr is fixed upstream.

Slint 1.18 needs its `compat-1-18` feature when `default-features = false` (set in
`slint-spike/Cargo.toml`). `rust-version` is 1.92 for Slint and 1.97 is what was installed here.

## Comparison

Measured in this container (4 cores, 15 GB RAM), both release builds from `cargo clean`:

| | gpui 0.2.2 | Slint 1.18.1 |
|---|---|---|
| Clean `cargo build --release` | 535 s | 245 s |
| Release binary, as built | 25.8 MB | 25.4 MB |
| Release binary, stripped | 18.8 MB | 19.6 MB |
| Unique crates in the runtime graph (`cargo tree -e normal`) | 660 | 431 |
| Direct dependencies | 5 | 5 |
| Rust lines (`src/`: data + main) | 470 | 467, plus 112 lines of `.slint` and a 3-line `build.rs` |
| Linux system packages to build | 16 apt packages (listed above, incl. cmake) plus the xattr patch | none beyond the display stack (not checked here) |
| Windowed run here | not run (no display) | not run (no display) |
| Headless path | `--headless` | `--headless` and a PNG frame (`--screenshot`) |
| License | Apache-2.0 | GPL-3.0-only OR Slint Royalty-free 2.0 OR Slint Commercial (choose one) |

Wiring the async feed into the event loop:

- gpui: the feed thread sends `Msg` values into a `futures` unbounded channel. The window's view
  starts one `cx.spawn` task that awaits the channel and calls `weak.update(cx, ...)` plus
  `cx.notify()`. The view is an ordinary struct on the UI thread. About 15 lines, no shared state.
  The spike needed `futures` as an extra direct dependency for the channel.
- Slint: the feed thread calls `slint::invoke_from_event_loop` with a closure that captures a
  `Weak` handle and the `Msg`. `VecModel` is `Rc`-based and not `Send`, so the models live in a
  `thread_local!` on the UI thread, and every update goes through it. The screenshot mode also
  needs a small platform implementation (`MinimalSoftwareWindow`), about 40 lines. More moving
  parts than gpui, but each step is explicit and the mechanism is documented.

Not measured: startup time, memory and frame feel. Both need a display, and the container has
none; these are the first things to measure on a desktop.

## Recommendation

Use Slint for the native client. The reasons are the ones this spike can show: a smaller
dependency graph (431 vs 660 crates), a build about half as long, no system packages beyond the
display stack, a stable 1.x release with a declarative `.slint` UI, and headless rendering that
works without a display. The owner's stated targets include mobile. Slint documents Android and
iOS targets (not built or run here), while gpui's mobile path is experimental (gpui-mobile) and
gpui is still 0.2.x on crates.io.
Pick gpui only if the desktop-only scope holds and the Apache-2.0 terms without an attribution
requirement matter more than build size and mobile maturity. The Slint licence is the decision
to take to the owner: the royalty-free option carries attribution and terms to check, and the
commercial option is a purchase.
