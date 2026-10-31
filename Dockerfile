# syntax=docker/dockerfile:1

# Both stages use the same Debian bookworm image, pinned by date tag and digest (the multi-arch index) so a
# rebuild gets the same base. To move to a newer one, take the tag and its digest from
# `docker buildx imagetools inspect debian:bookworm-<date>-slim` and change both FROM lines.
ARG DEBIAN=debian:bookworm-20261005-slim@sha256:7c7b2c966bc9ee8cedfeef67e0e279108992c77681fa595db4a9d65c06ccc587

# Build stage. Tov is built from source with the patches in tov-patches/ (applied in name order by
# scripts/build-tov.sh: streamed bodies, child sockets, ALPN, UDP, WAMR, libdatachannel, the fetch pool with
# nghttp2, request body streams, node:fs rename and fsync, a WASM time limit, the server lifecycle), so it needs
# Rust and a C and C++ compiler: the vendored BoringSSL, WAMR, libdatachannel and nghttp2 compile on first use.
# The gateway imports node:* modules, which Tov links through WebKitGTK's JavaScriptCore (pkg-config
# javascriptcoregtk-4.1). Debian bookworm matches the glibc and libraries of the runtime image below.
FROM ${DEBIAN} AS build

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git make gcc g++ libc6-dev \
      pkg-config libjavascriptcoregtk-4.1-dev \
 && rm -rf /var/lib/apt/lists/*

# rustup-init at a fixed version, checked against its published sha256 (no `curl | sh`), then a fixed toolchain.
ARG RUSTUP_VERSION=1.28.2
ARG RUSTUP_SHA256_AMD64=20a06e644b0d9bd2fbdbfd52d42540bdde820ea7df86e92e533c073da0cdd43c
ARG RUSTUP_SHA256_ARM64=e3853c5a252fca15252d07cb23a1bdd9377a8c6f3efa01531109281ae47f841c
ENV PATH=/root/.cargo/bin:$PATH
RUN set -eu; \
    case "$(dpkg --print-architecture)" in \
      amd64) triple=x86_64-unknown-linux-gnu; sum=$RUSTUP_SHA256_AMD64 ;; \
      arm64) triple=aarch64-unknown-linux-gnu; sum=$RUSTUP_SHA256_ARM64 ;; \
      *) echo "unsupported architecture: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac; \
    curl -fsSLo /tmp/rustup-init "https://static.rust-lang.org/rustup/archive/${RUSTUP_VERSION}/${triple}/rustup-init"; \
    echo "${sum}  /tmp/rustup-init" | sha256sum -c -; \
    chmod +x /tmp/rustup-init; \
    /tmp/rustup-init -y --no-modify-path --profile minimal --default-toolchain 1.97.0; \
    rm /tmp/rustup-init

WORKDIR /src
COPY . .
# /out/app/data is the -app-dir: config.json is mounted (or provided) there.
RUN scripts/build-tov.sh \
 && mkdir -p /out/app/data \
 && TOV_CFLAGS=-DTV_PLAIN_ALLOC build/tov/target/release/tov build src/main.tov -o /out/raiju

# Runtime. The binary links glibc, libstdc++ and libatomic (for the vendored C++ libraries) and JavaScriptCore with
# its GLib and ICU libraries; check with `ldd`. distroless/cc has no JavaScriptCore, so this is bookworm-slim with
# that library and CA certificates for HTTPS upstreams.
FROM ${DEBIAN}

ENV DEBIAN_FRONTEND=noninteractive
# the upgrade takes the Debian security fixes released since the pinned base (openssl, perl-base, ...), so the image
# scan stays clean between base bumps
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y --no-install-recommends ca-certificates libjavascriptcoregtk-4.1-0 \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build --chown=65532:65532 /out/app /app
COPY --from=build /out/raiju /usr/local/bin/raiju

EXPOSE 8080
# Numeric UID so Kubernetes runAsNonRoot can verify it.
USER 65532:65532
# /app/data holds config.json and the state Raiju writes beside it (config.json.bak, mcp-oauth-state.json,
# mcp-flow-state.json, logs/ and logs/audit/): mount a writable volume there to keep it. Without one, Docker gives
# the container an anonymous volume (as Bifrost's image declares its app dir). It is also the working directory: the
# gateway reads its log and audit folders from -app-dir, but a relative path given by hand lands somewhere writable.
WORKDIR /app/data
VOLUME ["/app/data"]

# The image has no curl: the binary probes itself. `raiju -healthcheck` GETs /health on 127.0.0.1 at -port, or
# PORT, or 8080; set PORT when the command below listens elsewhere.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["/usr/local/bin/raiju", "-healthcheck"]

ENTRYPOINT ["/usr/local/bin/raiju"]
CMD ["-app-dir", "/app/data", "-host", "0.0.0.0", "-port", "8080"]
