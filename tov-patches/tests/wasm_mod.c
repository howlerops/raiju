/* The module tov-patches/tests/wasm.tov runs through std/wasm (patch 0005). Plain C with no libc.
 * Build: clang --target=wasm32 -O1 -nostdlib -fno-builtin -Wl,--no-entry -Wl,--export-dynamic \
 *          -Wl,-z,stack-size=8192 -Wl,--initial-memory=131072 -Wl,--max-memory=1048576 -o wasm_mod.wasm wasm_mod.c */

typedef unsigned char u8;
typedef unsigned int u32;
typedef long long i64;

__attribute__((import_module("wasi_snapshot_preview1"), import_name("fd_write")))
extern int fd_write(int fd, const void *iovs, u32 n, u32 *written);

/* an import no host provides: the module still loads, and calling it traps */
__attribute__((import_module("env"), import_name("nope")))
extern int nope(int x);
int call_nope(int x) { return nope(x); }

int add(int a, int b) { return a + b; }
i64 mul64(i64 a, i64 b) { return a * b; }
int divide(int a, int b) { return a / b; }

void fill(u8 *p, u32 n, int v) { for (u32 i = 0; i < n; i++) p[i] = (u8)v; }
int sum(const u8 *p, u32 n) { int s = 0; for (u32 i = 0; i < n; i++) s += p[i]; return s; }

int spin(void) { for (volatile int i = 0;; i++) {} }
void boom(void) { __builtin_trap(); }

/* recursion that the operand stack cannot hold */
int deep(int n) { volatile int pad = n; return n == 0 ? 0 : 1 + deep(n - 1) + (pad - n); }

int grow(int pages) { return (int)__builtin_wasm_memory_grow(0, (u32)pages); }

void say(void) {
    static const char msg[] = "hello from wasm\n";
    struct { const void *p; u32 n; } iov = { msg, sizeof msg - 1 };
    u32 w = 0;
    fd_write(1, &iov, 1, &w);
}
