#ifndef __JSON_DOM_H__
#define __JSON_DOM_H__

#include <glib.h>

#define JT_LONG      1
#define JT_STRING    2
#define JT_MAP       3
#define JT_ARRAY     4
#define JT_NULL      5
#define JT_BOOLEAN   6
#define JT_DOUBLE    7

typedef int JsonNodeType;

struct JsonNode_t {
    JsonNodeType type;
    void* data;
};

typedef struct JsonNode_t JsonNode;


JsonNode* JsonNode_new(void* data, JsonNodeType type);
void JsonNode_free(JsonNode* node);

JsonNodeType JsonNode_getType(const JsonNode* node);
int JsonNode_isContainer(const JsonNode* node);

void JsonNode_array_append(JsonNode* parent, JsonNode* node, GError** err);

JsonNode* JsonNode_newNull();
JsonNode* JsonNode_newFromBoolean(int boolean);
JsonNode* JsonNode_newFromData(void* data, int dataLen, JsonNodeType type);
JsonNode* JsonNode_newFromLong(long l);
JsonNode* JsonNode_newFromString(const char* s);
JsonNode* JsonNode_newFromStringLen(const char* s, int len);
JsonNode* JsonNode_newMap();
JsonNode* JsonNode_newArray();
JsonNode* JsonNode_newFromDouble(double d);

int JsonNode_getBoolean(const JsonNode* node);
long JsonNode_getLong(const JsonNode* node);
double JsonNode_getDouble(const JsonNode* node);
GString* JsonNode_getString(const JsonNode* node);
GHashTable* JsonNode_getMap(const JsonNode* node);
GArray* JsonNode_getArray(const JsonNode* node);

JsonNode* JsonNode_map_lookup(const JsonNode* node, const char* key, GError** err);
void JsonNode_map_insert(JsonNode* parent, const char* key, JsonNode* node, GError** err);

void JsonNode_getValue(const JsonNode *node, void* out);

#endif
