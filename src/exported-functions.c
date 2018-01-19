#include "exported-functions.h"

#include <stdio.h>
#include <stdarg.h>
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/stat.h>
#include <string.h>
#include <sys/types.h>
#include <fcntl.h>
#include <glob.h>
#include <sys/statvfs.h>
#include <dirent.h>
#include <inttypes.h>

#include "utils.h"


static void set_error_from_errno(GError** err, GQuark domain, int errcode) {
    g_set_error(err, domain, errcode, "%s", iop_strerror(errcode));
}

static JsonNode* stdApiWrapper(int rv, GError** err) {
    if (rv < 0) {
        set_error_from_errno(err, IOPROCESS_STDAPI_ERROR, errno);
        return JsonNode_newFromBoolean(FALSE);
    }
    return JsonNode_newFromBoolean(TRUE);
}

static JsonNode* safeGetArg(const JsonNode *args, const char* argName,
                            JsonNodeType argType, GError** err) {
    JsonNode* tmp;

    if (!args) {
        g_set_error(err, IOPROCESS_ARGUMENT_ERROR, EINVAL, "args is empty");
        return NULL;
    }

    if (JsonNode_getType(args) != JT_MAP) {
        g_set_error(err, IOPROCESS_ARGUMENT_ERROR,
                    EINVAL, "args must be a map");
        return NULL;
    }

    tmp = JsonNode_map_lookup(args, argName, err);
    if (!tmp) {
        g_set_error(err, IOPROCESS_ARGUMENT_ERROR, EINVAL,
                    "arg '%s' was not found in list", argName);
        return NULL;
    }

    if (JsonNode_getType(tmp) != argType) {
        g_set_error(err, IOPROCESS_ARGUMENT_ERROR,
                    EINVAL, "Param '%s' has the wrong type", argName);
    }
    return tmp;
}

void safeGetArgValue(const JsonNode *args, const char* argName,
                     JsonNodeType argType, void* out, GError** err) {
    GError* tmpError = NULL;
    JsonNode* tmp;

    tmp = safeGetArg(args, argName, argType, &tmpError);
    if (!tmp) {
        g_propagate_error(err, tmpError);
        return;
    }

    JsonNode_getValue(tmp, out);
}

void safeGetArgValues(const JsonNode *args, GError** err,
                      int argn, ...) {
    int i;
    char* argName;
    JsonNodeType argType;
    GError* tmpError = NULL;
    void* out;
    va_list argp;
    va_start(argp, argn);

    for (i = 0; i < argn; i++) {
        argName = va_arg(argp, char*);
        argType = va_arg(argp, JsonNodeType);
        out = va_arg(argp, void*);

        safeGetArgValue(args, argName, argType, out, &tmpError);
        if(tmpError) {
            g_propagate_error(err, tmpError);
            goto end;
        }
    }
end:
    va_end(argp);
}

JsonNode* exp_rename(const JsonNode* args, GError** err) {
    GString* oldpath;
    GString* newpath;
    GError* tmpError = NULL;

    safeGetArgValues(args, &tmpError, 2,
                     "oldpath", JT_STRING, &oldpath,
                     "newpath", JT_STRING, &newpath
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    return stdApiWrapper(rename(oldpath->str, newpath->str), err);
}

/* Used for testing, simply responds "pong" */
JsonNode* exp_ping(
    __attribute__((unused)) const JsonNode* args,
    __attribute__((unused))GError** err) {
    return JsonNode_newFromString("pong");
}

/* Used for testing, returns the memstat. Helps to detect a mem leak */
JsonNode* exp_memstat(
    __attribute__((unused))const JsonNode* args,
    GError** err) {
    uint64_t size;
    uint64_t rss;
    uint64_t shr;
    JsonNode* res = NULL;
    FILE* fd = fopen("/proc/self/statm", "r");
    if (!fd) {
        set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, errno);
        return NULL;
    }

    if (fscanf(fd, "%" PRIu64 " %" PRIu64 " %" PRIu64, &size, &rss, &shr) < 3) {
        g_set_error(err,
                    IOPROCESS_GENERAL_ERROR,
                    EINVAL,
                    "bad statm format");
        goto clean;
    }
    res = JsonNode_newMap();
    JsonNode_map_insert(res, "size", JsonNode_newFromLong(size), NULL);
    JsonNode_map_insert(res, "rss", JsonNode_newFromLong(rss), NULL);
    JsonNode_map_insert(res, "shr", JsonNode_newFromLong(shr), NULL);
clean:
    fclose(fd);
    return res;

}

/* Used for testing, simply crashes the ioprocess */
JsonNode* exp_crash(
    __attribute__((unused))const JsonNode* args,
    __attribute__((unused))GError** err) {
    exit(1);
    return NULL;
}

/* Used for testing, will return contents of args "text" and will sleep */
JsonNode* exp_echo(const JsonNode* args, GError** err) {
    long sleep_sec = 0;
    GError *tmpError = NULL;
    GString* text;
    JsonNode* res;
    safeGetArgValues(args, &tmpError, 2,
                     "text", JT_STRING, &text,
                     "sleep", JT_LONG, &sleep_sec
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    if (sleep_sec > 0) {
        sleep(sleep_sec);
    }

    res = JsonNode_newFromString(text->str);
    return res;
}

JsonNode* exp_unlink(const JsonNode* args, GError** err) {
    GString* path;
    GError* tmpError = NULL;

    safeGetArgValue(args, "path", JT_STRING, (void*)&path, &tmpError);
    if (tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    return stdApiWrapper(unlink(path->str), err);
}

JsonNode* exp_rmdir(const JsonNode* args, GError** err) {
    GString* path;
    GError* tmpError = NULL;

    safeGetArgValue(args, "path", JT_STRING, (void*)&path, &tmpError);
    if (tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    return stdApiWrapper(rmdir(path->str), err);
}

JsonNode* exp_mkdir(const JsonNode* args, GError** err) {
    GError* tmpError = NULL;
    GString* path;
    long mode;

    safeGetArgValues(args, &tmpError, 2,
                     "path", JT_STRING, &path,
                     "mode", JT_LONG, &mode
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    return stdApiWrapper(mkdir(path->str, mode), err);
}

JsonNode* exp_chmod(const JsonNode* args, GError** err) {
    GError* tmpError = NULL;
    GString* path;
    long mode;

    safeGetArgValues(args, &tmpError, 2,
                     "path", JT_STRING, &path,
                     "mode", JT_LONG, &mode
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    return stdApiWrapper(chmod(path->str, mode), err);
}

JsonNode* exp_lexists(const JsonNode* args, GError** err) {
    GError* tmpError = NULL;
    GString* path;
    struct stat st;

    safeGetArgValues(args, &tmpError, 1,
                     "path", JT_STRING, &path
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    if (lstat(path->str, &st) < 0) {
        return JsonNode_newFromBoolean(FALSE);
    }

    return JsonNode_newFromBoolean(TRUE);
}

/* Checks if a path exists with some trick to bypass nfs stale handles */
JsonNode* exp_access(const JsonNode* args, GError** err) {
    GString* path;
    long mode;
    GError* tmpError = NULL;

    safeGetArgValues(args, &tmpError, 2,
                     "path", JT_STRING, &path,
                     "mode", JT_LONG, &mode
                    );

    if (tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    return stdApiWrapper(access(path->str, R_OK), err);
}

JsonNode* exp_touch(const JsonNode* args, GError** err){
    GString* path = NULL;
    int fd = -1, rv = 0;
    long mode;
    long flags;
    long defMode = S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH;
    long allFlags = O_WRONLY | O_CREAT;
    GError* tmpError = NULL;

    safeGetArgValues(args, &tmpError, 3,
                     "path", JT_STRING, &path,
                     "flags", JT_LONG, &flags,
                     "mode", JT_LONG, &mode
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    if (!mode) {
        mode = defMode;
    }

    if (flags) {
        allFlags |= flags;
    }

    fd = open(path->str, allFlags, mode);
    if (fd == -1) {
        rv = fd;
        goto clean;
    }

    rv = futimens(fd, NULL);
    if (rv < 0) {
        goto clean;
    }

clean:
    if (fd != -1) {
        close(fd);
    }
    return stdApiWrapper(rv ,err);
}

JsonNode* exp_truncate(const JsonNode* args, GError** err){
    GString* path = NULL;
    long mode;
    long defMode = S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH;
    long size;
    int fd = -1;
    int excl = 0;
    int flags = O_CREAT | O_WRONLY;
    int rv = 0;
    GError* tmpError = NULL;

    safeGetArgValues(args, &tmpError, 4,
                     "path", JT_STRING, &path,
                     "size", JT_LONG, &size,
                     "mode", JT_LONG, &mode,
                     "excl", JT_BOOLEAN, &excl
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    if (!mode) {
        mode = defMode;
    }

    if (excl) {
        flags |= O_EXCL;
    }

    fd = open(path->str, flags, mode);
    if (fd == -1) {
        rv = fd;
        goto clean;
    }

    rv = ftruncate(fd, size);
    if (rv < 0) {
        goto clean;
    }

clean:
    if (fd != -1) {
        close(fd);
    }
    return stdApiWrapper(rv ,err);
}

JsonNode* exp_link(const JsonNode* args, GError** err) {
    GString* oldpath;
    GString* newpath;
    GError* tmpError = NULL;

    safeGetArgValues(args, &tmpError, 2,
                     "oldpath", JT_STRING, &oldpath,
                     "newpath", JT_STRING, &newpath
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    return stdApiWrapper(link(oldpath->str, newpath->str), err);
}

JsonNode* exp_fsyncPath(const JsonNode* args, GError** err) {
    GString* path;
    GError* tmpError = NULL;
    int fd;

    safeGetArgValues(args, &tmpError, 1,
                     "path", JT_STRING, &path
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    fd = open(path->str, O_RDONLY);
    if (fd == -1) {
        set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, errno);
        return NULL;
    }

    if (fsync(fd) != 0) {
        set_error_from_errno(err, IOPROCESS_STDAPI_ERROR, errno);
    }

    close(fd);
    return NULL;
}

JsonNode* exp_symlink(const JsonNode* args, GError** err) {
    GString* oldpath;
    GString* newpath;
    GError* tmpError = NULL;

    safeGetArgValues(args, &tmpError, 2,
                     "oldpath", JT_STRING, &oldpath,
                     "newpath", JT_STRING, &newpath
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    return stdApiWrapper(symlink(oldpath->str, newpath->str), err);
}

JsonNode* exp_listdir(const JsonNode* args, GError** err) {
    GError* tmpError = NULL;
    GString* path;
    JsonNode* result = NULL;
    DIR *dp;
    char* fname;
    struct dirent *ep;

    safeGetArgValues(args, &tmpError, 1,
                     "path", JT_STRING, &path
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    dp = opendir(path->str);
    if (!dp) {
        set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, errno);
        return NULL;
    }

    result = JsonNode_newArray();

    while ((ep = readdir(dp))) {
        fname = ep->d_name;

        if (strcmp(fname, ".") == 0) {
            continue;
        }

        if (strcmp(fname, "..") == 0) {
            continue;
        }

        JsonNode_array_append(result,
                              JsonNode_newFromString(fname), NULL);
    }

    closedir(dp);
    return result;
}

JsonNode* exp_glob(const JsonNode* args, GError** err) {
    GError* tmpError = NULL;
    GString* pattern;
    JsonNode* result = NULL;
    glob_t globbuf;
    int rv;
    size_t i;

    safeGetArgValues(args, &tmpError, 1,
                     "pattern", JT_STRING, &pattern
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    result = JsonNode_newArray();
    memset(&globbuf, 0, sizeof(glob_t));
    rv = glob(pattern->str, GLOB_DOOFFS, NULL, &globbuf);
    switch (rv) {
    case GLOB_NOSPACE:
        set_error_from_errno(err, IOPROCESS_GENERAL_ERROR,
                             ENOMEM);
        goto clean;
    case GLOB_ABORTED:
        set_error_from_errno(err, IOPROCESS_GENERAL_ERROR,
                             EIO);
        goto clean;
    case GLOB_NOMATCH:
        goto clean;
    }

    for (i = 0; i < globbuf.gl_pathc; i++) {
        JsonNode_array_append(result,
                              JsonNode_newFromString(globbuf.gl_pathv[i]), NULL);
    }

clean:
    globfree(&globbuf);
    return result;
}

JsonNode* exp_writefile(const JsonNode* args, GError** err) {
    GError* tmpError = NULL;
    GString* path;
    GString* dataStr;
    char* data = NULL;
    char* tmpBuff = NULL;
    int direct;
    gsize dataLen;
    int fd = -1;
    int flags = O_WRONLY | O_CREAT | O_TRUNC;
    unsigned long ps = 0;
    int fullBuffSize = -1;
    int rv;
    gsize bwritten;
    unsigned long blocksize = 0;
    struct statvfs svfs;

    safeGetArgValues(args, &tmpError, 3,
                     "path", JT_STRING, &path,
                     "data", JT_STRING, &dataStr,
                     "direct", JT_BOOLEAN, &direct
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    fd = open(path->str, flags,
              S_IRUSR | S_IWUSR |
              S_IRGRP | S_IWGRP |
              S_IROTH);
    if (fd == -1) {
        set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, errno);
        goto clean;
    }

    data = (char*) g_base64_decode(dataStr->str, &dataLen);
    if (direct) {
        if (fstatvfs(fd, &svfs) < 0) {
            set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, errno);
            goto clean;
        }

        blocksize = svfs.f_bsize;
        ps = svfs.f_frsize;

        flags |= O_DIRECT;

        if (dataLen % blocksize == 0) {
            fullBuffSize = dataLen;
        } else {
            fullBuffSize = dataLen + (blocksize - (dataLen % blocksize));
        }

        rv = posix_memalign((void**) &tmpBuff, ps, fullBuffSize);
        if (rv != 0) {
            set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, errno);
            goto clean;
        }

        memcpy(tmpBuff, data, dataLen);
        memset(tmpBuff + dataLen, 0, fullBuffSize - dataLen);
        free(data);
        data = tmpBuff;
        tmpBuff = NULL;
        dataLen = fullBuffSize;
    }

    bwritten = 0;
    while (bwritten < dataLen) {
        rv = write(fd, data + bwritten, dataLen - bwritten);
        if (rv < 0) {
            set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, errno);
            goto clean;
        }
        bwritten += rv;
    }

    if (fsync(fd) != 0) {
        set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, errno);
        goto clean;
    }

clean:
    if (data) {
        free(data);
    }

    if (tmpBuff) {
        free(tmpBuff);
    }

    if (fd != -1) {
        close(fd);
    }

    return NULL;
}

JsonNode* exp_readfile(const JsonNode* args, GError** err) {
    int rv;
    int convertedLen;
    int rd;
    GString* path;
    JsonNode* result = NULL;
    GString* b64str = NULL;
    GError* tmpError = NULL;
    int direct = 0;
    int fd = -1;
    char* buff = NULL;
    int flags = O_RDONLY;
    unsigned long ps = 0;
    unsigned long buffsize = 0;
    int b64buffsize = 0;
    char* b64buff = NULL;
    int b64State = 0;
    int b64Save = 0;
    struct statvfs svfs;


    safeGetArgValues(args, &tmpError, 2,
                     "path", JT_STRING, &path,
                     "direct", JT_BOOLEAN, &direct
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    fd = open(path->str, flags);
    if (fd == -1) {
        set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, errno);
        goto clean;
    }

    if (fstatvfs(fd, &svfs) < 0) {
        set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, errno);
        goto clean;
    }
    buffsize = svfs.f_bsize;
    ps = svfs.f_frsize;
    b64buffsize = (buffsize / 3 + 1) * 4 + 4;

    /* This is only important for direct reads but it doesn't matter if we have
     * it for regular reads as well */
    rv = posix_memalign((void**) &buff, ps, buffsize);
    if (rv != 0) {
        set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, rv);
        goto clean;
    }

    b64buff = malloc(b64buffsize);
    if (!b64buff) {
        set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, errno);
        goto clean;
    }

    if (direct) {
        flags |= O_DIRECT;
    }

    /* We convert to base64 because json strings don't like some chars and I
     * don't blame them */
    b64str = g_string_new(NULL);
    rd = read(fd, buff, buffsize);
    while (rd > 0) {
        if (rd < 0) {
            set_error_from_errno(err, IOPROCESS_GENERAL_ERROR, errno);
            convertedLen = g_base64_encode_close(FALSE, b64buff,
                                                 &b64State, &b64Save);
            goto clean;
        }

        convertedLen = g_base64_encode_step((guchar*) buff, rd, FALSE, b64buff,
                                            &b64State, &b64Save);

        g_string_append_len(b64str, b64buff, convertedLen);

        rd = read(fd, buff, buffsize);
    }

    /* Empty files don't even start an encoder */
    if (b64State || b64Save) {
        convertedLen = g_base64_encode_close(FALSE, b64buff, &b64State, &b64Save);
        g_string_append_len(b64str, b64buff, convertedLen);
    }

    result = JsonNode_newFromString(b64str->str);
clean:
    if (b64buff) {
        free(b64buff);
    }

    if (fd != -1) {
        close(fd);
    }

    if (b64str) {
        g_string_free(b64str, TRUE);
    }

    if (buff) {
        free(buff);
    }

    return result;
}

JsonNode* exp_statvfs(const JsonNode* args, GError** err) {
    struct statvfs st;
    GError* tmpError = NULL;
    GString* path = NULL;
    JsonNode* res = NULL;

    safeGetArgValue(args, "path", JT_STRING, &path, &tmpError);
    if (tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    memset(&st, 0, sizeof(struct statvfs));
    if (statvfs(path->str, &st) < 0) {
        set_error_from_errno(err, IOPROCESS_STDAPI_ERROR, errno);
        goto end;
    }

    res = JsonNode_newMap();
    JsonNode_map_insert(res, "f_bsize", JsonNode_newFromLong(st.f_bsize), NULL);
    JsonNode_map_insert(res, "f_frsize", JsonNode_newFromLong(st.f_frsize), NULL);
    JsonNode_map_insert(res, "f_blocks", JsonNode_newFromLong(st.f_blocks), NULL);
    JsonNode_map_insert(res, "f_bfree", JsonNode_newFromLong(st.f_bfree), NULL);
    JsonNode_map_insert(res, "f_bavail", JsonNode_newFromLong(st.f_bavail), NULL);
    JsonNode_map_insert(res, "f_files", JsonNode_newFromLong(st.f_files), NULL);
    JsonNode_map_insert(res, "f_ffree", JsonNode_newFromLong(st.f_ffree), NULL);
    JsonNode_map_insert(res, "f_favail", JsonNode_newFromLong(st.f_favail), NULL);
    JsonNode_map_insert(res, "f_fsid", JsonNode_newFromLong(st.f_fsid), NULL);
    JsonNode_map_insert(res, "f_flag", JsonNode_newFromLong(st.f_flag), NULL);
    JsonNode_map_insert(res, "f_namemax", JsonNode_newFromDouble(st.f_namemax), NULL);
end:
    return res;
}

JsonNode* exp_stat(const JsonNode* args, GError** err) {
    struct stat st;
    GError* tmpError = NULL;
    GString* path = NULL;
    JsonNode* res = NULL;

    safeGetArgValue(args, "path", JT_STRING, &path, &tmpError);
    if (tmpError) {
        g_propagate_error(err, tmpError);
        return NULL;
    }

    memset(&st, 0, sizeof(struct stat));
    if (stat(path->str, &st) < 0) {
        set_error_from_errno(err, IOPROCESS_STDAPI_ERROR, errno);
        goto end;
    }

    res = JsonNode_newMap();
    JsonNode_map_insert(res, "st_ino", JsonNode_newFromLong(st.st_ino), NULL);
    JsonNode_map_insert(res, "st_dev", JsonNode_newFromLong(st.st_dev), NULL);
    JsonNode_map_insert(res, "st_mode", JsonNode_newFromLong(st.st_mode), NULL);
    JsonNode_map_insert(res, "st_nlink", JsonNode_newFromLong(st.st_nlink), NULL);
    JsonNode_map_insert(res, "st_uid", JsonNode_newFromLong(st.st_uid), NULL);
    JsonNode_map_insert(res, "st_gid", JsonNode_newFromLong(st.st_gid), NULL);
    JsonNode_map_insert(res, "st_size", JsonNode_newFromLong(st.st_size), NULL);
    JsonNode_map_insert(res, "st_atime", JsonNode_newFromDouble(st.st_atime), NULL);
    JsonNode_map_insert(res, "st_mtime", JsonNode_newFromDouble(st.st_mtime), NULL);
    JsonNode_map_insert(res, "st_ctime", JsonNode_newFromDouble(st.st_ctime), NULL);
    JsonNode_map_insert(res, "st_blocks", JsonNode_newFromLong(st.st_blocks), NULL);
end:
    return res;
}

