#ifndef __EXPORTED_FUNCTIONS_h__
#define __EXPORTED_FUNCTIONS_h__

#include <glib.h>

#include "json-dom.h"

#define IOPROCESS_ARGUMENT_ERROR \
   g_quark_from_static_string("ioprocess-argument-error")

#define IOPROCESS_STDAPI_ERROR \
    g_quark_from_static_string("ioprocess-stdapi-error")

#define IOPROCESS_GENERAL_ERROR \
    g_quark_from_static_string("ioprocess-general-error")


typedef JsonNode* (*ExportedFunction) (const JsonNode* args, GError**);

struct ExportedFunctionEntry_t {
    const char* name;
    ExportedFunction callback;
};
typedef struct ExportedFunctionEntry_t ExportedFunctionEntry;

void safeGetArgValues(const JsonNode *args, GError** err,
                      int argn, ...);
void safeGetArgValue(const JsonNode *args, const char* argName,
                     JsonNodeType argType, void* out, GError** err);

JsonNode* exp_stat(const JsonNode* args, GError** err);
JsonNode* exp_symlink(const JsonNode* args, GError** err);
JsonNode* exp_truncate(const JsonNode* args, GError** err);
JsonNode* exp_link(const JsonNode* args, GError** err);
JsonNode* exp_access(const JsonNode* args, GError** err);
JsonNode* exp_chmod(const JsonNode* args, GError** err);
JsonNode* exp_unlink(const JsonNode* args, GError** err);
JsonNode* exp_echo(const JsonNode* args, GError** err);
JsonNode* exp_crash(const JsonNode* args, GError** err);
JsonNode* exp_memstat(const JsonNode* args, GError** err);
JsonNode* exp_ping(const JsonNode* args, GError** err);
JsonNode* exp_rename(const JsonNode* args, GError** err);
JsonNode* exp_readfile(const JsonNode* args, GError** err);
JsonNode* exp_glob(const JsonNode* args, GError** err);
JsonNode* exp_writefile(const JsonNode* args, GError** err);
JsonNode* exp_rmdir(const JsonNode* args, GError** err);
JsonNode* exp_statvfs(const JsonNode* args, GError** err);
JsonNode* exp_lexists(const JsonNode* args, GError** err);
JsonNode* exp_listdir(const JsonNode* args, GError** err);
JsonNode* exp_mkdir(const JsonNode* args, GError** err);
JsonNode* exp_touch(const JsonNode* args, GError** err);
JsonNode* exp_fsyncPath(const JsonNode* args, GError** err);
#endif
