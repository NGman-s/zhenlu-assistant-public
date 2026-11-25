#include "seg_tx.h"

#include <stdio.h>
#include <string.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

#include "esp_heap_caps.h"
#include "esp_log.h"
#include "sdkconfig.h"

static const char *TAG = "seg_tx";

#ifndef CONFIG_SEG_TX_RING_SECONDS
#define CONFIG_SEG_TX_RING_SECONDS 60
#endif
#ifndef CONFIG_SEG_TX_STREAM
#define CONFIG_SEG_TX_STREAM 1
#endif

#define QUEUE_DEPTH   4
#define CHUNK_SAMPLES 120    /* 段模式：每行 120 采样 = 240 字节 → 320 个 base64 字符 */
#define STREAM_SAMPLES 1600  /* 流模式：每行 1600 采样 = 100 ms = 3200 字节 → 4266 个字符 */

static int16_t *s_ring;
static size_t   s_ring_samples;
static uint64_t s_written;
static QueueHandle_t s_queue;
static uint32_t s_sent;
static uint32_t s_dropped;

static bool     s_streaming;
static uint64_t s_stream_pos;   /* 流模式：已经发到哪个绝对采样 */

/* 采音任务写环、发送任务读环，s_written 必须原子读 */
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;

/* 发送任务的缓冲区放静态区：流模式一行要 4 KB 多，放任务栈会爆 */
static int16_t s_chunk[STREAM_SAMPLES];
static char    s_line[(STREAM_SAMPLES * 2 * 4 / 3) + 8];

typedef struct {
    uint16_t seg_id;
    uint32_t count;
    uint64_t start;
} job_t;

static const char B64[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static uint64_t written_snapshot(void)
{
    portENTER_CRITICAL(&s_lock);
    uint64_t w = s_written;
    portEXIT_CRITICAL(&s_lock);
    return w;
}

static size_t b64_encode(const uint8_t *in, size_t n, char *out)
{
    size_t i = 0;
    size_t o = 0;
    while (i + 2 < n) {
        uint32_t v = ((uint32_t)in[i] << 16) | ((uint32_t)in[i + 1] << 8) | (uint32_t)in[i + 2];
        out[o++] = B64[(v >> 18) & 63];
        out[o++] = B64[(v >> 12) & 63];
        out[o++] = B64[(v >> 6) & 63];
        out[o++] = B64[v & 63];
        i += 3;
    }
    if (n - i == 1) {
        uint32_t v = (uint32_t)in[i] << 16;
        out[o++] = B64[(v >> 18) & 63];
        out[o++] = B64[(v >> 12) & 63];
        out[o++] = '=';
        out[o++] = '=';
    } else if (n - i == 2) {
        uint32_t v = ((uint32_t)in[i] << 16) | ((uint32_t)in[i + 1] << 8);
        out[o++] = B64[(v >> 18) & 63];
        out[o++] = B64[(v >> 12) & 63];
        out[o++] = B64[(v >> 6) & 63];
        out[o++] = '=';
    }
    out[o] = '\0';
    return o;
}

static size_t ring_read(uint64_t abs, uint64_t written, int16_t *dst, size_t n)
{
    if (!s_ring || abs >= written) {
        return 0;
    }
    uint64_t avail = written - abs;
    if ((uint64_t)n > avail) {
        n = (size_t)avail;
    }
    size_t pos = (size_t)(abs % s_ring_samples);
    size_t first = s_ring_samples - pos;
    if (first > n) {
        first = n;
    }
    memcpy(dst, &s_ring[pos], first * sizeof(int16_t));
    if (n > first) {
        memcpy(dst + first, &s_ring[0], (n - first) * sizeof(int16_t));
    }
    return n;
}

/* 连续流：把还没发出去的音频按 100 ms 一块打印出去 */
static void stream_pump(void)
{
    uint64_t written = written_snapshot();
    uint64_t oldest = (written > s_ring_samples) ? (written - s_ring_samples) : 0;

    if (s_stream_pos < oldest) {
        /* 桌面端读得太慢，环形缓冲已经覆盖了未发送的部分 */
        printf("DROP %llu\n", (unsigned long long)oldest);
        fflush(stdout);
        s_stream_pos = oldest;
        s_dropped++;
    }

    if (written <= s_stream_pos) {
        return;
    }

    uint32_t avail = (uint32_t)(written - s_stream_pos);
    uint32_t n = (avail < STREAM_SAMPLES) ? avail : STREAM_SAMPLES;
    size_t got = ring_read(s_stream_pos, written, s_chunk, n);
    if (got == 0) {
        return;
    }
    b64_encode((const uint8_t *)s_chunk, got * sizeof(int16_t), s_line);
    printf("CHK %llu %s\n", (unsigned long long)s_stream_pos, s_line);
    fflush(stdout);
    s_stream_pos += got;
    s_sent++;
}

static void tx_task(void *arg)
{
    (void)arg;
    job_t job;
    uint32_t idle_ticks = 0;

    for (;;) {
        if (s_streaming) {
            uint64_t written = written_snapshot();
            uint64_t pending = (written > s_stream_pos) ? (written - s_stream_pos) : 0;

            if (pending >= STREAM_SAMPLES) {
                /* 攒满 100 ms 再发，减少行数与打印开销 */
                stream_pump();
                idle_ticks = 0;
                continue;
            }
            if (pending > 0 && ++idle_ticks > 60) {
                /* 300 ms 都没攒满（会话收尾/说话断续），把余量发掉 */
                stream_pump();
                idle_ticks = 0;
                continue;
            }
            if (pending == 0) {
                idle_ticks = 0;
            }
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }

        if (xQueueReceive(s_queue, &job, portMAX_DELAY) != pdTRUE) {
            continue;
        }

        uint64_t written = written_snapshot();
        uint64_t oldest = (written > s_ring_samples) ? (written - s_ring_samples) : 0;
        if (job.start < oldest) {
            s_dropped++;
            ESP_LOGW(TAG, "段 #%u 已被环形缓冲覆盖，丢弃", (unsigned)job.seg_id);
            continue;
        }

        esp_log_level_t prev_level = esp_log_level_get("*");
        esp_log_level_set("*", ESP_LOG_NONE);

        printf("SEG %u %u %llu\n", (unsigned)job.seg_id, (unsigned)job.count,
               (unsigned long long)job.start);

        uint32_t done = 0;
        while (done < job.count) {
            uint64_t now_written = written_snapshot();
            uint64_t now_oldest = (now_written > s_ring_samples) ? (now_written - s_ring_samples) : 0;
            if (job.start + done < now_oldest) {
                ESP_LOGW(TAG, "段 #%u 传输途中被环形缓冲覆盖，截断", (unsigned)job.seg_id);
                break;
            }
            uint32_t n = job.count - done;
            if (n > CHUNK_SAMPLES) {
                n = CHUNK_SAMPLES;
            }
            size_t got = ring_read(job.start + done, now_written, s_chunk, n);
            if (got == 0) {
                break;
            }
            b64_encode((const uint8_t *)s_chunk, got * sizeof(int16_t), s_line);
            printf("AUD %s\n", s_line);
            done += (uint32_t)got;
        }

        printf("END %u %u\n", (unsigned)job.seg_id, (unsigned)job.count);
        fflush(stdout);

        esp_log_level_set("*", prev_level);
        s_sent++;
    }
}

esp_err_t seg_tx_init(size_t ring_seconds)
{
    if (ring_seconds == 0) {
        ring_seconds = CONFIG_SEG_TX_RING_SECONDS;
    }
    s_ring_samples = (size_t)16000 * ring_seconds;

    s_ring = (int16_t *)heap_caps_malloc(s_ring_samples * sizeof(int16_t), MALLOC_CAP_SPIRAM);
    if (!s_ring) {
        ESP_LOGE(TAG, "PSRAM 环形缓冲分配失败（需要 %u KB）",
                 (unsigned)(s_ring_samples * sizeof(int16_t) / 1024));
        return ESP_ERR_NO_MEM;
    }
    s_written = 0;
    s_sent = 0;
    s_dropped = 0;
    s_stream_pos = 0;
    s_streaming = (CONFIG_SEG_TX_STREAM != 0);

    s_queue = xQueueCreate(QUEUE_DEPTH, sizeof(job_t));
    if (!s_queue) {
        return ESP_ERR_NO_MEM;
    }

    BaseType_t ok = xTaskCreatePinnedToCore(tx_task, "seg_tx", 4096, NULL, 1, NULL, 1);
    if (ok != pdPASS) {
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "环形缓冲 %u 秒（%u KB PSRAM），模式=%s",
             (unsigned)ring_seconds,
             (unsigned)(s_ring_samples * sizeof(int16_t) / 1024),
             s_streaming ? "连续流" : "段");
    return ESP_OK;
}

void seg_tx_push(const int16_t *pcm, size_t n)
{
    if (!s_ring || !pcm || n == 0) {
        return;
    }
    if (n > s_ring_samples) {
        pcm += (n - s_ring_samples);
        n = s_ring_samples;
    }

    portENTER_CRITICAL(&s_lock);
    size_t pos = (size_t)(s_written % s_ring_samples);
    size_t first = s_ring_samples - pos;
    if (first > n) {
        first = n;
    }
    memcpy(&s_ring[pos], pcm, first * sizeof(int16_t));
    if (n > first) {
        memcpy(&s_ring[0], pcm + first, (n - first) * sizeof(int16_t));
    }
    s_written += n;
    portEXIT_CRITICAL(&s_lock);
}

esp_err_t seg_tx_send(int64_t start_sample, int64_t end_sample, uint16_t seg_id)
{
    if (!s_ring || end_sample <= start_sample) {
        return ESP_ERR_INVALID_ARG;
    }
    if (s_streaming) {
        /* 流模式不需要按段打包，音频已经连续发出去了 */
        return ESP_OK;
    }

    uint64_t written = written_snapshot();
    uint64_t oldest = (written > s_ring_samples) ? (written - s_ring_samples) : 0;

    uint64_t st = (start_sample < 0) ? 0 : (uint64_t)start_sample;
    if (st < oldest) {
        st = oldest;
    }
    uint64_t en = (uint64_t)end_sample;
    if (en > written) {
        en = written;
    }
    if (en <= st) {
        return ESP_ERR_INVALID_STATE;
    }

    job_t job;
    job.seg_id = seg_id;
    job.count = (uint32_t)(en - st);
    job.start = st;

    if (xQueueSend(s_queue, &job, 0) != pdTRUE) {
        s_dropped++;
        ESP_LOGW(TAG, "发送队列满，丢弃段 #%u", (unsigned)seg_id);
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

void seg_tx_stats(uint32_t *sent, uint32_t *dropped)
{
    if (sent) {
        *sent = s_sent;
    }
    if (dropped) {
        *dropped = s_dropped;
    }
}

bool seg_tx_streaming(void)
{
    return s_streaming;
}
