#ifndef STTS_WHISPER_BRIDGE_H
#define STTS_WHISPER_BRIDGE_H
#include <stdbool.h>
#include <stdint.h>
typedef struct stts_whisper stts_whisper;
typedef struct stts_vad stts_vad;
void stts_load_backends(const char *directory);
bool stts_has_gpu(void);
uint64_t stts_memory_bytes(void);
stts_whisper * stts_whisper_load(const char *path, bool gpu, int threads);
void stts_whisper_cancel(stts_whisper *engine);
void stts_whisper_free(stts_whisper *engine);
int stts_whisper_transcribe(stts_whisper *engine, const float *samples, int count, const char *language);
int stts_whisper_segment_count(stts_whisper *engine);
const char *stts_whisper_segment_text(stts_whisper *engine, int index);
int64_t stts_whisper_segment_start(stts_whisper *engine, int index);
int64_t stts_whisper_segment_end(stts_whisper *engine, int index);
float stts_whisper_segment_silence(stts_whisper *engine, int index);
stts_vad *stts_vad_load(const char *path);
float stts_vad_probability(stts_vad *engine, const float *samples, int count);
void stts_vad_free(stts_vad *engine);
#endif
