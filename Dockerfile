# syntax=docker/dockerfile:1

# Build stage. Tov is built from source by its installer; the installer also
# installs Rust when cargo is missing. Debian bookworm matches the glibc of the
# runtime image below.
FROM debian:bookworm-slim AS build

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git make gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*

ENV PATH=/root/.cargo/bin:$PATH
RUN curl -fsSL https://tov.sh/install.sh | sh

WORKDIR /src
COPY . .
# /out/app/data is the -app-dir: config.json is mounted (or provided) there.
RUN mkdir -p /out/app/data \
 && TOV_CFLAGS=-DTV_PLAIN_ALLOC tov build src/main.tov -o /out/raiju

# Runtime. The binary links glibc and libm dynamically (check with
# `ldd build/raiju`), so a fully static base is not enough. base-debian12 adds
# glibc, libgcc and CA certificates for HTTPS upstreams. There is no shell and
# no curl, so HEALTHCHECK is not possible: probe GET /health from outside.
FROM gcr.io/distroless/base-debian12:nonroot

COPY --from=build --chown=65532:65532 /out/app /app
COPY --from=build /out/raiju /usr/local/bin/raiju

EXPOSE 8080
# Numeric UID so Kubernetes runAsNonRoot can verify it.
USER 65532:65532

ENTRYPOINT ["/usr/local/bin/raiju"]
CMD ["-app-dir", "/app/data", "-host", "0.0.0.0", "-port", "8080"]
