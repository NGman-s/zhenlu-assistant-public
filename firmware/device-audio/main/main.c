/* 诊录助手终端 · 主程序
 *
 * 当前阶段（W1-W2）：采音 → 端侧 VAD 分段 → 段表，日志输出。
 * 网络上传（net_ws）与持久化缓存（storage）由嵌入式负责人接入，
 * 本文件只负责把"采音—分段—段表"这条算法链路跑起来。
 */

#include <inttypes.h>
#include <stdio.h>
#include <string.h>

#include "audio_in.h"
#include "vad.h"
#include "segmap.h"
#include "seg_tx.h"

#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "app";

static int16_t s_frame[AUDIO_IN_FRAME];

static int64_t s_boot_us;   /* 采音起点，用于时间轴自检 */
static bool    s_session_on;
static int64_t s_last_voice_us;

static void log_segment(const vad_segment_t *seg, void *ctx)
{
    (void)ctx;
    int idx = segmap_add(seg->start_sample, seg->end_sample, 0);
    const seg_record_t *r = segmap_get((size_t)(idx < 0 ? 0 : idx));
    if (!r) {
        return;
    }
    ESP_LOGI(TAG, "段 #%u  [%6.2f s → %6.2f s]  时长 %5.2f s  asr_offset %6" PRIu32 " ms",
             r->seg_id,
             (double)seg->start_sample / AUDIO_IN_SAMPLE_RATE,
             (double)seg->end_sample / AUDIO_IN_SAMPLE_RATE,
             (double)(seg->end_sample - seg->start_sample) / AUDIO_IN_SAMPLE_RATE,
             r->asr_offset_ms);

    if (seg_tx_streaming()) {
        /* 连续流模式：音频已经按块发走，这里只报话轮边界，供桌面端做标记 */
        printf("TURN %lld %lld %u\n",
               (long long)seg->start_sample, (long long)seg->end_sample, (unsigned)r->seg_id);
        fflush(stdout);
        return;
    }

    /* 把这段音频排进发送队列，由 seg_tx 任务 base64 分行打到串口 */
    seg_tx_send(seg->start_sample, seg->end_sample, r->seg_id);
}

static void print_stats(void)
{
    uint32_t frames = 0, speech = 0, segs = 0;
    vad_stats(&frames, &speech, &segs);
    float ratio = frames ? (100.0f * (float)speech / (float)frames) : 0.0f;

    /* 时间轴自检：真实时间 vs 采样数换算出的时间。
     * 正值表示真实时间走得更快——说明有样本没被读到（DMA 溢出/读超时），
     * 此时段表里的采样位置会比实际录音偏早，必须能看出来。 */
    uint64_t total = audio_in_total_samples();
    int64_t expect_ms = (int64_t)(total / (AUDIO_IN_SAMPLE_RATE / 1000));
    int64_t actual_ms = (esp_timer_get_time() - s_boot_us) / 1000;
    int64_t drift_ms = actual_ms - expect_ms;

    uint32_t sent = 0, dropped = 0;
    seg_tx_stats(&sent, &dropped);

    ESP_LOGI(TAG, "统计: 帧 %" PRIu32 " | 语音占比 %.1f%% | 段数 %" PRIu32
                  " | 噪声底 %.1f dB | 段表 %u 条 / 总时长 %" PRIu32 " ms",
             frames, ratio, segs, vad_noise_floor_db(),
             (unsigned)segmap_count(), segmap_total_ms());

    ESP_LOGI(TAG, "链路: 采样 %llu | 时间偏差 %+lld ms | 段发送 %u / 丢弃 %u",
             (unsigned long long)total, (long long)drift_ms,
             (unsigned)sent, (unsigned)dropped);

    if (drift_ms > 200 || drift_ms < -200) {
        ESP_LOGW(TAG, "时间轴偏差 %lld ms，段表时间戳会整体偏移（检查 I2S 是否丢帧）",
                 (long long)drift_ms);
    }

    if (vad_noise_floor_db() < -95.0f) {
        ESP_LOGW(TAG, "噪声底极低，麦克风可能未接或没有时钟（检查 BCLK/WS/DIN 接线）");
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "诊录助手终端启动（ESP32-S3 + 数字麦克风）");

    audio_in_cfg_t acfg;
    audio_in_cfg_default(&acfg);
    acfg.gpio_bclk = CONFIG_AUDIO_IN_I2S_BCLK;
    acfg.gpio_ws = CONFIG_AUDIO_IN_I2S_WS;
    acfg.gpio_din = CONFIG_AUDIO_IN_I2S_DIN;
    acfg.gain_db = CONFIG_AUDIO_IN_GAIN_DB;
    acfg.hp_hz = 80;

    ESP_ERROR_CHECK(audio_in_init(&acfg));
    ESP_ERROR_CHECK(audio_in_start());

    /* 60 秒环形缓冲（PSRAM），用于出段时回取整段音频 */
    ESP_ERROR_CHECK(seg_tx_init(60));

    vad_cfg_t vcfg;
    vad_cfg_default(&vcfg);
    ESP_ERROR_CHECK(vad_init(&vcfg, log_segment, NULL));

    segmap_init(AUDIO_IN_SAMPLE_RATE);

    ESP_LOGI(TAG, "开始采音，20 ms/帧。说话即可看到分段日志；每 10 秒输出一次统计。");

    uint32_t iter = 0;
    (void)iter;
    s_boot_us = esp_timer_get_time();
    int64_t last_stats = esp_timer_get_time();
    int64_t started = esp_timer_get_time();

    while (true) {
        uint64_t sample_index = 0;
        size_t n = audio_in_read(s_frame, AUDIO_IN_FRAME, &sample_index);
        if (n == 0) {
            vTaskDelay(pdMS_TO_TICKS(10));
            int64_t now = esp_timer_get_time();
            if (now - last_stats > 10 * 1000 * 1000) {
                ESP_LOGW(TAG, "10 秒内没读到样本，检查 I2S 接线与供电");
                last_stats = now;
            }
            continue;
        }

        seg_tx_push(s_frame, n);
        vad_feed(s_frame, n, sample_index);
        iter++;

        int64_t now = esp_timer_get_time();

        /* 会话边界自适应：检测到说话自动开始，静音超过 8 秒自动收尾。
         * 桌面端据此决定什么时候把整场 WAV 上传，避免逐句上传丢上下文。 */
        if (seg_tx_streaming()) {
            if (vad_last_is_speech()) {
                if (!s_session_on) {
                    printf("SESSION_START %llu\n", (unsigned long long)sample_index);
                    fflush(stdout);
                    s_session_on = true;
                }
                s_last_voice_us = now;
            } else if (s_session_on && now - s_last_voice_us > 8LL * 1000 * 1000) {
                printf("SESSION_END %llu\n", (unsigned long long)audio_in_total_samples());
                fflush(stdout);
                s_session_on = false;
            }
        }

        if (now - last_stats >= 10 * 1000 * 1000) {
            print_stats();
            last_stats = now;
        }

        /* 每 30 分钟做一次会话切分：段表回归到 0，方便长时间挂机测试 */
        if (now - started >= 30LL * 60 * 1000 * 1000) {
            ESP_LOGI(TAG, "会话切分：段表重置（共记录 %u 段）", (unsigned)segmap_count());
            segmap_reset();
            started = now;
        }
    }
}
