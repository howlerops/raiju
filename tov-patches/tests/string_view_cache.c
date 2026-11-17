/* Compile with the patched runtime on the include path; no compiler/JSC build needed. */
#define TV_PLAIN_ALLOC
#include "tov.c"
#include <assert.h>

int main(void) {
    const char prefix[] = "data:image/\xe6\x97\xa5;base64";
    tv_str source = tv_str_from(prefix, sizeof(prefix) - 1);
    tv_str semicolon = tv_str_from(";", 1);
    /* The first operation on this newly allocated string is indexOf, not length. */
    assert(tv_str_index_of(source, semicolon) == 12);
    uintptr_t previous = (uintptr_t)source.p;
    tv_str_release(source);
    /* No cached UTF-16 offset may survive the lifetime of its string address. */
    for (int i = 0; i < TV_UVIEWS; i++) assert((uintptr_t)tv_uviews[i].p != previous);

    const char png[] = "data:image/png;base64";
    tv_str next = tv_str_from(png, sizeof(png) - 1);
    tv_int end = tv_str_index_of(next, semicolon);
    assert(end == 14);
    tv_str mime = tv_str_slice(next, 5, end, true, NULL);
    assert(mime.p->len == 9 && memcmp(mime.p->data, "image/png", 9) == 0);
    tv_str_release(mime);
    tv_str_release(next);
    tv_str_release(semicolon);
    puts("string view cache lifetime: ok");
    return 0;
}
