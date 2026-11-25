#pragma once

#include <stdint.h>
#include <stddef.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* 采音参数：16 kHz / 16 bit / 单声道（采集双通道下混），32 000 B/s。
 * 与《音频算法与测试方案》表2 一致：固定增益、80 Hz 高通、20 ms 一帧。 */
#define AUDIO_IN_SAMPLE_RATE 16000
#define AUDIO_IN_FRAME       320   /* 20 ms */

typedef struct {
    int gpio_bclk;
    int gpio_ws;
    int gpio_din;
    int gain_db;     /* 固定数字增益 0..18 dB，出厂标定后写入 NVS */
    int hp_hz;       /* 高通截止频率，建议 80 */
} audio_in_cfg_t;

void audio_in_cfg_default(audio_in_cfg_t *cfg);

esp_err_t audio_in_init(const audio_in_cfg_t *cfg);
esp_err_t audio_in_start(void);

/* 阻塞读取一帧（frames 个采样，单声道 int16），返回实际采样数。
 * sample_index 返回该帧首个采样在会话内的序号（uint64，暂停时不增长）。 */
size_t audio_in_read(int16_t *buf, size_t frames, uint64_t *sample_index);

uint64_t audio_in_total_samples(void);

#ifdef __cplusplus
}
#endif
