/* cortex-engine: LFM3-Omni with the NPU vision encoder and the LM in one runtime.
 *
 * The latest camera frame is encoded (NPU + CPU islands) and read into the LM's memory in the background, so an ask
 * only reads the question. Every call returns immediately; results arrive as JSON lines through the event callback
 * given to ce_open, from engine threads:
 *   {"type":"token","text":...}
 *   {"type":"done","ttft_ms":..,"total_ms":..,"n_out":..,"view_frame_id":..,"view_age_ms":..,"cancelled":..}
 *   {"type":"view","frame_id":..,"skipped":..,"cos":..,"prep_ms":..,"encode_ms":..[,"read_ms":..,"preempted":..]}
 *   {"type":"error","what":...}
 *
 * Config JSON: model, mmproj, split_dir, qnn_lib_dir (required); system_prompt, lm_cpus [4-7], vision_cpus [1-3],
 * island_cpus [4-7], skip_cos 0.98, max_tokens 60, max_history_tokens 1536. cpu0 is the safety core and is refused.
 */
#ifndef CORTEX_ENGINE_H
#define CORTEX_ENGINE_H
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef void (*ce_event_cb)(const char* json_line, void* user);

void* ce_open(const char* config_json, ce_event_cb cb, void* user); /* NULL on failure, see ce_last_error */
const char* ce_last_error(void);                                    /* this thread's last ce_open error */
int ce_push_frame(void* h, const uint8_t* rgb, int w, int hgt, long frame_id); /* copies; latest frame wins */
int ce_refresh(void* h);                          /* prepare, encode, skip check, read the view */
int ce_ask(void* h, const char* text, int max_tokens); /* -1 and an error "busy" event while an ask runs */
int ce_cancel(void* h);
int ce_reset_history(void* h);
const char* ce_status(void* h); /* JSON; valid until the next ce_status call on h */
void ce_close(void* h);

#ifdef __cplusplus
}
#endif
#endif
