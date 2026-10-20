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
 *
 * Three more config keys switch the other hooks on (all off by default, so a plugin that sets none of them
 * changes nothing the HTTP transport carries):
 *   http   what http_pre_hook and http_post_hook do:
 *            rewrite   pre: replaces "from" with "to" in the request body, sets the x-request-id header to
 *                      "tag" and puts {"http_pre":"ran"} in the context; post: sets the x-wasm-http-post
 *                      header to "tag" (x-wasm-http-ctx tells whether the context from pre arrived) and
 *                      adds "x_http_post":"tag" to a JSON object body
 *            respond   pre: answers the request itself (202, a JSON body, header x-plugin: pre)
 *            error     pre: fails with "http pre refused"
 *            path      pre: moves the request to /v1/models (the host must refuse it)
 *   post   what post_hook adds: error (turns a response into a 429 error), recover (turns an error into
 *          a chat response), chunk (rewrites each stream chunk: "chunk_from" to "chunk_to"), text (the
 *          same, in a whole response as well as in each chunk), skip (drops a stream chunk that contains
 *          "chunk_skip", answering an error with Bifrost's stream_control skip_stream)
 *   count  "on": post_hook also adds "x_post_n", how many whole answers this instance's post_hook has seen
 *   chunk_from, chunk_to, chunk_skip, chunk_stop   http_stream_chunk_hook: replaces chunk_from with
 *          chunk_to in each chunk, drops a chunk that contains chunk_skip, ends the stream on a chunk
 *          that contains chunk_stop. The hook is a pass-through when none is set.
 */

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long long u64;

#define EXPORT(n) __attribute__((export_name(n)))

/* the name the HTTP pre hook is exported under: http_pre_hook, or http_intercept (its older name) when
 * built with -DPRE_NAME='"http_intercept"' (tests/wasm/plugin_intercept.wasm) */
#ifndef PRE_NAME
#define PRE_NAME "http_pre_hook"
#endif

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
static char http[16];
static char postm[16];
static char chunk_from[32];
static char chunk_to[32];
static char chunk_skip[32];
static char chunk_stop[32];
static char count[8];
static int count_on;
static u32 post_calls;

/* a number in decimal */
static void put_num(buf *b, u32 v) {
    char d[12];
    int n = 0;
    do { d[n++] = (char)('0' + v % 10); v /= 10; } while (v > 0);
    while (n > 0) { char c = d[--n]; put(b, &c, 1); }
}

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
    str_of(c, len, "http", http, sizeof http);
    str_of(c, len, "post", postm, sizeof postm);
    str_of(c, len, "chunk_from", chunk_from, sizeof chunk_from);
    str_of(c, len, "chunk_to", chunk_to, sizeof chunk_to);
    str_of(c, len, "chunk_skip", chunk_skip, sizeof chunk_skip);
    str_of(c, len, "chunk_stop", chunk_stop, sizeof chunk_stop);
    str_of(c, len, "count", count, sizeof count);
    count_on = count[0] == 'o' && count[1] == 'n';
    return find((const u8 *)mode, slen(mode), "initfail") == 0 ? 1 : 0;
}

static int same_str(const char *a, const char *b) {
    u32 i = 0;
    while (a[i] && b[i] && a[i] == b[i]) i++;
    return a[i] == 0 && b[i] == 0;
}

static int is(const char *m) { return same_str(mode, m); }
static int is_http(const char *m) { return same_str(http, m); }
static int is_post(const char *m) { return same_str(postm, m); }

/* ---- base64 (the HTTP hooks carry bodies as base64) ---- */

static const char B64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static u32 b64_encode(const u8 *s, u32 n, u8 *out) {
    u32 k = 0;
    for (u32 i = 0; i < n; i += 3) {
        u32 v = (u32)s[i] << 16;
        if (i + 1 < n) v |= (u32)s[i + 1] << 8;
        if (i + 2 < n) v |= (u32)s[i + 2];
        out[k++] = (u8)B64[(v >> 18) & 63];
        out[k++] = (u8)B64[(v >> 12) & 63];
        out[k++] = i + 1 < n ? (u8)B64[(v >> 6) & 63] : '=';
        out[k++] = i + 2 < n ? (u8)B64[v & 63] : '=';
    }
    return k;
}

static int b64_val(u8 c) {
    if (c >= 'A' && c <= 'Z') return c - 'A';
    if (c >= 'a' && c <= 'z') return c - 'a' + 26;
    if (c >= '0' && c <= '9') return c - '0' + 52;
    if (c == '+') return 62;
    if (c == '/') return 63;
    return -1;
}

static u32 b64_decode(const u8 *s, u32 n, u8 *out) {
    u32 k = 0, acc = 0, bits = 0;
    for (u32 i = 0; i < n; i++) {
        int v = b64_val(s[i]);
        if (v < 0) continue;
        acc = (acc << 6) | (u32)v;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out[k++] = (u8)((acc >> bits) & 0xff);
        }
    }
    return k;
}

/* the base64 string value of key in s as [start, end) without its quotes; false when absent */
static int b64_span(const u8 *s, u32 n, const char *key, u32 *start, u32 *end) {
    u32 a, b;
    if (!value_of(s, n, key, &a, &b) || s[a] != '"' || b < a + 2) return 0;
    *start = a + 1;
    *end = b - 1;
    return 1;
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

static void put_object_with(buf *b, const u8 *c, u32 n, const char *member);

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
    u32 rs = 0, re = 0, cs = 0, ce = 0;
    /* the context that came in (from the HTTP hooks, say) is kept, with "pre":"ran" added */
    puts_(&b, "{\"context\":");
    if (value_of(in, len, "context", &cs, &ce)) put_object_with(&b, in + cs, ce - cs, "\"pre\":\"ran\""); else puts_(&b, "{\"pre\":\"ran\"}");
    puts_(&b, ",\"request\":");
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

/* the bytes s[0..n) copied to b, with the first `from` replaced by `to` (nothing replaced when from is empty) */
static void put_replaced(buf *b, const u8 *s, u32 n, const char *from, const char *to) {
    int at = from[0] ? find(s, n, from) : -1;
    if (at < 0) {
        put(b, s, n);
        return;
    }
    put(b, s, (u32)at);
    puts_(b, to);
    u32 skip = (u32)at + slen(from);
    put(b, s + skip, n - skip);
}

/* a JSON object c[0..n) with one more member first: {member, ...rest} */
static void put_object_with(buf *b, const u8 *c, u32 n, const char *member) {
    if (n < 2 || c[0] != '{') {
        puts_(b, "{");
        puts_(b, member);
        puts_(b, "}");
        return;
    }
    puts_(b, "{");
    puts_(b, member);
    u32 i = 1;
    while (i < n && c[i] == ' ') i++;
    if (i < n && c[i] != '}') puts_(b, ",");
    put(b, c + 1, n - 1);
}

static const char CHAT_CHUNK[] = "chat.completion.chunk";

EXPORT("post_hook") u64 plugin_post_hook(u32 ptr, u32 len) {
    const u8 *in = (const u8 *)ptr;
    buf b = new_buf(len * 2 + 4096);
    if (!b.p) return 0;
    if (is("trap")) __builtin_trap();
    u32 cs = 0, ce = 0, rs = 0, re = 0;
    int have_ctx = value_of(in, len, "context", &cs, &ce);
    int ctx_ok = have_ctx && find(in + cs, ce - cs, "\"pre\":\"ran\"") >= 0;
    int input_error = find(in, len, "\"has_error\":true") >= 0;
    /* post=error: a response becomes a 429 error; an error that came in is handed back as it is */
    if (is_post("error") && !input_error) {
        puts_(&b, "{\"context\":");
        if (have_ctx) put(&b, in + cs, ce - cs); else puts_(&b, "{}");
        puts_(&b, ",\"response\":null,\"error\":{\"error\":{\"message\":\"turned into an error by the plugin\",\"type\":\"plugin_error\",\"code\":\"plugin_post\"},\"status_code\":429,\"is_bifrost_error\":false},\"has_error\":true,\"hook_error\":\"\"}");
        return pack(&b);
    }
    /* post=recover: an error that came in becomes a chat response */
    if (is_post("recover") && input_error) {
        puts_(&b, "{\"context\":");
        if (have_ctx) put(&b, in + cs, ce - cs); else puts_(&b, "{}");
        puts_(&b, ",\"response\":{\"chat_response\":");
        puts_(&b, CHAT);
        puts_(&b, "},\"error\":{},\"has_error\":false,\"hook_error\":\"\"}");
        return pack(&b);
    }
    puts_(&b, "{\"context\":");
    if (have_ctx) put(&b, in + cs, ce - cs); else puts_(&b, "{}");
    puts_(&b, ",\"response\":");
    if (input_error) {
        /* an error that is not recovered: handed back as it came */
        u32 es = 0, ee = 0;
        puts_(&b, "null,\"error\":");
        if (value_of(in, len, "error", &es, &ee)) put(&b, in + es, ee - es); else puts_(&b, "{}");
        puts_(&b, ",\"has_error\":true,\"hook_error\":\"\"}");
        return pack(&b);
    }
    if (value_of(in, len, "response", &rs, &re)) {
        int is_chunk = find(in + rs, re - rs, CHAT_CHUNK) >= 0;
        /* post=skip: a stream chunk that contains chunk_skip is dropped (an error with Bifrost's stream_control) */
        if (is_post("skip") && is_chunk && chunk_skip[0] && find(in + rs, re - rs, chunk_skip) >= 0) {
            b.n = 0;
            puts_(&b, "{\"context\":");
            if (have_ctx) put(&b, in + cs, ce - cs); else puts_(&b, "{}");
            puts_(&b, ",\"response\":null,\"error\":{\"error\":{\"message\":\"chunk skipped\"},\"stream_control\":{\"skip_stream\":true}},\"has_error\":true,\"hook_error\":\"\"}");
            return pack(&b);
        }
        if ((is_post("chunk") && is_chunk) || is_post("text")) {
            /* chunk_from becomes chunk_to inside the stream chunk (text: inside a whole response too) */
            put_replaced(&b, in + rs, re - rs, chunk_from, chunk_to);
        } else {
            /* insert the marker as the first field of the object the response holds (":{" opens it) */
            int at = find(in + rs, re - rs, "\":{");
            if (at >= 0) {
                u32 cut = (u32)at + 3;
                put(&b, in + rs, cut);
                puts_(&b, "\"x_wasm_plugin\":\"");
                puts_(&b, ctx_ok ? "ctx-ok" : "ctx-missing");
                puts_(&b, ":");
                puts_(&b, tag);
                puts_(&b, "\",");
                /* count=on: how many whole answers this instance's post_hook has seen */
                if (count_on && !is_chunk) {
                    post_calls++;
                    puts_(&b, "\"x_post_n\":");
                    put_num(&b, post_calls);
                    puts_(&b, ",");
                }
                put(&b, in + rs + cut, re - rs - cut);
            } else {
                put(&b, in + rs, re - rs);
            }
        }
    } else {
        puts_(&b, "null");
    }
    puts_(&b, ",\"error\":{},\"has_error\":false,\"hook_error\":\"\"}");
    return pack(&b);
}

/* ---- the HTTP transport hooks ---- */

static const char RESPOND_BODY[] = "eyJhbnN3ZXJlZCI6ImJ5IHRoZSBwbHVnaW4ifQ==";

EXPORT(PRE_NAME) u64 plugin_http_pre_hook(u32 ptr, u32 len) {
    const u8 *in = (const u8 *)ptr;
    buf b = new_buf(len * 3 + 4096);
    if (!b.p) return 0;
    u32 cs = 0, ce = 0, rs = 0, re = 0;
    int have_ctx = value_of(in, len, "context", &cs, &ce);
    int have_req = value_of(in, len, "request", &rs, &re);
    if (is_http("error")) {
        puts_(&b, "{\"context\":{},\"request\":null,\"response\":null,\"has_response\":false,\"error\":\"http pre refused\"}");
        return pack(&b);
    }
    if (is_http("respond")) {
        puts_(&b, "{\"context\":");
        if (have_ctx) put_object_with(&b, in + cs, ce - cs, "\"http_pre\":\"ran\""); else puts_(&b, "{}");
        puts_(&b, ",\"request\":null,\"response\":{\"status_code\":202,\"headers\":{\"content-type\":\"application/json\",\"x-plugin\":\"pre\"},\"body\":\"");
        puts_(&b, RESPOND_BODY);
        puts_(&b, "\"},\"has_response\":true,\"error\":\"\"}");
        return pack(&b);
    }
    if (is_http("path")) {
        puts_(&b, "{\"context\":{},\"request\":{\"method\":\"POST\",\"path\":\"/v1/models\",\"headers\":{},\"query\":{},\"body\":\"\"},\"response\":null,\"has_response\":false,\"error\":\"\"}");
        return pack(&b);
    }
    puts_(&b, "{\"context\":");
    if (have_ctx) {
        if (is_http("rewrite")) put_object_with(&b, in + cs, ce - cs, "\"http_pre\":\"ran\"");
        else put(&b, in + cs, ce - cs);
    } else {
        puts_(&b, "{}");
    }
    puts_(&b, ",\"request\":");
    if (!have_req) {
        puts_(&b, "null");
    } else if (is_http("rewrite")) {
        u32 hp = 0;
        int h = find(in + rs, re - rs, "\"headers\":{");
        u32 bs = 0, be = 0;
        if (h < 0 || !b64_span(in + rs, re - rs, "body", &bs, &be)) {
            put(&b, in + rs, re - rs);
        } else {
            hp = (u32)h + slen("\"headers\":{");
            /* x-request-id is set: replaced when the request has one already (an earlier plugin's), else added */
            int old = find(in + rs, bs, "\"x-request-id\":\"");
            if (old >= 0) {
                u32 vs = (u32)old + slen("\"x-request-id\":\"");
                u32 ve = vs;
                while (ve < bs && in[rs + ve] != '"') ve++;
                put(&b, in + rs, vs);
                puts_(&b, tag);
                put(&b, in + rs + ve, bs - ve);
            } else {
                put(&b, in + rs, hp);
                puts_(&b, "\"x-request-id\":\"");
                puts_(&b, tag);
                puts_(&b, "\"");
                if (in[rs + hp] != '}') puts_(&b, ",");
                put(&b, in + rs + hp, bs - hp);
            }
            /* the body: decoded, one text replaced, encoded again */
            u8 *raw = (u8 *)plugin_malloc(be - bs + 4);
            u8 *rep = (u8 *)plugin_malloc((be - bs) * 2 + 256);
            u8 *enc = (u8 *)plugin_malloc((be - bs) * 4 + 256);
            if (raw && rep && enc) {
                u32 n = b64_decode(in + rs + bs, be - bs, raw);
                buf t = { rep, 0, (be - bs) * 2 + 256 };
                put_replaced(&t, raw, n, from, to);
                u32 k = b64_encode(t.p, t.n, enc);
                put(&b, enc, k);
            }
            if (raw) plugin_free((u32)raw);
            if (rep) plugin_free((u32)rep);
            if (enc) plugin_free((u32)enc);
            put(&b, in + rs + be, re - rs - be);
        }
    } else {
        put(&b, in + rs, re - rs);
    }
    puts_(&b, ",\"response\":null,\"has_response\":false,\"error\":\"\"}");
    return pack(&b);
}

EXPORT("http_post_hook") u64 plugin_http_post_hook(u32 ptr, u32 len) {
    const u8 *in = (const u8 *)ptr;
    buf b = new_buf(len * 3 + 4096);
    if (!b.p) return 0;
    u32 cs = 0, ce = 0, rs = 0, re = 0;
    int have_ctx = value_of(in, len, "context", &cs, &ce);
    int ctx_ok = have_ctx && find(in + cs, ce - cs, "\"http_pre\":\"ran\"") >= 0;
    puts_(&b, "{\"context\":");
    if (have_ctx) put(&b, in + cs, ce - cs); else puts_(&b, "{}");
    if (is_http("rewrite") && value_of(in, len, "response", &rs, &re)) {
        u32 bs = 0, be = 0;
        puts_(&b, ",\"response\":{\"headers\":{\"x-wasm-http-post\":\"");
        puts_(&b, tag);
        puts_(&b, "\",\"x-wasm-http-ctx\":\"");
        puts_(&b, ctx_ok ? "ok" : "missing");
        puts_(&b, "\"}");
        if (b64_span(in + rs, re - rs, "body", &bs, &be) && be > bs) {
            u8 *raw = (u8 *)plugin_malloc(be - bs + 4);
            u8 *out = (u8 *)plugin_malloc((be - bs) * 2 + 256);
            u8 *enc = (u8 *)plugin_malloc((be - bs) * 4 + 256);
            if (raw && out && enc) {
                u32 n = b64_decode(in + rs + bs, be - bs, raw);
                /* a JSON object body gets a marker member; any other body is left as it is */
                if (n > 0 && raw[0] == '{') {
                    buf t = { out, 0, (be - bs) * 2 + 256 };
                    puts_(&t, "{\"x_http_post\":\"");
                    puts_(&t, tag);
                    puts_(&t, "\"");
                    if (n > 1 && raw[1] != '}') puts_(&t, ",");
                    put(&t, raw + 1, n - 1);
                    u32 k = b64_encode(t.p, t.n, enc);
                    puts_(&b, ",\"body\":\"");
                    put(&b, enc, k);
                    puts_(&b, "\"");
                }
            }
            if (raw) plugin_free((u32)raw);
            if (out) plugin_free((u32)out);
            if (enc) plugin_free((u32)enc);
        }
        puts_(&b, "}");
    }
    puts_(&b, ",\"error\":\"\"}");
    return pack(&b);
}

EXPORT("http_stream_chunk_hook") u64 plugin_http_stream_chunk_hook(u32 ptr, u32 len) {
    const u8 *in = (const u8 *)ptr;
    buf b = new_buf(len * 2 + 4096);
    if (!b.p) return 0;
    u32 cs = 0, ce = 0, ks = 0, ke = 0;
    int have_ctx = value_of(in, len, "context", &cs, &ce);
    int have_chunk = value_of(in, len, "chunk", &ks, &ke);
    puts_(&b, "{\"context\":");
    if (have_ctx) put(&b, in + cs, ce - cs); else puts_(&b, "{}");
    if (!have_chunk) {
        puts_(&b, ",\"chunk\":null,\"has_chunk\":false,\"skip\":false,\"error\":\"\"}");
        return pack(&b);
    }
    if (chunk_skip[0] && find(in + ks, ke - ks, chunk_skip) >= 0) {
        puts_(&b, ",\"chunk\":null,\"has_chunk\":false,\"skip\":true,\"error\":\"\"}");
        return pack(&b);
    }
    if (chunk_stop[0] && find(in + ks, ke - ks, chunk_stop) >= 0) {
        puts_(&b, ",\"chunk\":null,\"has_chunk\":false,\"skip\":false,\"error\":\"chunk blocked by the plugin\"}");
        return pack(&b);
    }
    puts_(&b, ",\"chunk\":");
    put_replaced(&b, in + ks, ke - ks, chunk_from, chunk_to);
    puts_(&b, ",\"has_chunk\":true,\"skip\":false,\"error\":\"\"}");
    return pack(&b);
}

EXPORT("cleanup") int plugin_cleanup(void) { return 0; }
