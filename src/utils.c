#include <string.h>
#include <errno.h>
#include <glib.h>

#define MAX_STRERR_SIZE 256

static char *gnu_strerror_r(int error, char *buffer, size_t len) {
    // Check what strerror_r is present and implement accordingly
#if (_POSIX_C_SOURCE >= 200112L || _XOPEN_SOURCE >= 600) && ! _GNU_SOURCE

    if (strerror_r(error, buffer, len) != 0) {
        snprintf(buffer, len, "Unknown error %d", error);
    }

    // XSI version does not promise a terminating zero.
    if (len) {
        buffer[len - 1] = '\0';
    }

    return buffer;
#else
    return strerror_r(error, buffer, len);
#endif
}


const char* iop_strerror(int err) {
    char buff[MAX_STRERR_SIZE];
    int saved_errno = errno;
    char *msg = NULL;
    const char *ret;

    ret = gnu_strerror_r(err, buff, MAX_STRERR_SIZE);
    // g_intern_string() only works with utf-8 strings
    if (!g_get_charset(NULL)) {
        msg = g_locale_to_utf8(ret, -1, NULL, NULL, NULL);
        ret = msg;
    }

    // Put in glib's internal string cache
    ret = g_intern_string(ret);

    if (msg) {
        g_free(msg);
    }

    errno = saved_errno;
    return ret;
}
