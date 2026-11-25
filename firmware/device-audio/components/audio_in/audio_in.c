#include "audio_in.h"

#include <math.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include "driver/i2s_std.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static const char *TAG = "audio_in";

#pragma pack(push, 1)
typedef struct {
    int16_t b0, b1, b2, a1, a2; /* Q14 定点系数 */
} biquad_q14_t;
#pragma pack(pop)

typedef struct {
    i2s_chan_handle_t rx;
    audio_in_cfg_t cfg;
    biquad_q14_t hp;
    int32_t z1, z2;          /* 转置直接Ⅱ型状态 */
    int32_t gain_q8;         /* 定点增益 */
    uint64_t total_samples;
    bool inited;
    bool started;
} audio_in_t;

static audio_in_t s_ai;

void audio_in_cfg_default(audio_in_cfg_t *cfg)
{
    cfg->gpio_bclk = 5;
    cfg->gpio_ws = 4;
    cfg->gpio_din = 6;
    cfg->gain_db = 0;
    cfg->hp_hz = 80;
}

/* RBJ 二阶高通，系数转 Q14。在 16 kHz 下 80 Hz 高通主要抑制空调与结构低频。 */
static void biquad_hp_init(biquad_q14_t *q, float f0, float fs)
{
    const float Q = 0.70710678f;
    float w0 = 2.0f * (float)M_PI * f0 / fs;
    float cw = cosf(w0), sw = sinf(w0), alpha = sw / (2.0f * Q);
    float a0 = 1.0f + alpha;
    float b0 = (1.0f + cw) / 2.0f / a0;
    float b1 = -(1.0f + cw) / a0;
    float b2 = b0;
    float a1 = -2.0f * cw / a0;
    float a2 = (1.0f - alpha) / a0;
    const float S = 16384.0f;
    q->b0 = (int16_t)lrintf(b0 * S);
    q->b1 = (int16_t)lrintf(b1 * S);
    q->b2 = (int16_t)lrintf(b2 * S);
    q->a1 = (int16_t)lrintf(a1 * S);
    q->a2 = (int16_t)lrintf(a2 * S);
    ESP_LOGI(TAG, "HPF %d Hz @ %d Hz  b={%d,%d,%d} a={%d,%d}",
             (int)f0, (int)fs, q->b0, q->b1, q->b2, q->a1, q->a2);
}

esp_err_t audio_in_init(const audio_in_cfg_t *cfg)
{
    if (!cfg) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(&s_ai, 0, sizeof(s_ai));
    s_ai.cfg = *cfg;

    i2s_chan_config_t chan_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    chan_cfg.dma_desc_num = 8;
    chan_cfg.dma_frame_num = AUDIO_IN_FRAME;
    chan_cfg.auto_clear = true;

    esp_err_t err = i2s_new_channel(&chan_cfg, NULL, &s_ai.rx);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_new_channel: %s", esp_err_to_name(err));
        return err;
    }

    i2s_std_config_t std_cfg = {
        .clk_cfg = I2S_STD_CLK_DEFAULT_CONFIG(AUDIO_IN_SAMPLE_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT, I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = (gpio_num_t)cfg->gpio_bclk,
            .ws = (gpio_num_t)cfg->gpio_ws,
            .dout = I2S_GPIO_UNUSED,
            .din = (gpio_num_t)cfg->gpio_din,
            .invert_flags = {
                .mclk_inv = false,
                .bclk_inv = false,
                .ws_inv = false,
            },
        },
    };
    /* 数字 MEMS 麦（INMP441）输出 24 bit 左对齐，位宽按 32 bit 槽接收。
     * ESP32-S3 的 I2S 外设（HW v2）没有 msb_right 字段，左对齐用 left_align。 */
    std_cfg.slot_cfg.left_align = true;

    err = i2s_channel_init_std_mode(s_ai.rx, &std_cfg);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "i2s_channel_init_std_mode: %s", esp_err_to_name(err));
        return err;
    }

    biquad_hp_init(&s_ai.hp, (float)cfg->hp_hz, (float)AUDIO_IN_SAMPLE_RATE);
    s_ai.gain_q8 = (int32_t)(powf(10.0f, (float)cfg->gain_db / 20.0f) * 256.0f);
    s_ai.inited = true;

    ESP_LOGI(TAG, "init ok: %d Hz, bclk=%d ws=%d din=%d, gain=%d dB, hp=%d Hz",
             AUDIO_IN_SAMPLE_RATE, cfg->gpio_bclk, cfg->gpio_ws, cfg->gpio_din,
             cfg->gain_db, cfg->hp_hz);
    return ESP_OK;
}

esp_err_t audio_in_start(void)
{
    if (!s_ai.inited) {
        return ESP_ERR_INVALID_STATE;
    }
    esp_err_t err = i2s_channel_enable(s_ai.rx);
    if (err != ESP_OK) {
        return err;
    }
    s_ai.started = true;
    return ESP_OK;
}

static inline int16_t hp_process(biquad_q14_t *c, int32_t *z1, int32_t *z2, int32_t x)
{
    /* 转置直接Ⅱ型，Q14 定点。中间量用 int64，避免 Q14 乘法累加溢出。 */
    int64_t y = ((int64_t)c->b0 * x + *z1) >> 14;
    int64_t nz1 = ((int64_t)c->b1 * x - (int64_t)c->a1 * y + *z2) >> 14;
    int64_t nz2 = ((int64_t)c->b2 * x - (int64_t)c->a2 * y) >> 14;
    *z1 = (int32_t)nz1;
    *z2 = (int32_t)nz2;
    if (y > 32767) {
        y = 32767;
    } else if (y < -32768) {
        y = -32768;
    }
    return (int16_t)y;
}

size_t audio_in_read(int16_t *buf, size_t frames, uint64_t *sample_index)
{
    if (!s_ai.started || !buf || frames == 0) {
        return 0;
    }
    static int32_t raw[AUDIO_IN_FRAME * 2];
    size_t want = frames * 2 * sizeof(int32_t);
    size_t got = 0;

    if (frames > AUDIO_IN_FRAME) {
        frames = AUDIO_IN_FRAME;
        want = frames * 2 * sizeof(int32_t);
    }

    esp_err_t err = i2s_channel_read(s_ai.rx, raw, want, &got, pdMS_TO_TICKS(200));
    if (err != ESP_OK || got == 0) {
        return 0;
    }

    size_t n = got / (2 * sizeof(int32_t));
    if (n > frames) {
        n = frames;
    }
    if (sample_index) {
        *sample_index = s_ai.total_samples;
    }

    /* INMP441 只焊一颗时，另一路 slot 是静音（取决于 L/R 脚接 GND 还是 VDD）。
     * 逐帧比较两路能量，自动取有信号的那一路——接错左/右也不会全静音。 */
    int64_t energy_l = 0;
    int64_t energy_r = 0;
    for (size_t i = 0; i < n; i++) {
        int32_t l = raw[i * 2] >> 16;
        int32_t r = raw[i * 2 + 1] >> 16;
        energy_l += (l < 0) ? -l : l;
        energy_r += (r < 0) ? -r : r;
    }
    const bool use_left = (energy_l >= energy_r);

    for (size_t i = 0; i < n; i++) {
        /* 24 bit 左对齐于 32 bit 槽：取高 16 位即 16 bit 采样 */
        int32_t v = use_left ? (raw[i * 2] >> 16) : (raw[i * 2 + 1] >> 16);
        int32_t s = (v * s_ai.gain_q8) >> 8;
        buf[i] = hp_process(&s_ai.hp, &s_ai.z1, &s_ai.z2, s);
    }
    s_ai.total_samples += n;
    return n;
}

uint64_t audio_in_total_samples(void)
{
    return s_ai.total_samples;
}
