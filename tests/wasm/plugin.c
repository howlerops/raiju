/* A small plugin for Raiju's WebAssembly plugin tests (Bifrost's JSON ABI: malloc, free, get_name,
 * init, pre_hook, post_hook, cleanup). It is plain C with no libc, compiled to tests/wasm/plugin.wasm
 * by `make wasm-fixture`; the .wasm is committed so the tests need no WebAssembly toolchain.
 *
 * init takes a JSON config; its "mode" picks what the hooks do:
 *   rewrite (default)  pre_hook replaces the config's "from" text with "to" inside the request and
 *                      puts {"pre":"ran"} in the context; post_hook adds "x_wasm_plugin":"<tag>"
 *                      to the chat response, with tag "ctx-ok" when the context from pre_hook arrived
 *   short              pre_hook answers with a chat response of its own (a short circuit)
 *   fail               pre_hook answers with a short-circuit error (status 418)
 *   error              pre_hook returns "error":"plugin said no"
 *   trap               both hooks execute `unreachable`
 *   loop               pre_hook never returns
 *   memory             pre_hook asks for 256 MiB of linear memory and reports whether it got it
 *   print              pre_hook writes a line to standard output (WASI fd_write)
 *   badjson            pre_hook returns text that is not JSON
 *   initfail           init returns 1
 */

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long u64;

#define EXPORT(n) __attribute__((export_name(n)))

__attribute__((import_module("wasi_snapshot_preview1"), import_name("fd_write")))
extern int fd_write(int fd, const void *iovs, u32 n, u32 *written);

extern u8 __heap_base;

/* ---- memory: a bump allocator that starts over when everything is freed ---- */

static u32 bump;
static u32 live;

EXPORT("malloc") u32 plugin_malloc(u32 n) {
    if (bump == 0) bump = (u32)&__heap_base;
    u32 at = (bump + 7u) & ~7u;
    u32 end = at + n;
    if (end < at) return 0;
    u32 have = (u32)__builtin_wasm_memory_size(0) * 65536u;
    if (end > have) {
        u32 more = (end - have + 65535u) / 65536u;
        if (__builtin_wasm_memory_grow(0, more) == (u32)-1) return 0;
    }
    bump = end;
    live++;
    return at;
}

EXPORT("free") void plugin_free(u32 p) {
    (void)p;
    if (live > 0 && --live == 0) bump = 0;
}

/* ---- text helpers ---- */

static u32 slen(const char *s) { u32 n = 0; while (s[n]) n++; return n; }

static int find(const u8 *h, u32 hn, const char *needle) {
    u32 nn = slen(needle);
    if (nn == 0 || nn > hn) return -1;
    for (u32 i = 0; i + nn <= hn; i++) {
        u32 j = 0;
        while (j < nn && h[i + j] == (u8)needle[j]) j++;
        if (j == nn) return (int)i;
    }
    return -1;
}

typedef struct { u8 *p; u32 n, cap; } buf;

static void put(buf *b, const void *s, u32 n) {
    const u8 *q = s;
    for (u32 i = 0; i < n && b->n < b->cap; i++) b->p[b->n++] = q[i];
}
static void puts_(buf *b, const char *s) { put(b, s, slen(s)); }

/* the end of the JSON value that starts at i (strings, nesting) */
static u32 skip_value(const u8 *s, u32 i, u32 n) {
    int depth = 0;
    int str = 0;
    for (; i < n; i++) {
        u8 c = s[i];
        if (str) {
            if (c == '\\') i++;
            else if (c == '"') { str = 0; if (depth == 0) return i + 1; }
            continue;
        }
        if (c == '"') str = 1;
        else if (c == '{' || c == '[') depth++;
        else if (c == '}' || c == ']') { depth--; if (depth <= 0) return i + 1; }
        else if (depth == 0 && (c == ',' || c == '}' || c == ']')) return i;
    }
    return n;
}

/* the value after "key": in s, as [start, end); false when absent */
static int value_of(const u8 *s, u32 n, const char *key, u32 *start, u32 *end) {
    char pat[48];
    u32 k = 0;
    pat[k++] = '"';
    for (const char *q = key; *q && k < 40; q++) pat[k++] = *q;
    pat[k++] = '"';
    pat[k++] = ':';
    pat[k] = 0;
    int at = find(s, n, pat);
    if (at < 0) return 0;
    u32 i = (u32)at + k;
    while (i < n && s[i] == ' ') i++;
    *start = i;
    *end = skip_value(s, i, n);
    return 1;
}

/* a string value without escapes, copied into out (NUL-terminated) */
static int str_of(const u8 *s, u32 n, const char *key, char *out, u32 cap) {
    u32 a, b;
    if (!value_of(s, n, key, &a, &b) || s[a] != '"' || b < a + 2) return 0;
    u32 k = 0;
    for (u32 i = a + 1; i + 1 < b && k + 1 < cap; i++) out[k++] = (char)s[i];
    out[k] = 0;
    return 1;
}

static u64 pack(const buf *b) { return ((u64)(u32)b->p << 32) | b->n; }

static buf new_buf(u32 cap) {
    buf b;
    b.p = (u8 *)plugin_malloc(cap);
    b.n = 0;
    b.cap = b.p ? cap : 0;
    return b;
}

/* ---- the plugin ---- */

static char mode[16] = "rewrite";
static char from[64];
static char to[64];
static char tag[32] = "seen";

EXPORT("get_name") u64 plugin_get_name(void) {
    buf b = new_buf(32);
    puts_(&b, "raiju-test-plugin");
    return pack(&b);
}

EXPORT("init") int plugin_init(u32 ptr, u32 len) {
    const u8 *c = (const u8 *)ptr;
    str_of(c, len, "mode", mode, sizeof mode);
    str_of(c, len, "from", from, sizeof from);
    str_of(c, len, "to", to, sizeof to);
    str_of(c, len, "tag", tag, sizeof tag);
    return find((const u8 *)mode, slen(mode), "initfail") == 0 ? 1 : 0;
}

static int is(const char *m) {
    u32 i = 0;
    while (mode[i] && m[i] && mode[i] == m[i]) i++;
    return mode[i] == 0 && m[i] == 0;
}

static const char CHAT[] =
    "{\"id\":\"wasm-1\",\"object\":\"chat.completion\",\"created\":1,\"model\":\"wasm-model\","
    "\"choices\":[{\"index\":0,\"message\":{\"role\":\"assistant\",\"content\":\"from the plugin\"},\"finish_reason\":\"stop\"}],"
    "\"usage\":{\"prompt_tokens\":1,\"completion_tokens\":2,\"total_tokens\":3}}";

/* a trap while this much of the module's own stack is in use: the stack pointer is not restored,
 * so a host that kept calling the same instance would run out of stack after a few traps */
static void trap_deep(void) {
    volatile char pad[2048];
    pad[0] = 1;
    __builtin_trap();
}

EXPORT("pre_hook") u64 plugin_pre_hook(u32 ptr, u32 len) {
    const u8 *in = (const u8 *)ptr;
    buf b = new_buf(len * 2 + 4096);
    if (!b.p) return 0;
    if (is("trap")) trap_deep();
    if (is("loop")) { for (volatile u32 i = 0;; i++) {} }
    if (is("badjson")) { puts_(&b, "this is not json"); return pack(&b); }
    if (is("print")) {
        static const char msg[] = "hello from the plugin\n";
        struct { const void *p; u32 n; } iov = { msg, sizeof msg - 1 };
        u32 w = 0;
        fd_write(1, &iov, 1, &w);
    }
    if (is("memory")) {
        u32 got = __builtin_wasm_memory_grow(0, 4096);
        puts_(&b, "{\"context\":{},\"request\":null,\"short_circuit\":null,\"has_short_circuit\":false,\"error\":\"");
        puts_(&b, got == (u32)-1 ? "grow denied" : "grow allowed");
        puts_(&b, "\"}");
        return pack(&b);
    }
    if (is("error")) {
        puts_(&b, "{\"context\":{},\"request\":null,\"short_circuit\":null,\"has_short_circuit\":false,\"error\":\"plugin said no\"}");
        return pack(&b);
    }
    if (is("short")) {
        puts_(&b, "{\"context\":{\"pre\":\"ran\"},\"request\":null,\"short_circuit\":{\"response\":{\"chat_response\":");
        puts_(&b, CHAT);
        puts_(&b, "}},\"has_short_circuit\":true,\"error\":\"\"}");
        return pack(&b);
    }
    if (is("fail")) {
        puts_(&b, "{\"context\":{},\"request\":null,\"short_circuit\":{\"error\":{\"error\":{\"message\":\"blocked by the plugin\",\"type\":\"policy_error\",\"code\":\"plugin_blocked\"},\"status_code\":418}},\"has_short_circuit\":true,\"error\":\"\"}");
        return pack(&b);
    }
    /* rewrite: copy the request, replacing the first "from" with "to" */
    u32 rs = 0, re = 0;
    puts_(&b, "{\"context\":{\"pre\":\"ran\"},\"request\":");
    if (value_of(in, len, "request", &rs, &re)) {
        int at = from[0] ? find(in + rs, re - rs, from) : -1;
        if (at < 0) {
            put(&b, in + rs, re - rs);
        } else {
            put(&b, in + rs, (u32)at);
            puts_(&b, to);
            u32 skip = (u32)at + slen(from);
            put(&b, in + rs + skip, re - rs - skip);
        }
    } else {
        puts_(&b, "null");
    }
    puts_(&b, ",\"short_circuit\":null,\"has_short_circuit\":false,\"error\":\"\"}");
    return pack(&b);
}

EXPORT("post_hook") u64 plugin_post_hook(u32 ptr, u32 len) {
    const u8 *in = (const u8 *)ptr;
    buf b = new_buf(len * 2 + 4096);
    if (!b.p) return 0;
    if (is("trap")) __builtin_trap();
    u32 cs = 0, ce = 0, rs = 0, re = 0;
    int have_ctx = value_of(in, len, "context", &cs, &ce);
    int ctx_ok = have_ctx && find(in + cs, ce - cs, "\"pre\":\"ran\"") >= 0;
    puts_(&b, "{\"context\":");
    if (have_ctx) put(&b, in + cs, ce - cs); else puts_(&b, "{}");
    puts_(&b, ",\"response\":");
    if (value_of(in, len, "response", &rs, &re)) {
        /* insert the marker as the first field of the chat response object */
        int at = find(in + rs, re - rs, "\"chat_response\":{");
        if (at >= 0) {
            u32 cut = (u32)at + slen("\"chat_response\":{");
            put(&b, in + rs, cut);
            puts_(&b, "\"x_wasm_plugin\":\"");
            puts_(&b, ctx_ok ? "ctx-ok" : "ctx-missing");
            puts_(&b, ":");
            puts_(&b, tag);
            puts_(&b, "\",");
            put(&b, in + rs + cut, re - rs - cut);
        } else {
            put(&b, in + rs, re - rs);
        }
    } else {
        puts_(&b, "null");
    }
    puts_(&b, ",\"error\":{},\"has_error\":false,\"hook_error\":\"\"}");
    return pack(&b);
}

EXPORT("cleanup") int plugin_cleanup(void) { return 0; }
