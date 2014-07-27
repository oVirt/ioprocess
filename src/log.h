#ifndef __IOPROCESS_LOG_H__
#define __IOPROCESS_LOG_H__

#include <glib.h>

extern gboolean TRACE_ENABLED;

#define g_trace(...) \
    if (TRACE_ENABLED) { g_debug(__VA_ARGS__); }

#endif

