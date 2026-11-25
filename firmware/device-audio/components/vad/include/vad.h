#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* 端侧 VAD：能量 + 自适应噪声底 + 滞回 + 挂起。
 * 参数默认值与《音频算法与测试方案》表4 对应，改动前请同步文档。 */

typedef struct {
    int frame_samples;   /* 每帧采样数，320 = 20 ms */
    float enter_db;      /* 进入阈值：噪声底 + 9 dB */
    float exit_db;       /* 退出阈值：噪声底 + 6 dB（与 enter 拉开 3 dB 滞回） */
    int hang_frames;     /* 静音挂起 280 ms = 14 帧 */
    int pre_frames;      /* 起点回退窗口 300 ms = 15 帧 */
    int guard_frames;    /* 边界保护 100 ms = 5 帧 */
    int min_frames;      /* 最短语音段 200 ms = 10 帧 */
    int max_frames;      /* 单段上限 30 s = 1500 帧，超过强制切分 */
    int win_frames;      /* 噪声底窗口 500 帧 = 10 s */
    int32_t peak_open;   /* 起段所需的最小峰值（绝对值，满幅 32767） */
    int32_t peak_active; /* 维持段所需的最小峰值 */
} vad_cfg_t;

typedef struct {
    int64_t start_sample;
    int64_t end_sample;   /* 不含 */
} vad_segment_t;

typedef void (*vad_seg_cb_t)(const vad_segment_t *seg, void *ctx);

void vad_cfg_default(vad_cfg_t *cfg);

esp_err_t vad_init(const vad_cfg_t *cfg, vad_seg_cb_t cb, void *ctx);

/* 送入一帧 int16 PCM；sample_index 是该帧首个采样在会话内的序号。 */
void vad_feed(const int16_t *frame, size_t n, uint64_t sample_index);

/* 最近一帧是否判为语音（供调试与帧判决导出使用）。 */
bool vad_last_is_speech(void);

/* 统计：已处理帧数、语音帧数、语音段数。 */
void vad_stats(uint32_t *frames, uint32_t *speech_frames, uint32_t *segments);

/* 当前噪声底（dB），负数，用于日志与现场排障。 */
float vad_noise_floor_db(void);

#ifdef __cplusplus
}
#endif
