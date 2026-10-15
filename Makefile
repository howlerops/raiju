.PHONY: build test unit e2e ui check openapi-check run bench tov tov-test

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

check:
	scripts/check.py src/*.tov src/providers/*.tov tests/*.tov

# the management API spec against the routes a probe gateway serves (needs build/raiju)
openapi-check: build
	python3 tests/openapi_check.py build/raiju

unit:
	$(TOV) test src/main.tov

e2e:
	python3 tests/e2e.py
	RAIJU_SERVER=http1 python3 tests/e2e.py

ui:
	NODE_PATH=$$(npm root -g) node tests/ui_e2e.mjs

test: check unit tov-test e2e ui

run:
	$(TOV) run src/main.tov

bench:
	bench/run.sh
