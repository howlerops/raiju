# syntax=docker/dockerfile:1

# Build stage. Tov is built from source with the patches in tov-patches/
# (streamed response bodies), so it needs Rust and a C++ compiler (Tov builds
# BoringSSL for TLS on first use). Debian bookworm
# matches the glibc of the runtime image below.
FROM debian:bookworm-slim AS build

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git make gcc g++ libc6-dev \
 && rm -rf /var/lib/apt/lists/*

ENV PATH=/root/.cargo/bin:$PATH
RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal

WORKDIR /src
COPY . .
# /out/app/data is the -app-dir: config.json is mounted (or provided) there.
RUN scripts/build-tov.sh \
 && mkdir -p /out/app/data \
 && TOV_CFLAGS=-DTV_PLAIN_ALLOC build/tov/target/release/tov build src/main.tov -o /out/raiju

# Runtime. The binary links glibc, libm and (built here, with Tov's BoringSSL
# compiled by g++) libstdc++ dynamically; check with `ldd`. distroless/cc adds
# libstdc++, libgcc and CA certificates for HTTPS upstreams to glibc. There is
# no shell and no curl, so HEALTHCHECK is not possible: probe GET /health from outside.
FROM gcr.io/distroless/cc-debian12:nonroot

COPY --from=build --chown=65532:65532 /out/app /app
COPY --from=build /out/raiju /usr/local/bin/raiju

EXPOSE 8080
# Numeric UID so Kubernetes runAsNonRoot can verify it.
USER 65532:65532

ENTRYPOINT ["/usr/local/bin/raiju"]
CMD ["-app-dir", "/app/data", "-host", "0.0.0.0", "-port", "8080"]
