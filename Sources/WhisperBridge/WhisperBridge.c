#include "WhisperBridge.h"
#include <whisper.h>
#include <stdlib.h>
#include <ggml-backend.h>

void stts_load_backends(const char *directory) { ggml_backend_load_all_from_path(directory); }
struct stts_vad { struct whisper_vad_context *ctx; };
static void quiet_log(enum ggml_log_level level, const char *text, void *data) { (void)level; (void)text; (void)data; }

stts_vad *stts_vad_load(const char *path) {
    whisper_log_set(quiet_log, NULL);
    struct whisper_vad_context_params p = whisper_vad_default_context_params();
    p.n_threads = 1; p.use_gpu = false;
    struct whisper_vad_context *ctx = whisper_vad_init_from_file_with_params(path, p);
    if (!ctx) return NULL;
    stts_vad *e = calloc(1, sizeof(*e));
    if (!e) { whisper_vad_free(ctx); return NULL; }
    e->ctx = ctx; return e;
}
float stts_vad_probability(stts_vad *e, const float *samples, int count) {
    if (!e || !whisper_vad_detect_speech_no_reset(e->ctx, samples, count)) return -1;
    int n = whisper_vad_n_probs(e->ctx);
    if (n < 1) return 0;
    float *p = whisper_vad_probs(e->ctx), value = 0;
    for (int i = 0; i < n; ++i) if (p[i] > value) value = p[i];
    return value;
}
void stts_vad_free(stts_vad *e) { if (e) { whisper_vad_free(e->ctx); free(e); } }
