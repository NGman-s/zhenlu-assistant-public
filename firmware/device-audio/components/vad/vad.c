#include "vad.h"

#include <inttypes.h>
#include <math.h>
#include <string.h>

#include "sdkconfig.h"
#include "esp_log.h"

/* 新加的 Kconfig 项在旧 sdkconfig 里可能还不存在（要重新 configure 才会生成），
 * 这里给个兜底值，保证任何情况下都能编过。 */
#ifndef CONFIG_VAD_MAX_MS
#define CONFIG_VAD_MAX_MS 30000
#endif

static const char *TAG = "vad";

#define MAX_WIN       500   /* 10 s @ 20 ms */
#define NUM_BINS      100   /* -100 .. 0 dB，1 dB 一档 */
#define DB_MIN        (-100.0f)
#define DB_MAX        (0.0f)

typedef struct {
    vad_cfg_t cfg;
    vad_seg_cb_t cb;
    void *ctx;

    /* 噪声底：滚动直方图，避免每帧排序，内存固定 200 B + 1 KB 环 */
    uint16_t ring[MAX_WIN];
    uint16_t bin_cnt[NUM_BINS];
    int ring_pos;
    int ring_len;

    /* 状态机 */
    bool active;
    int enter_cnt;          /* 起段去抖：连续 2 帧过门限才起段 */
    int64_t seg_start_frame;
    int64_t last_speech_frame;
    int64_t frame_index;

    /* 统计 */
    uint32_t frames;
    uint32_t speech_frames;
    uint32_t segments;
    bool last_speech;
    float floor_db;
} vad_state_t;

static vad_state_t s_vad;

/* 5 帧中值滤波：抑制单帧/两帧的爆音，避免它把 400 ms 的静音间隙打断。
 * 与 Python 参考实现一致（window=5）。 */
#define MED_N 5
static float s_med_buf[MED_N];
static int   s_med_len;
static int   s_med_pos;

static float med5_push(float v)
{
    s_med_buf[s_med_pos] = v;
    s_med_pos = (s_med_pos + 1) % MED_N;
    if (s_med_len < MED_N) {
        s_med_len++;
    }
    if (s_med_len < MED_N) {
        return v;
    }
    float t[MED_N];
    for (int i = 0; i < MED_N; i++) {
        t[i] = s_med_buf[i];
    }
    /* 插入排序，5 个元素足够 */
    for (int i = 1; i < MED_N; i++) {
        float key = t[i];
        int j = i - 1;
        while (j >= 0 && t[j] > key) {
            t[j + 1] = t[j];
            j--;
        }
        t[j + 1] = key;
    }
    return t[MED_N / 2];
}

void vad_cfg_default(vad_cfg_t *cfg)
{
    /* 默认值来自 menuconfig → "诊录助手-端点检测"，改参数不用改代码 */
    cfg->frame_samples = 320;
    cfg->enter_db      = (float)CONFIG_VAD_ENTER_DB;
    cfg->exit_db       = (float)CONFIG_VAD_EXIT_DB;
    cfg->hang_frames   = CONFIG_VAD_HANG_MS / 20;
    cfg->pre_frames    = CONFIG_VAD_PRE_MS / 20;
    cfg->guard_frames  = CONFIG_VAD_GUARD_MS / 20;
    cfg->min_frames    = CONFIG_VAD_MIN_MS / 20;
    cfg->max_frames    = CONFIG_VAD_MAX_MS / 20;
    cfg->win_frames    = 500;   /* 10 s */
    cfg->peak_open     = CONFIG_VAD_PEAK_OPEN;
    cfg->peak_active   = CONFIG_VAD_PEAK_ACTIVE;
}

static inline int db_to_bin(float db)
{
    if (db <= DB_MIN) {
        return 0;
    }
    if (db >= DB_MAX) {
        return NUM_BINS - 1;
    }
    return (int)(db - DB_MIN);
}

static void noise_floor_update(float db)
{
    int b = db_to_bin(db);
    if (s_vad.ring_len >= s_vad.cfg.win_frames) {
        uint16_t old = s_vad.ring[s_vad.ring_pos];
        if (s_vad.bin_cnt[old] > 0) {
            s_vad.bin_cnt[old]--;
        }
    } else {
        s_vad.ring_len++;
    }
    s_vad.ring[s_vad.ring_pos] = (uint16_t)b;
    s_vad.bin_cnt[b]++;
    s_vad.ring_pos = (s_vad.ring_pos + 1) % s_vad.cfg.win_frames;
}

/* 取直方图的 20 分位作为噪声底（1 dB 分辨率）。
 * 用 p20 而不是 p10：宿舍/实验室这类底噪起伏大的环境，p10 会把门限压得过低，
 * 一阵风吹草动就误触发。 */
static float noise_floor_p20(void)
{
    if (s_vad.ring_len == 0) {
        return DB_MIN;
    }
    int target = (s_vad.ring_len * 2 + 9) / 10;  /* ceil(20%) */
    if (target < 1) {
        target = 1;
    }
    int acc = 0;
    for (int i = 0; i < NUM_BINS; i++) {
        acc += s_vad.bin_cnt[i];
        if (acc >= target) {
            return DB_MIN + (float)i;
        }
    }
    return DB_MIN + (float)(NUM_BINS - 1);
}

static inline float frame_db(const int16_t *x, size_t n)
{
    /* 归一化到 [-1,1] 后求功率，与参考实现同一口径 */
    const float k = 1.0f / 32768.0f;
    float acc = 0.0f;
    for (size_t i = 0; i < n; i++) {
        float v = (float)x[i] * k;
        acc += v * v;
    }
    float p = acc / (float)(n ? n : 1);
    if (p <= 1e-12f) {
        return DB_MIN;
    }
    return 10.0f * log10f(p);
}

static inline int32_t frame_peak(const int16_t *x, size_t n)
{
    int32_t pk = 0;
    for (size_t i = 0; i < n; i++) {
        int32_t v = x[i];
        if (v < 0) {
            v = -v;
        }
        if (v > pk) {
            pk = v;
        }
    }
    return pk;
}

static void emit_segment(int64_t end_frame)
{
    int64_t frames = end_frame - s_vad.seg_start_frame;
    if (frames < s_vad.cfg.min_frames) {
        return;
    }
    vad_segment_t seg;
    seg.start_sample = s_vad.seg_start_frame * s_vad.cfg.frame_samples;
    seg.end_sample = end_frame * s_vad.cfg.frame_samples;
    s_vad.segments++;
    ESP_LOGD(TAG, "segment #%" PRIu32 ": [%" PRId64 ", %" PRId64 ") = %.3f s",
             s_vad.segments, seg.start_sample, seg.end_sample,
             (double)(seg.end_sample - seg.start_sample) / 16000.0);
    if (s_vad.cb) {
        s_vad.cb(&seg, s_vad.ctx);
    }
}

esp_err_t vad_init(const vad_cfg_t *cfg, vad_seg_cb_t cb, void *ctx)
{
    if (!cfg || cfg->frame_samples <= 0) {
        return ESP_ERR_INVALID_ARG;
    }
    if (cfg->win_frames > MAX_WIN) {
        return ESP_ERR_INVALID_ARG;
    }
    memset(&s_vad, 0, sizeof(s_vad));
    s_vad.cfg = *cfg;
    s_vad.cb = cb;
    s_vad.ctx = ctx;
    s_vad.floor_db = DB_MIN;
    s_med_len = 0;
    s_med_pos = 0;
    memset(s_med_buf, 0, sizeof(s_med_buf));
    ESP_LOGI(TAG, "init: enter=%.1f exit=%.1f dB, hang=%d帧, pre=%d帧, min=%d帧, max=%d帧, peak=%d/%d",
             cfg->enter_db, cfg->exit_db, cfg->hang_frames, cfg->pre_frames, cfg->min_frames,
             cfg->max_frames, (int)cfg->peak_open, (int)cfg->peak_active);
    return ESP_OK;
}

void vad_feed(const int16_t *frame, size_t n, uint64_t sample_index)
{
    if (!frame || n == 0) {
        return;
    }
    (void)sample_index;

    float db_raw = frame_db(frame, n);
    float db = med5_push(db_raw);
    noise_floor_update(db);
    s_vad.floor_db = noise_floor_p20();

    /* 绝对峰值门限：宿舍/教室底噪再起伏，也很难越过这个值 */
    int32_t peak = frame_peak(frame, n);

    float enter = s_vad.floor_db + s_vad.cfg.enter_db;
    float exit_ = s_vad.floor_db + s_vad.cfg.exit_db;
    bool speech;

    if (!s_vad.active) {
        speech = (db > enter) && (peak >= s_vad.cfg.peak_open);
        if (speech) {
            /* 连续 2 帧（40 ms）过门限才起段，滤掉单帧毛刺 */
            if (++s_vad.enter_cnt >= 2) {
                s_vad.enter_cnt = 0;
                s_vad.active = true;
                /* 起点回退：前缓冲就在这一步，不再额外减一次（见方案勘误） */
                s_vad.seg_start_frame = s_vad.frame_index - s_vad.cfg.pre_frames - s_vad.cfg.guard_frames;
                if (s_vad.seg_start_frame < 0) {
                    s_vad.seg_start_frame = 0;
                }
                s_vad.last_speech_frame = s_vad.frame_index;
            }
        } else {
            s_vad.enter_cnt = 0;
        }
    } else {
        /* 单段超过上限就强制切一刀，避免长语音把环形缓冲撑爆、段音频被截断。
         * 新段从当前帧开始（不再回退前缓冲，否则会与上一段重叠重复）。 */
        if (s_vad.cfg.max_frames > 0 &&
            s_vad.frame_index - s_vad.seg_start_frame >= s_vad.cfg.max_frames) {
            emit_segment(s_vad.frame_index);
            s_vad.seg_start_frame = s_vad.frame_index;
            s_vad.last_speech_frame = s_vad.frame_index;
        }

        /* 收尾也要求有峰值：避免底噪的小起伏把段一直续着 */
        speech = (db > exit_) && (peak >= s_vad.cfg.peak_active);
        if (speech) {
            s_vad.last_speech_frame = s_vad.frame_index;
        } else if (s_vad.frame_index - s_vad.last_speech_frame > s_vad.cfg.hang_frames) {
            /* 挂起结束：终点回退到最后语音帧 + 保护，避免每段多送 400 ms 静音 */
            int64_t end = s_vad.last_speech_frame + s_vad.cfg.guard_frames + 1;
            emit_segment(end);
            s_vad.active = false;
        }
    }

    s_vad.last_speech = speech;
    s_vad.frames++;
    if (speech) {
        s_vad.speech_frames++;
    }
    s_vad.frame_index++;
}

bool vad_last_is_speech(void)
{
    return s_vad.last_speech;
}

void vad_stats(uint32_t *frames, uint32_t *speech_frames, uint32_t *segments)
{
    if (frames) {
        *frames = s_vad.frames;
    }
    if (speech_frames) {
        *speech_frames = s_vad.speech_frames;
    }
    if (segments) {
        *segments = s_vad.segments;
    }
}

float vad_noise_floor_db(void)
{
    return s_vad.floor_db;
}
