# syntax=docker/dockerfile:1

# Both stages use the same Ubuntu 24.04 LTS (noble) image, pinned by date tag and digest (the multi-arch index) so a
# rebuild gets the same base. To move to a newer one, take the tag and its digest from
# `docker buildx imagetools inspect ubuntu:noble-<date>` and change ARG BASE.
# Ubuntu rather than Debian bookworm: Ubuntu ships fixes for the glibc and util-linux CVEs that bookworm leaves unfixed
# (CVE-2026-84243, CVE-2026-53613, CVE-2026-53615), and noble is the release CI builds the compiler on.
ARG BASE=ubuntu:noble-20261024.1@sha256:fe81560990fae86dc4743202b2cb4d3df98d0bcf949173cecef15ce1127ef852

# Build stage. Tov is built from source with the patches in tov-patches/ (applied in name order by
# scripts/build-tov.sh: streamed bodies, child sockets, ALPN, UDP, WAMR, libdatachannel, the fetch pool with
# nghttp2, request body streams, node:fs rename and fsync, a WASM time limit, the server lifecycle), so it needs
# Rust and a C and C++ compiler: the vendored BoringSSL, WAMR, libdatachannel and nghttp2 compile on first use.
# The gateway imports node:* modules, which Tov links through WebKitGTK's JavaScriptCore (pkg-config
# javascriptcoregtk-4.1). The same base as the runtime image below, so glibc and the libraries match.
FROM ${BASE} AS build

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
# The compiler first, from its only inputs (the patches and the build script), so a change under src/ reuses this
# layer instead of recompiling Tov.
COPY tov-patches/ tov-patches/
COPY scripts/build-tov.sh scripts/build-tov.sh
RUN scripts/build-tov.sh
COPY src/ src/
# /out/app/data is the -app-dir: config.json is mounted (or provided) there.
RUN mkdir -p /out/app/data \
 && TOV_CFLAGS=-DTV_PLAIN_ALLOC build/tov/target/release/tov build src/main.tov -o /out/raiju

# Runtime. The binary links glibc, libstdc++ and libatomic (for the vendored C++ libraries) and JavaScriptCore with
# its GLib and ICU libraries; check with `ldd`. distroless/cc has no JavaScriptCore, so this is Ubuntu noble with
# that library and CA certificates for HTTPS upstreams.
FROM ${BASE}

ENV DEBIAN_FRONTEND=noninteractive
# The upgrade takes the Ubuntu security fixes released since the pinned base (glibc, util-linux, openssl, ...), so the
# image scan stays clean between base bumps. The gateway never mounts anything, so the `mount` package (setuid
# mount/umount, the restricted-mount path of CVE-2026-78410, unfixed upstream) is removed; libmount1 stays for GLib.
# Nothing in the image needs to change user, so the setuid and setgid bits of what remains (su, passwd, ...) are cleared:
# the gateway runs as 65532 and has no use for a path to root, also where no-new-privileges is not set.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && apt-get install -y --no-install-recommends ca-certificates libjavascriptcoregtk-4.1-0 \
 && apt-get purge -y --allow-remove-essential mount \
 && find / -xdev -type f -perm /6000 -exec chmod a-s {} + \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build --chown=65532:65532 /out/app /app
COPY --from=build /out/raiju /usr/local/bin/raiju

EXPOSE 8080
# Numeric UID so Kubernetes runAsNonRoot can verify it.
USER 65532:65532
# /app/data holds config.json and the state Raiju writes beside it (config.json.bak, mcp-oauth-state.json,
# mcp-flow-state.json, logs/ and logs/audit/): mount a writable volume there to keep it. Without one, Docker gives
# the container an anonymous volume. It is also the working directory: the
# gateway reads its log and audit folders from -app-dir, but a relative path given by hand lands somewhere writable.
WORKDIR /app/data
# Fargate copies directory metadata only for declared volumes. Without /tmp here its task bind mount is
# root-owned 0755, so user 65532 cannot create the worker-share or request-log directories. Preserve /tmp's 1777 mode.
VOLUME ["/app/data", "/tmp"]

# The image has no curl: the binary probes itself. `raiju -healthcheck` GETs /health on 127.0.0.1 at -port, or
# PORT, or 8080; set PORT when the command below listens elsewhere.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["/usr/local/bin/raiju", "-healthcheck"]

ENTRYPOINT ["/usr/local/bin/raiju"]
CMD ["-app-dir", "/app/data", "-host", "0.0.0.0", "-port", "8080"]
