#define _POSIX_C_SOURCE 1

#include "json-dom.h"

#include <stdlib.h>
#include <errno.h>
#include <glib.h>
#include <string.h>

#include "utils.h"

static void JsonNode_free_cb(void* node) {
    JsonNode_free((JsonNode*) node);
}

JsonNodeType JsonNode_getType(const JsonNode* node) {
    return node->type;
}


/* Creates a new json node, the new object takes ownership of there data */
JsonNode* JsonNode_new(void* data, JsonNodeType type) {
    JsonNode* node = malloc(sizeof(JsonNode));
    if (!node) {
        return NULL;
    }

    node->type = type;
    node->data = data;

    return node;
}

/* Creates a new json node, the new object does not takes ownership of there data */
JsonNode* JsonNode_newFromData(void* data, int dataLen, JsonNodeType type) {
    JsonNode* result = NULL;
    void* dataCopy = NULL;
    if (type != JT_NULL) {
        dataCopy = malloc(dataLen);
        if (!dataCopy) {
            return NULL;
        }
        memcpy(dataCopy, data, dataLen);
    }

    result = JsonNode_new(dataCopy, type);
    if (!result) {
        free(dataCopy);
    }
    return result;
}

JsonNode* JsonNode_newNull() {
    return JsonNode_newFromData(NULL, sizeof(0), JT_NULL);
}

JsonNode* JsonNode_newFromBoolean(int boolean) {
    return JsonNode_newFromData(&boolean, sizeof(int), JT_BOOLEAN);
}

JsonNode* JsonNode_newFromLong(long l) {
    return JsonNode_newFromData(&l, sizeof(long), JT_LONG);
}

JsonNode* JsonNode_newFromDouble(double d) {
    return JsonNode_newFromData(&d, sizeof(long), JT_DOUBLE);
}

JsonNode* JsonNode_newFromString(const char* s) {
    GString* sCopy = g_string_new(s);
    return JsonNode_new(sCopy, JT_STRING);
}

JsonNode* JsonNode_newFromStringLen(const char* s, int len) {
    GString* sCopy = g_string_new_len(s, len);
    return JsonNode_new(sCopy, JT_STRING);
}

JsonNode* JsonNode_newArray() {
    GArray* array = g_array_new(TRUE, TRUE, sizeof(JsonNode*));
    return JsonNode_new(array, JT_ARRAY);
}

JsonNode* JsonNode_newMap() {
    GHashTable* map = g_hash_table_new_full(g_str_hash, g_str_equal,
                                            free, JsonNode_free_cb);
    return JsonNode_new(map, JT_MAP);
}

void JsonNode_array_append(JsonNode* parent, JsonNode* node, GError** err) {
    GArray* array;
    if (parent->type != JT_ARRAY) {
        g_set_error(err, 0, EINVAL, "Invalid type");
    }

    array = (GArray*) parent->data;
    g_array_append_val(array, node);
}

void JsonNode_map_insert(JsonNode* parent, const char* key, JsonNode* node, GError** err) {
    GHashTable* map;
    char* keyCopy;
    if (parent->type != JT_MAP) {
        g_set_error(err, 0, EINVAL, "Invalid type");
        return;
    }

    map = (GHashTable*) parent->data;
    keyCopy = g_strdup(key);
    if (!keyCopy) {
        g_set_error(err, 0, ENOMEM, "%s", iop_strerror(ENOMEM));
        return;
    }

    g_hash_table_insert(map, keyCopy, node);
}

JsonNode* JsonNode_map_lookup(const JsonNode* node, const char* key, GError** err) {
    if (node->type != JT_MAP) {
        g_set_error(err, 0, EINVAL, "Invalid type");
        return NULL;
    }

    return (JsonNode*) g_hash_table_lookup((GHashTable*) node->data, key);
}

int JsonNode_getBoolean(const JsonNode* node) {
    return *((int*) node->data);
}

long JsonNode_getLong(const JsonNode* node) {
    return *((long*) node->data);
}

double JsonNode_getDouble(const JsonNode* node) {
    return *((double*) node->data);
}

GString* JsonNode_getString(const JsonNode* node) {
    return (GString*) node->data;
}

GHashTable* JsonNode_getMap(const JsonNode* node) {
    return (GHashTable*) node->data;
}

GArray* JsonNode_getArray(const JsonNode* node) {
    return (GArray*) node->data;
}

int JsonNode_isContainer(const JsonNode* node) {
    switch(node->type) {
    case JT_MAP:
    case JT_ARRAY:
        return TRUE;
    }

    return FALSE;
}

void JsonNode_free(JsonNode* node) {
    int i;
    GArray* array;
    JsonNode* child;
    if (!node) {
        return;
    }

    if (node->data) {
        switch(node->type) {
        case JT_MAP:
            g_hash_table_remove_all((GHashTable*) node->data);
            g_hash_table_destroy((GHashTable*) node->data);
            break;
        case JT_ARRAY:
            array = (GArray*) node->data;
            for (i = 0; ; i++) {
                child = g_array_index(array, JsonNode*, i);
                if (!child) {
                    break;
                }
                JsonNode_free(child);
            }
            g_array_free(array, TRUE);
            break;
        case JT_STRING:
            g_string_free(node->data, TRUE);
            break;
        default:
            free(node->data);
            break;
        }
    }

    free(node);
}

/* Auto extract the value, use if you know that the type of the node already */
void JsonNode_getValue(const JsonNode *node, void* out) {
    switch (JsonNode_getType(node)) {
    case JT_NULL:
        *((int*)out) = 0;
        break;
    case JT_BOOLEAN:
        *((int*)out) = JsonNode_getBoolean(node);
        break;
    case JT_MAP:
        *((GHashTable**)out) = JsonNode_getMap(node);
        break;
    case JT_STRING:
        *((GString**)out) = JsonNode_getString(node);
        break;
    case JT_LONG:
        *((long*)out) = JsonNode_getLong(node);
        break;
    case JT_ARRAY:
        *((GArray**)out) = JsonNode_getArray(node);
        break;
    }
}
