#ifndef __JSON_DOM_GENERATOR_H__
#define __JSON_DOM_GENERATOR_H__

#include "json-dom.h"
#include <stdint.h>

char* jdGenerator_generate(const JsonNode* node, uint64_t* resLen);

#endif
