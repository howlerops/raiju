/* Force a real collection before workers start, then report completed idle collections.
 * A copied VM deterministically waits for its vanished collector; no substitute GC or fork hook. */
#define _GNU_SOURCE 1
#include <JavaScriptCore/JavaScript.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

void JSSynchronousGarbageCollectForDebugging(JSContextRef context) {
    void (*collect)(JSContextRef) = dlsym(RTLD_NEXT, "JSSynchronousGarbageCollectForDebugging");
    if (!collect) abort();
    collect(context);
    printf("collected %ld\n", (long)getpid());
    fflush(stdout);
}

JSGlobalContextRef JSGlobalContextCreate(JSClassRef global_class) {
    JSGlobalContextRef (*create)(JSClassRef) = dlsym(RTLD_NEXT, "JSGlobalContextCreate");
    if (!create) abort();
    JSGlobalContextRef context = create(global_class);
    JSSynchronousGarbageCollectForDebugging(context);
    return context;
}
