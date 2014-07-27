#include <string.h>
#include <errno.h>
#include <glib.h>

#define MAX_STRERR_SIZE 256

const char* iop_strerror(int err) {
    char buff[MAX_STRERR_SIZE];
    int saved_errno = errno;
    char *msg = NULL;
    const char *ret;

    strerror_r(err, buff, MAX_STRERR_SIZE);
    buff[MAX_STRERR_SIZE - 1] = '\0';
    // g_intern_string() only works with utf-8 strings
    if (!g_get_charset(NULL))
          msg = g_locale_to_utf8(buff, -1, NULL, NULL, NULL);

    // Put in glib's internal string cache
    ret = g_intern_string(msg);
    g_free(msg);

    errno = saved_errno;
    return ret;
}
