#include "WhisperBridge.h"
#include <whisper.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <ggml-backend.h>
#include <mach/mach.h>

void stts_load_backends(const char *directory) { ggml_backend_load_all_from_path(directory); }
bool stts_has_gpu(void) {
    for (size_t i = 0; i < ggml_backend_dev_count(); i++) {
        if (ggml_backend_dev_type(ggml_backend_dev_get(i)) == GGML_BACKEND_DEVICE_TYPE_GPU) return true;
    }
    return false;
}
uint64_t stts_memory_bytes(void) {
    task_vm_info_data_t info;
    mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
    if (task_info(mach_task_self(), TASK_VM_INFO, (task_info_t)&info, &count) != KERN_SUCCESS) return 0;
    return info.phys_footprint;
}

struct stts_whisper { struct whisper_context *ctx; int threads; atomic_bool cancel; };
struct stts_vad { struct whisper_vad_context *ctx; };
static bool should_abort(void *data) { return atomic_load(&((stts_whisper *)data)->cancel); }
static void quiet_log(enum ggml_log_level level, const char *text, void *data) { (void)level; (void)text; (void)data; }

stts_whisper *stts_whisper_load(const char *path, bool gpu, int threads) {
    whisper_log_set(quiet_log, NULL);
    struct whisper_context_params params = whisper_context_default_params();
    params.use_gpu = gpu;
    params.flash_attn = gpu;
    struct whisper_context *ctx = whisper_init_from_file_with_params(path, params);
    if (!ctx) return NULL;
    stts_whisper *engine = calloc(1, sizeof(*engine));
    if (!engine) { whisper_free(ctx); return NULL; }
    engine->ctx = ctx;
    engine->threads = threads < 1 ? 1 : (threads > 4 ? 4 : threads);
    atomic_init(&engine->cancel, false);
    return engine;
}
void stts_whisper_cancel(stts_whisper *engine) { if (engine) atomic_store(&engine->cancel, true); }
void stts_whisper_free(stts_whisper *engine) { if (engine) { whisper_free(engine->ctx); free(engine); } }
int stts_whisper_transcribe(stts_whisper *engine, const float *samples, int count, const char *language) {
    if (!engine || !samples || count < 1) return -1;
    if (atomic_load(&engine->cancel)) return -2;
    struct whisper_full_params p = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    p.n_threads = engine->threads;
    p.language = language;
    p.translate = false;
    p.no_context = true;
    p.no_timestamps = false;
    p.print_progress = false;
    p.print_realtime = false;
    p.print_timestamps = false;
    p.print_special = false;
    p.suppress_blank = true;
    p.suppress_nst = true;
    p.temperature = 0;
    p.temperature_inc = 0;
    p.greedy.best_of = 1;
    p.abort_callback = should_abort;
    p.abort_callback_user_data = engine;
    return whisper_full(engine->ctx, p, samples, count);
}
int stts_whisper_segment_count(stts_whisper *e) { return whisper_full_n_segments(e->ctx); }
const char *stts_whisper_segment_text(stts_whisper *e, int i) { return whisper_full_get_segment_text(e->ctx, i); }
int64_t stts_whisper_segment_start(stts_whisper *e, int i) { return whisper_full_get_segment_t0(e->ctx, i); }
int64_t stts_whisper_segment_end(stts_whisper *e, int i) { return whisper_full_get_segment_t1(e->ctx, i); }
float stts_whisper_segment_silence(stts_whisper *e, int i) { return whisper_full_get_segment_no_speech_prob(e->ctx, i); }
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
