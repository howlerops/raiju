/* Test-only WebKitGTK interposer: exercise the real memory-pressure constructor and a full GC
 * from the GLib context pumped by Tov. No engine initialization or substitute GC is provided here. */
#define _GNU_SOURCE 1
#include <JavaScriptCore/JavaScript.h>
#include <glib.h>
#include <dlfcn.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>

extern void *wtf_memory_pressure(void) __asm__("_ZN3WTF21MemoryPressureHandler9singletonEv");
extern void *wtf_main_runloop(void) __asm__("_ZN3WTF7RunLoop13mainSingletonEv");
extern void *wtf_current_runloop(void) __asm__("_ZN3WTF7RunLoop16currentSingletonEv");
extern bool wtf_is_main_thread(void) __asm__("_ZN3WTF12isMainThreadEv");
extern void JSSynchronousGarbageCollectForDebugging(JSContextRef);

static gboolean collect(gpointer data) {
    if (!wtf_is_main_thread() || wtf_main_runloop() != wtf_current_runloop()
        || !g_main_context_is_owner(g_main_context_get_thread_default())) {
        fputs("FAIL WebKitGTK collection ran on the wrong loop/thread\n", stdout);
        exit(1);
    }
    JSSynchronousGarbageCollectForDebugging((JSContextRef)data);
    puts("ok WebKitGTK memory-pressure singleton and real full GC on the program loop");
    return G_SOURCE_REMOVE;
}

JSGlobalContextRef JSGlobalContextCreate(JSClassRef global_class) {
    JSGlobalContextRef (*create)(JSClassRef) = dlsym(RTLD_NEXT, "JSGlobalContextCreate");
    if (!create) {
        fputs("FAIL WebKitGTK context constructor unavailable\n", stdout);
        exit(1);
    }
    JSGlobalContextRef context = create(global_class);
    /* Before patch 0025 this takes the production crash path: the real constructor dereferences
     * the uninitialized RunLoop::mainSingleton. Do not initialize it in the probe. */
    (void)wtf_memory_pressure();
    GMainContext *loop = g_main_context_get_thread_default();
    if (!loop || !wtf_is_main_thread() || wtf_main_runloop() != wtf_current_runloop()) {
        fputs("FAIL WebKitGTK main runloop was not initialized by Tov\n", stdout);
        exit(1);
    }
    GSource *timer = g_timeout_source_new(20);
    g_source_set_callback(timer, collect, (gpointer)context, NULL);
    g_source_attach(timer, loop);
    g_source_unref(timer);
    return context;
}
