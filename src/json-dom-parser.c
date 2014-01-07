#include "json-dom-parser.h"

#include <glib.h>
#include <errno.h>
#include <yajl/yajl_parse.h>
#include <stdint.h>

#if YAJL_VERSION == 2
#define t_yajl_long long long
#define t_yajl_size size_t
#else
#define t_yajl_long long
#define t_yajl_size unsigned int
#endif

struct JsonDomBuilderCtx_t {
    GString* tmpMapKay;
    GQueue* containerStack;
};

typedef struct JsonDomBuilderCtx_t JsonDomBuilderCtx;

static void jdBuilder_init(JsonDomBuilderCtx* ctx) {
    ctx->containerStack = g_queue_new();
    ctx->tmpMapKay = g_string_new(NULL);
}

static void jdBuilder_done(JsonDomBuilderCtx* ctx) {
    g_queue_free(ctx->containerStack);
    g_string_free(ctx->tmpMapKay, TRUE);
}

static int jdBuilder_popContainerStack(JsonDomBuilderCtx* ctx) {
    g_queue_pop_head(ctx->containerStack);
    return 0;
}

static int jdBuilder_addValue(JsonDomBuilderCtx* ctx, JsonNode* node) {
    JsonNode* head = NULL;

    head = (JsonNode*) g_queue_peek_head(ctx->containerStack);
    if (!head) {
        g_queue_push_head(ctx->containerStack, node);
        return 0;
    }

    switch(head->type) {
    case JT_ARRAY:
        JsonNode_array_append(head, node, NULL);
        break;
    case JT_MAP:
        JsonNode_map_insert(head, ctx->tmpMapKay->str, node, NULL);
        break;
    default:
        g_warning("Parser Error");
        return -1;
    }
    return 0;
}

static int cb_build_safeAdd(void* ctx, JsonNode* node) {
    if (!node) {
        return 0;
    }

    if (jdBuilder_addValue((JsonDomBuilderCtx*) ctx, node) < 0) {
        JsonNode_free(node);
        return 0;
    }

    return 1;
}


static int cb_build_null(void * ctx) {
    JsonNode* node = JsonNode_newNull();
    return cb_build_safeAdd(ctx, node);
}

static int cb_build_boolean(void * ctx, int boolean) {
    JsonNode* node = JsonNode_newFromBoolean(boolean);
    return cb_build_safeAdd(ctx, node);
}

static int cb_build_long(void * ctx, t_yajl_long l) {
    JsonNode* node = JsonNode_newFromLong(l);
    return cb_build_safeAdd(ctx, node);
}

static int cb_build_double(void * ctx, double d) {
    JsonNode* node = JsonNode_newFromDouble(d);
    return cb_build_safeAdd(ctx, node);
}

static int cb_build_string(void * ctx, const unsigned char* stringVal,
                           t_yajl_size stringLen) {
    JsonNode* node = JsonNode_newFromStringLen((const char*) stringVal,
                     stringLen);
    JsonNode_getString(node);
    return cb_build_safeAdd(ctx, node);
}

static int cb_build_map_key(void * ctx, const unsigned char * stringVal,
                            t_yajl_size stringLen) {
    JsonDomBuilderCtx* c = (JsonDomBuilderCtx*) ctx;
    g_string_overwrite_len(c->tmpMapKay, 0,
                           (const char*) stringVal, (int) stringLen);
    g_string_truncate(c->tmpMapKay, stringLen);
    return 1;
}

static int cb_build_safeContainerAdd(JsonDomBuilderCtx* ctx, JsonNode*
                                     container) {
    if (!cb_build_safeAdd(ctx, container)) {
        return 0;
    }
    g_queue_push_head(ctx->containerStack, container);

    return 1;
}

static int cb_build_start_map(void* ctx) {
    JsonNode* node = JsonNode_newMap();
    return cb_build_safeContainerAdd((JsonDomBuilderCtx*) ctx, node);
}


static int cb_build_end_container(void * ctx) {
    jdBuilder_popContainerStack((JsonDomBuilderCtx*) ctx);
    return 1;
}

static int cb_build_start_array(void * ctx) {
    JsonNode* node = JsonNode_newArray();
    return cb_build_safeContainerAdd((JsonDomBuilderCtx*) ctx, node);
}

static yajl_callbacks build_callbacks = {
    cb_build_null,
    cb_build_boolean,
    cb_build_long,
    cb_build_double,
    NULL,
    cb_build_string,
    cb_build_start_map,
    cb_build_map_key,
    cb_build_end_container,
    cb_build_start_array,
    cb_build_end_container
};

JsonNode* jdParser_buildDom(const char* buffer, uint64_t bufflen,
                            GError** err) {
    JsonDomBuilderCtx ctx;
    yajl_handle parser = NULL;
    JsonNode* result = NULL;
    yajl_status stat;
    jdBuilder_init(&ctx);
#if YAJL_VERSION == 2
    parser = yajl_alloc(&build_callbacks, NULL, (void *) &ctx);
#else
    yajl_parser_config cfg = { 1, 1 };
    parser = yajl_alloc(&build_callbacks, &cfg, NULL, (void *) &ctx);
#endif
    if (!parser) {
        g_set_error(err, 0, ENOMEM,
                    "Could not allocate json parser: %s",
                    g_strerror(ENOMEM));
        goto clean;
    }

    stat = yajl_parse(parser,
                      (const unsigned char*) buffer,
                      (unsigned int) bufflen);
    if (stat != yajl_status_ok) {
        g_set_error(err, 0, EINVAL,
                    "Could not parse json string: %s",
                    g_strerror(EINVAL));
        goto clean;
    }

#if YAJL_VERSION == 2
    stat = yajl_complete_parse(parser);
#else
    stat = yajl_parse_complete(parser);
#endif
    if (stat != yajl_status_ok) {
        g_set_error(err, 0, EINVAL,
                    "Could not parse json string: %s",
                    g_strerror(EINVAL));
        goto clean;
    }
    result = (JsonNode*) g_queue_peek_tail(ctx.containerStack);

clean:
    if (!result) {
        result = (JsonNode*) g_queue_peek_tail(ctx.containerStack);
        if (result) {
            JsonNode_free(result);
            result = NULL;
        }
    }

    if (parser) {
        yajl_free(parser);
    }

    jdBuilder_done(&ctx);
    return result;
}
