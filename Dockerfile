# syntax=docker/dockerfile:1

# Build stage. Tov is built from source with the patches in tov-patches/
# (0001-0008: streamed bodies, child sockets, ALPN, UDP, WAMR, libdatachannel,
# the fetch pool with nghttp2, streamed request bodies), so it needs Rust and a
# C and C++ compiler: the vendored BoringSSL, WAMR, libdatachannel and nghttp2
# compile on first use. The gateway imports node:* modules, which Tov links
# through WebKitGTK's JavaScriptCore (pkg-config javascriptcoregtk-4.1). Debian
# bookworm matches the glibc and libraries of the runtime image below.
FROM debian:bookworm-slim AS build

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git make gcc g++ libc6-dev \
      pkg-config libjavascriptcoregtk-4.1-dev \
 && rm -rf /var/lib/apt/lists/*

ENV PATH=/root/.cargo/bin:$PATH
RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain 1.97.0

WORKDIR /src
COPY . .
# /out/app/data is the -app-dir: config.json is mounted (or provided) there.
RUN scripts/build-tov.sh \
 && mkdir -p /out/app/data \
 && TOV_CFLAGS=-DTV_PLAIN_ALLOC build/tov/target/release/tov build src/main.tov -o /out/raiju

# Runtime. The binary links glibc, libstdc++ and libatomic (for the vendored C++
# libraries) and JavaScriptCore with its GLib and ICU libraries; check with `ldd`.
# distroless/cc has no JavaScriptCore, so this is bookworm-slim with that library
# and CA certificates for HTTPS upstreams. No HEALTHCHECK (no curl): probe
# GET /health from outside.
FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates libjavascriptcoregtk-4.1-0 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build --chown=65532:65532 /out/app /app
COPY --from=build /out/raiju /usr/local/bin/raiju

EXPOSE 8080
# the app dir (the gateway reads its log and audit folders from -app-dir, not from here, but a relative path given
# by hand lands somewhere writable)
WORKDIR /app/data
# Numeric UID so Kubernetes runAsNonRoot can verify it.
USER 65532:65532

ENTRYPOINT ["/usr/local/bin/raiju"]
CMD ["-app-dir", "/app/data", "-host", "0.0.0.0", "-port", "8080"]
