.PHONY: build test unit e2e ui check run bench

# Tov's async slab allocator corrupts its free lists once ~30 fetches are in
# flight (see docs/tov-notes.md); plain malloc avoids it at the same speed.
export TOV_CFLAGS ?= -DTV_PLAIN_ALLOC

build:
	mkdir -p build && tov build src/main.tov -o build/raiju

check:
	scripts/check.py src/*.tov src/providers/*.tov tests/*.tov

unit:
	tov test src/main.tov

e2e:
	python3 tests/e2e.py

ui:
	NODE_PATH=$$(npm root -g) node tests/ui_e2e.mjs

test: check unit e2e ui

run:
	tov run src/main.tov

bench:
	bench/run.sh
