.PHONY: build test unit e2e ui web web-check check openapi-check parity-count run bench tov tov-test wasm-fixture

# Tov's async slab allocator corrupts its free lists once ~30 fetches are in
# flight (see docs/tov-notes.md); plain malloc avoids it at the same speed.
export TOV_CFLAGS ?= -DTV_PLAIN_ALLOC

# Raiju needs Tov with the patches in tov-patches/ (make tov builds it).
TOV_PATCHED := build/tov/target/release/tov
export TOV ?= $(if $(wildcard $(TOV_PATCHED)),$(abspath $(TOV_PATCHED)),tov)

tov:
	scripts/build-tov.sh

tov-test:
	tov-patches/tests/run.sh

build:
	mkdir -p build && $(TOV) build src/main.tov -o build/raiju

# The WebAssembly plugin the unit and e2e tests load (tests/wasm/plugin.c). The .wasm is committed, so the
# tests need no toolchain; this rebuilds it with clang and wasm-ld (clang --target=wasm32 needs no libc).
wasm-fixture:
	clang --target=wasm32 -O2 -nostdlib -fno-builtin -Wall -Wl,--no-entry -Wl,--initial-memory=262144 -Wl,-z,stack-size=16384 -o tests/wasm/plugin.wasm tests/wasm/plugin.c
	cd tov-patches/tests && clang --target=wasm32 -O1 -nostdlib -fno-builtin -Wl,--no-entry -Wl,--export-all -Wl,-z,stack-size=8192 -Wl,--initial-memory=131072 -Wl,--max-memory=1048576 -o wasm_mod.wasm wasm_mod.c

check:
	scripts/check.py src/*.tov src/providers/*.tov tests/*.tov

# the management API spec against the routes a probe gateway serves (needs build/raiju)
openapi-check: build
	python3 tests/openapi_check.py build/raiju

# recount the status column of docs/parity.md and rewrite its Summary table
parity-count:
	python3 scripts/parity_count.py --write

unit:
	$(TOV) test src/main.tov

e2e:
	python3 tests/e2e.py
	RAIJU_SERVER=http1 python3 tests/e2e.py

build/mock_upstream: tests/mock_upstream.tov
	mkdir -p build && $(TOV) build tests/mock_upstream.tov -o build/mock_upstream

# the web UI in headless Chromium against build/raiju (the committed src/ui_assets.tov)
ui: build build/mock_upstream
	NODE_PATH=$$(npm root -g) node tests/ui_e2e.mjs

# The web UI (web/, SolidJS on Vite, built with Bun) is embedded in src/ui_assets.tov, which is
# committed: building the gateway needs no Node. `make web` regenerates the API types from
# docs/openapi/management.yaml, type-checks, builds web/dist and embeds it.
BUN ?= $(or $(shell command -v bun 2>/dev/null),$(HOME)/.bun/bin/bun)

web:
	cd web && $(BUN) install --frozen-lockfile && $(BUN) run gen && $(BUN) run check && $(BUN) run build
	python3 scripts/embed_ui.py

# rebuilds the UI and fails when src/ui_assets.tov or web/src/api/schema.d.ts would change
web-check:
	mkdir -p build && cp web/src/api/schema.d.ts build/schema.d.ts.prev
	cd web && $(BUN) install --frozen-lockfile && $(BUN) run gen && $(BUN) run check && $(BUN) run build
	@cmp -s web/src/api/schema.d.ts build/schema.d.ts.prev || { echo "web/src/api/schema.d.ts is out of date; run make web and commit it" >&2; exit 1; }
	python3 scripts/embed_ui.py --check

test: check unit tov-test e2e ui

run:
	$(TOV) run src/main.tov

bench:
	bench/run.sh
