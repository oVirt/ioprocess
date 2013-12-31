#ifndef __JSON_DOM_PARSER_H__
#define __JSON_DOM_PARSER_H__

#include "json-dom.h"

#include <stdint.h>

JsonNode* jdParser_buildDom(const char* buffer, uint64_t bufflen, GError** err);

#endif
