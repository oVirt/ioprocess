#include <sys/types.h>
#include <sys/stat.h>
#include <dirent.h>
#include <glib.h>
#include <errno.h>
#include <string.h>
#include <unistd.h>
#include <stdio.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <inttypes.h>

#include "log.h"
#include "utils.h"

#include "json-dom.h"
#include "json-dom-generator.h"
#include "json-dom-parser.h"

#include "exported-functions.h"
#include <limits.h>

#define IOPROCESS_COMMUNICATION_ERROR \
    g_quark_from_static_string("ioprocess-general-error")

static int READ_PIPE_FD = -1;
static int WRITE_PIPE_FD = -1;
static int MAX_THREADS = 0;
static int MAX_QUEUED_REQUESTS = -1;
static gboolean KEEP_FDS = FALSE;
gboolean TRACE_ENABLED = FALSE;

/* Because g_async_queue_push can't take null */
static int stop_value;
#define STOP_PTR ((gpointer) &stop_value)

static GAsyncQueue *logger_queue;

static inline void stop_request_reader(void) {
    if (READ_PIPE_FD != -1) {
        close(READ_PIPE_FD);
        READ_PIPE_FD = -1;
    }
}

static GOptionEntry entries[] = {
    {
        "read-pipe-fd", 'r', G_OPTION_FLAG_IN_MAIN, G_OPTION_ARG_INT,
        &READ_PIPE_FD, "The pipe FD used to get commands from VDSM", "IN_FD"
    },
    {
        "write-pipe-fd", 'w', G_OPTION_FLAG_IN_MAIN, G_OPTION_ARG_INT,
        &WRITE_PIPE_FD, "The pipe FD used to send results back to VDSM", "OUT_FD"
    },
    {
        "max-threads", 't', G_OPTION_FLAG_IN_MAIN, G_OPTION_ARG_INT,
        &MAX_THREADS, "Max threads to be used, 0 for unlimited", "MAX_THREADS"
    },
    {
        "max-queued-requests", 'q', G_OPTION_FLAG_IN_MAIN, G_OPTION_ARG_INT,
        &MAX_QUEUED_REQUESTS, "Max requests to be queued, -1 for unlimited", "MAX_QUEUED_REQUESTS"
    },
    {
        "keep-fds", '\0', G_OPTION_FLAG_IN_MAIN, G_OPTION_ARG_NONE,
        &KEEP_FDS, "Don't close inherited file discriptors when starting", NULL
    },
    {
        "trace-enabled", '\0', G_OPTION_FLAG_IN_MAIN, G_OPTION_ARG_NONE,
        &TRACE_ENABLED, "Enable trace debugging", NULL
    },
    { NULL }
};

static GError *new_thread_result(int rv) {
    if (rv == 0) {
        return NULL;
    } else {
        return g_error_new(
                   IOPROCESS_COMMUNICATION_ERROR,
                   rv,
                   "%s",
                   iop_strerror(rv));
    }
}


static GThread *create_thread(__attribute__((unused)) const gchar *name,
                              GThreadFunc func,
                              gpointer data,
                              __attribute__((unused)) gboolean joinable) {
#if GLIB_CHECK_VERSION(2, 32, 0)
    return g_thread_new(name, func, data);
#else
    return g_thread_create(func, data, joinable, NULL);
#endif
}

/* A log function that makes output easy to parse */
static void logfunc(const gchar *log_domain, GLogLevelFlags log_level,
                    const gchar *message, gpointer user_data) {
    static const char *format = "%s|%s|%s\n";
    GAsyncQueue *queue = (GAsyncQueue *) user_data;
    const char *levelStr = NULL;
    size_t buff_size = -1;
    char *buff = NULL;
    switch(log_level) {
    case G_LOG_LEVEL_WARNING:
        levelStr = "WARNING";
        break;
    case G_LOG_LEVEL_DEBUG:
        levelStr = "DEBUG";
        break;
    case G_LOG_LEVEL_MESSAGE:
    case G_LOG_LEVEL_INFO:
        levelStr = "INFO";
        break;
    default:
        levelStr = "ERROR";
    }

    buff_size = snprintf(NULL, 0, format, levelStr, log_domain, message);
    buff = malloc(buff_size + 1);
    if (buff) {
        // if we can't allocated the buffer we can't really log
        snprintf(buff, buff_size + 1, format, levelStr, log_domain, message);
        g_async_queue_push(queue, buff);
    }
}

static void *logWriter(void *data) {
    FILE *stream = (FILE *) data;
    size_t nchars = -1;
    size_t n_written = -1;
    char *text = NULL;

    while (!feof(stream) && !ferror(stream)) {
        if (n_written == nchars) {
            if (text) {
                free(text);
                text = NULL;
            }
            text = (char*) g_async_queue_pop(logger_queue);
            n_written = 0;
            nchars = strlen(text);
        } else {
            n_written += fwrite(
                text + n_written,
                sizeof(char),
                nchars - n_written,
                stream
            );
        }
    }

    if (text) {
        free(text);
    }

    return NULL;
}



static ExportedFunctionEntry exportedFunctions[] = {
    /* testing commands */
    { "ping", exp_ping },
    { "echo", exp_echo },
    { "memstat", exp_memstat },
    { "crash", exp_crash },
    /* exported commands */
    { "stat", exp_stat },
    { "lstat", exp_lstat },
    { "statvfs", exp_statvfs },
    { "access", exp_access },
    { "rename", exp_rename },
    { "unlink", exp_unlink },
    { "rmdir", exp_rmdir },
    { "link", exp_link },
    { "symlink", exp_symlink },
    { "chmod", exp_chmod },
    { "readfile", exp_readfile },
    { "glob", exp_glob },
    { "listdir", exp_listdir },
    { "writefile", exp_writefile },
    { "lexists", exp_lexists },
    { "truncate", exp_truncate },
    { "mkdir", exp_mkdir },
    { "fsyncPath", exp_fsyncPath },
    { "touch", exp_touch },
    { "probe_block_size", exp_probe_block_size },
    { NULL, NULL }
};

/* Close FDs that you got from fork but you don't need.
 * whitelist is an array that ends with a -1 */
static int closeUnrelatedFDs(int whitelist[]) {
    DIR *dp;
    int dfd;
    struct dirent *ep;
    char *fname;
    int fdNum = -1;
    int i;
    int closeFlag = FALSE;

    char fullPath[PATH_MAX];
    char filePath[PATH_MAX];
    ssize_t len;

    /* I use fdopendir so I know what the fd number is so I don't close it mid
     * operation */
    dfd = open("/proc/self/fd/", O_RDONLY);
    if (dfd == -1) {
        g_warning("Could not open proc fd dir: %s", iop_strerror(errno));
        return -errno;
    }

    dp = fdopendir(dfd);
    if (dp == NULL) {
        g_warning("Could not get directory pointer: %s", iop_strerror(errno));
        return -errno;
    }

    while ((ep = readdir(dp))) {
        fname = ep->d_name;

        if (strcmp(fname, ".") == 0) {
            continue;
        }

        if (strcmp(fname, "..") == 0) {
            continue;
        }

        if(sscanf(fname, "%d", &fdNum) < 1) {
            g_warning("File '%s' is not an FD representation: %s",
                      fname, iop_strerror(errno));
            continue;
        }

        if (fdNum == dfd) {
            g_trace("Not closing FD %d because it's the directory fd", fdNum);
            continue;
        }

        if (whitelist != NULL) {
            closeFlag = FALSE;
            for (i = 0; whitelist[i] != -1; i++) {
                if (fdNum == whitelist[i]) {
                    g_trace("Not closing FD %d because it's in whitelist",
                            fdNum);
                    closeFlag = TRUE;
                    break;
                }
            }

            if (closeFlag) {
                continue;
            }
        }

        sprintf(fullPath, "/proc/self/fd/%s", fname);

        len = readlink(fullPath, filePath, PATH_MAX - 1);
        if (len < 0)
            strcpy(filePath, "(error)");
        else
            filePath[len] = '\0';

        g_trace("Closing unrelated fd no: %s (%s)", fname, filePath);
        if (close(fdNum) < 0) {
            switch (errno) {
            case EBADF:
                continue;
            }
            g_warning("Could not close fd %d: %s", fdNum, iop_strerror(errno));
            return -errno;
        }
    }

    closedir(dp);

    return 0;
}

static int parseCmdLine(int argc, char *argv[]) {
    GError *error = NULL;
    GOptionContext *context;
    int rv = 0;

    context = g_option_context_new ("- process to perform risky IO");
    g_option_context_add_main_entries (context, entries, NULL);

    if (!g_option_context_parse (context, &argc, &argv, &error)) {
        g_print("option parsing failed: %s\n", error->message);
        rv = -1;
        goto clean;
    }

    if (READ_PIPE_FD < 0 || WRITE_PIPE_FD < 0) {
        g_print("option 'read-pipe-fd' and 'write-pipe-fd' are mandatory\n");
        rv = -1;
        goto clean;
    }

    if (MAX_THREADS < 0) {
      g_print("option 'max-threads' cannot be negative\n");
      rv = -1;
      goto clean;
    }

    if (MAX_QUEUED_REQUESTS >=0 && MAX_THREADS == 0) {
      g_print("option 'max-queued-requests' only works when a the thread pool "
              "has been capped\n");
      rv = -1;
      goto clean;
    }

clean:
    g_option_context_free(context);

    return rv;
}

static ExportedFunction getCallback(const char *methodName) {
    int i;
    for (i = 0; exportedFunctions[i].name != NULL; i++) {
        if (strcmp(exportedFunctions[i].name, methodName) != 0) {
            continue;
        }

        return exportedFunctions[i].callback;
    }

    return NULL;
}

static void extractRequestInfo(const JsonNode *reqInfo, char **methodName,
                               long *reqId, JsonNode **args, GError **err) {
    GError *tmpError = NULL;
    GString *methodNameStr;

    safeGetArgValues(reqInfo, &tmpError, 2,
                     "id", JT_LONG, reqId,
                     "methodName", JT_STRING, &methodNameStr
                    );

    if(tmpError) {
        g_propagate_error(err, tmpError);
        return;
    }

    *methodName = g_strdup(methodNameStr->str);

    *args = JsonNode_map_lookup(reqInfo, "args", NULL);

    return;
}

static JsonNode *buildResponse(long id, const GError *err, JsonNode *result) {
    int errcode = 0;
    const char *errstr = "SUCCESS";
    JsonNode *resp;

    if (err) {
        errcode = err->code;
        errstr = err->message;
    }
    if (result == NULL) {
        result = JsonNode_newMap();
    }

    resp = JsonNode_newMap();
    JsonNode_map_insert(resp, "id", JsonNode_newFromLong(id), NULL);
    JsonNode_map_insert(resp, "errcode", JsonNode_newFromLong(errcode), NULL);
    JsonNode_map_insert(resp, "errstr", JsonNode_newFromString(errstr), NULL);
    JsonNode_map_insert(resp, "result", result, NULL);
    return resp;
}

struct IOProcessCtx_t {
    GAsyncQueue *requestQueue;
    GAsyncQueue *responseQueue;
    int readPipe;
    int writePipe;
};
typedef struct IOProcessCtx_t IOProcessCtx;

struct RequestParams {
    gint64 reqTime;
    JsonNode *reqObj;
    GAsyncQueue *responseQueue;
};

static void servQueueFull(struct RequestParams *params) {
    GError *gerr = NULL;
    JsonNode *response = NULL;
    long reqId = -1;
    GAsyncQueue *responseQueue = params->responseQueue;
    safeGetArgValues(params->reqObj, NULL, 1,
         "id", JT_LONG, &reqId
    );

    g_warning("(%li) Request queue full", reqId);
    g_set_error(&gerr,
        IOPROCESS_GENERAL_ERROR,
        EAGAIN, "%s", iop_strerror(EAGAIN)
    );

    response = buildResponse(reqId, gerr, NULL);
    if (!response) {
        g_warning("(%li) Could not build response object", reqId);
        goto clean;
    }

    g_async_queue_push(responseQueue, response);
clean:
    if (gerr) {
        g_error_free(gerr);
    }
}

static void servRequest(void *data, void *queueSlotsLeft) {
    ExportedFunction callback;
    struct RequestParams *params = (struct RequestParams *) data;
    char *methodName = NULL;
    GError *err = NULL;
    long reqId = -1;
    JsonNode *reqInfo = params->reqObj;
    GAsyncQueue *responseQueue = params->responseQueue;
    JsonNode *args = NULL;
    JsonNode *response;
    JsonNode *result = NULL;
    gint64 startTime;

    g_trace("Extracting request information...");
    extractRequestInfo(reqInfo, &methodName, &reqId, &args, &err);
    if (err) {
        g_warning("Could not extract params: %s", err->message);
        goto clean;
    }


    g_trace("(%li) Finding callback '%s'...", reqId, methodName);
    callback = getCallback(methodName);
    if (!callback) {
        err = g_error_new(0, EINVAL,
                          "No such method '%s'", methodName);
        goto respond;
    }

    startTime = g_get_monotonic_time();

    g_debug("(%li) Start request for method '%s' (waitTime=%" PRId64 ")",
            reqId, methodName, startTime - params->reqTime);

    result = callback(args, &err);

    g_debug("(%li) Finished request for method '%s' (runTime=%" PRId64 ")",
            reqId, methodName, g_get_monotonic_time() - startTime);

respond:
    g_trace("(%li) Building response", reqId);

    if (!result) {
        result = JsonNode_newMap();
    }

    response = buildResponse(reqId, err, result);
    if (!response) {
        g_warning("(%li) Could not build response object", reqId);
        goto clean;
    }

    g_trace("(%li) Queuing response", reqId);
    g_async_queue_push(responseQueue, response);

clean:
    free(params);

    if (methodName) {
        free(methodName);
    }

    if (err) {
        g_error_free(err);
    }

    JsonNode_free(reqInfo);
    if (MAX_QUEUED_REQUESTS >= 0) {
        g_atomic_int_inc((gint*) queueSlotsLeft);
        g_debug("(%li) Dequeuing request (slotsLeft=%i)", reqId,
                *(gint*)queueSlotsLeft);
    }
}

static void *requestHandler(void *data) {
    gint queueSlotsLeft = MAX_THREADS + MAX_QUEUED_REQUESTS + 1;
    IOProcessCtx *ctx = (IOProcessCtx *) data;
    GAsyncQueue *requestQueue = ctx->requestQueue;
    GAsyncQueue *responseQueue = ctx->responseQueue;
    JsonNode *reqObj;
    GError *gerr = NULL;
    GThreadPool *threadPool;
    struct RequestParams *reqParams;
    int err = 0;

    threadPool = g_thread_pool_new(servRequest, /* entry point */
                                   /* pool specific user data */
                                   &queueSlotsLeft,
                                   /* max threads, -1 for unlimited */
                                   (!MAX_THREADS) ? -1 : MAX_THREADS,
                                   /* don't create immediately,
                                      share with others */
                                   FALSE,
                                   &gerr);
    if (gerr) {
      g_warning("%s", gerr->message);
      err = gerr->code;
      g_error_free(gerr);
      gerr = NULL;
      return new_thread_result(err);
    }

    while (TRUE) {
        GError *gerr = NULL;
        reqObj = (JsonNode *) g_async_queue_pop(requestQueue);
        /* Check if we're stopping */
        if (reqObj == STOP_PTR) {
            err = 0;
            break;
        }

        reqParams = malloc(sizeof(struct RequestParams));
        if (!reqParams) {
            g_warning("Could not allocate request params");
            err = ENOMEM;
            break;
        }
        reqParams->reqTime = g_get_monotonic_time();
        reqParams->reqObj = reqObj;
        reqParams->responseQueue = responseQueue;

        if (MAX_QUEUED_REQUESTS >= 0 &&
            g_atomic_int_dec_and_test(&queueSlotsLeft)) {
            servQueueFull(reqParams);
            g_atomic_int_inc(&queueSlotsLeft);
        } else {
            /* TODO: log request id */
            g_debug("Queuing request (slotsLeft=%i)", queueSlotsLeft);

            g_thread_pool_push(threadPool, reqParams, &gerr);
            if (gerr) {
                    g_warning("%s", gerr->message);
                    err = gerr->code;
                    g_error_free(gerr);
                    gerr = NULL;
                    break;
            }
        }
    }

    /* Initiate shutdown by not accepting any more requests. */
    stop_request_reader();

    /* Flush the thread pool */
    g_thread_pool_free(threadPool, FALSE, TRUE);

    /* Push null to responseQueue to signal we're done */
    g_async_queue_push(responseQueue, STOP_PTR);

    return new_thread_result(err);
}

static void *responseWriter(void *data) {
    IOProcessCtx *ctx = (IOProcessCtx *) data;
    int writePipe = ctx->writePipe;
    GAsyncQueue *responseQueue = ctx->responseQueue;
    uint64_t bytesWritten = 0;
    uint64_t bufflen = 0;
    JsonNode *responseObj;
    int n;
    char *buffer = NULL;
    void *ret = NULL;

    while (TRUE) {
            if (bytesWritten == bufflen) {
                if (buffer) {
                    free(buffer);
                }

                responseObj = (JsonNode *) g_async_queue_pop(responseQueue);
                if (responseObj == STOP_PTR) {
                    g_message("responseWriter received stop request, "
                            "terminating\n");
                    break;
                }
                g_trace("Generating json...");
                buffer = jdGenerator_generate(responseObj, &bufflen);
                JsonNode_free(responseObj);
                if (!buffer) {
                    g_warning("Could not allocate response buffer");
                    ret = new_thread_result(EINVAL);
                    break;
            }

            g_trace("Sending response sized %" PRIu64, bufflen);

            if (write(writePipe, &bufflen, sizeof(uint64_t)) < 0) {
                g_warning("Could not write to pipe: %s", iop_strerror(errno));
                ret = new_thread_result(errno);
                break;
            }
            bytesWritten = 0;
        }

        n = write(writePipe, buffer + bytesWritten, bufflen - bytesWritten);
        if (n <= 0) {
            if (errno == EAGAIN) {
                continue;
            }

            g_warning("Could not write to pipe: %s", iop_strerror(errno));
            ret = new_thread_result(errno);
            break;
        }

        bytesWritten += n;
    }

    /* Stop request reading, and close the pipe as we won't use it anymore
     * anyway */
    if (ret) {
        stop_request_reader();
    }
    close(WRITE_PIPE_FD);

    return ret;
}

static void *requestReader(void *data) {
    IOProcessCtx *ctx = (IOProcessCtx *) data;
    int readPipe = ctx->readPipe;
    GAsyncQueue *requestQueue = ctx->requestQueue;
    uint64_t bytesPending = 0;
    uint64_t reqSize = 0;
    int rv = 0;
    char *buffer = NULL;
    JsonNode *requestObj = NULL;
    GError *err = NULL;

    while (TRUE) {
        if (bytesPending == 0) {
            g_trace("Waiting for next request...");
            rv = read(readPipe, &reqSize, sizeof(reqSize));
            g_trace("Receiving request...");
            if (rv < 0) {
                g_warning("Could not read request size: %s", iop_strerror(errno));
                rv = errno;
                goto done;
            }

            g_trace("Message size is %" PRIu64, reqSize);
            buffer = malloc(reqSize + 1);
            if (!buffer) {
                g_warning("Could not allocate request buffer: %s",
                          iop_strerror(errno));

                rv = errno;
                goto done;
            }

            memset(buffer, 0, reqSize + 1);
            bytesPending = reqSize;
        }

        rv = read(readPipe, buffer + (reqSize - bytesPending),
                  bytesPending);
        if (rv < 0) {
            g_warning("Could not read from pipe: %s", iop_strerror(errno));
            rv = errno;
            goto done;
        } else if (rv == 0) {
            g_warning("Pipe closed");
            rv = EPIPE;
            goto done;
        }

        bytesPending -= rv;
        if (bytesPending == 0) {
            g_trace("Marshaling message...");
            err = NULL;
            requestObj = jdParser_buildDom(buffer, reqSize, &err);
            if (!requestObj) {
                g_warning("Could not parse request '%s': %s", buffer, err->message);
                g_error_free(err);
                rv = EINVAL;
                goto done;
            }

            free(buffer);
            buffer = NULL;

            g_trace("Queuing request...");
            g_async_queue_push(requestQueue, requestObj);
        }
    }
done:
    if (buffer) {
        free(buffer);
    }

    /* End of requests to requestHandler */
    g_async_queue_push(requestQueue, STOP_PTR);

    return new_thread_result(rv);
}

static int communicate(int readPipe, int writePipe) {
    int rv = 0;
    GThread *requestReaderThread = NULL;
    GThread *responseWriterThread = NULL;
    GThread *requestHandlerThread = NULL;
    IOProcessCtx ctx;

    ctx.readPipe = readPipe;
    ctx.writePipe = writePipe;
    ctx.requestQueue = g_async_queue_new();
    ctx.responseQueue = g_async_queue_new();

    requestReaderThread = create_thread("request reader", requestReader, &ctx,
                                        TRUE);
    if (!requestReaderThread) {
        g_warning("Could not allocate request reader thread");
        rv = -ENOMEM;
        goto clean;
    }

    responseWriterThread = create_thread("response writer", responseWriter,
                                         &ctx, TRUE);
    if (!responseWriterThread) {
        g_warning("Could not allocate response writer thread");
        rv = -ENOMEM;
        goto clean;
    }

    requestHandlerThread = create_thread("request handler", requestHandler,
                                         &ctx, TRUE);
    if (!requestHandlerThread) {
        g_warning("Could not allocate request handler thread");
        rv = -ENOMEM;
        goto clean;
    }


    g_thread_join(requestReaderThread);
    requestReaderThread = NULL;
    rv = 0;
clean:
    if (requestHandlerThread) {
        g_thread_join(requestHandlerThread);
    }
    if (responseWriterThread) {
        g_thread_join(responseWriterThread);
    }
    close(ctx.readPipe);
    close(ctx.writePipe);
    g_async_queue_unref(ctx.requestQueue);
    g_async_queue_unref(ctx.responseQueue);
    return rv;
}

GThread *log_writer = NULL;

static int setup_logging() {
    logger_queue = g_async_queue_new();

    g_log_set_handler(NULL, G_LOG_LEVEL_MASK, logfunc, logger_queue);

    log_writer = create_thread("log writer", logWriter, stderr, TRUE);
    if (!log_writer) {
        g_print("Could not allocate request reader thread");
        return - ENOMEM;
    }

    return 0;
}

static void stop_logging() {
    fclose(stderr);
    g_message("CLOSE"); // Push a message so that the log thread shuts down;

    if (log_writer) {
        g_thread_join(log_writer);
    }

}

int main(int argc, char *argv[]) {
    int rv = 0;
    int whitelist[] = {STDOUT_FILENO, STDERR_FILENO, -1, -1, -1};

    if (parseCmdLine(argc, argv) < 0) {
        return -1;
    }

    whitelist[2] = READ_PIPE_FD;
    whitelist[3] = WRITE_PIPE_FD;

#if !GLIB_CHECK_VERSION(2, 32, 0)
    g_thread_init(NULL);
#endif

    rv = setup_logging();
    if (rv < 0) {
        return -rv;
    }

    g_message("Starting ioprocess");

    if (!KEEP_FDS) {
        g_debug("Closing unrelated FDs...");
        rv = closeUnrelatedFDs(whitelist);
        if (rv < 0) {
            g_warning("Could not close unrelated FDs: %s",
                      iop_strerror(-rv));
            return -rv;
        }
    }

    g_debug("Opening communication channels...");
    rv = communicate(READ_PIPE_FD, WRITE_PIPE_FD);

    g_message("Shutting down ioprocess");
    stop_logging();

    return rv;
}
