#include "json-dom-generator.h"

#include <glib.h>
#include <string.h>
#include <stdlib.h>
#include <yajl/yajl_gen.h>

static void jdGenerator_generate_node(yajl_gen gen, const JsonNode* node);

static yajl_gen create_yajl_gen() {
#if YAJL_VERSION == 2
    return yajl_gen_alloc(NULL);
#else
    yajl_gen_config conf = { 1, "  " };
    return yajl_gen_alloc(&conf, NULL);
#endif
}

char* jdGenerator_generate(const JsonNode* node, uint64_t* resLen) {
    char* res;
    const unsigned char* buf;
#if YAJL_VERSION == 2
    size_t len;
#else
    unsigned int len;
#endif
    yajl_gen g = create_yajl_gen();
    jdGenerator_generate_node(g, node);
    yajl_gen_get_buf(g, &buf, &len);
    res = (char*) calloc(len, sizeof(char*));
    memcpy(res, buf, (int) len);
    *resLen = len;
    yajl_gen_clear(g);
    yajl_gen_free(g);
    return res;
}

static void jdGenerator_generate_node(yajl_gen gen, const JsonNode* node) {
    GString* tmpStr;
    GHashTable* tmpHashTable;
    GArray* tmpArray;
    GHashTableIter iter;
    int i;
    char* key;
    const JsonNode* value;
    switch(node->type) {
    case JT_NULL:
        yajl_gen_null(gen);
        break;
    case JT_BOOLEAN:
        yajl_gen_bool(gen, JsonNode_getBoolean(node));
        break;
    case JT_LONG:
        yajl_gen_integer(gen, JsonNode_getLong(node));
        break;
    case JT_DOUBLE:
        yajl_gen_double(gen, JsonNode_getDouble(node));
        break;
    case JT_STRING:
        tmpStr = JsonNode_getString(node);
        yajl_gen_string(gen,
                        (const unsigned char*) tmpStr->str,
                        (unsigned int) tmpStr->len);
        break;
    case JT_MAP:
        tmpHashTable = JsonNode_getMap(node);
        g_hash_table_iter_init(&iter, tmpHashTable);
        yajl_gen_map_open(gen);
        while (g_hash_table_iter_next(&iter, (void**) &key, (void**)
                                      &value)) {
            yajl_gen_string(gen,
                            (const unsigned char*) key,
                            (unsigned int) strlen(key));
            jdGenerator_generate_node(gen, value);
        }
        yajl_gen_map_close(gen);
        break;
    case JT_ARRAY:
        yajl_gen_array_open(gen);
        tmpArray = JsonNode_getArray(node);
        for (i = 0; ; i++) {
            value = g_array_index(tmpArray, JsonNode*, i);
            if (!value) {
                break;
            }
            jdGenerator_generate_node(gen, value);
        }
        yajl_gen_array_close(gen);
        break;
    }
}

