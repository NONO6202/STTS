#ifndef STTS_WHISPER_BRIDGE_H
#define STTS_WHISPER_BRIDGE_H
typedef struct stts_vad stts_vad;
void stts_load_backends(const char *directory);
stts_vad *stts_vad_load(const char *path);
float stts_vad_probability(stts_vad *engine, const float *samples, int count);
void stts_vad_free(stts_vad *engine);
#endif
