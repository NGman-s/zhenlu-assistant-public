#include "segmap.h"

#include <inttypes.h>
#include <string.h>

#include "esp_log.h"

static const char *TAG = "segmap";

static struct {
    uint32_t sr;
    size_t count;
    uint64_t acc_samples;   /* 累计采样数：偏移一律由它换算，避免取整漂移 */
    seg_record_t rec[SEGMAP_MAX];
} s_map;

void segmap_init(uint32_t sample_rate)
{
    memset(&s_map, 0, sizeof(s_map));
    s_map.sr = sample_rate ? sample_rate : 16000;
    ESP_LOGI(TAG, "init: %" PRIu32 " Hz, 最多 %d 段/会话", s_map.sr, SEGMAP_MAX);
}

void segmap_reset(void)
{
    uint32_t sr = s_map.sr;
    memset(&s_map, 0, sizeof(s_map));
    s_map.sr = sr;
}

int segmap_add(int64_t start_sample, int64_t end_sample, uint16_t flags)
{
    if (end_sample <= start_sample) {
        return -1;
    }
    if (s_map.count >= SEGMAP_MAX) {
        ESP_LOGW(TAG, "段表已满（%d 段），本段未记录", SEGMAP_MAX);
        return -1;
    }
    seg_record_t *r = &s_map.rec[s_map.count];
    r->seg_id = (uint16_t)s_map.count;
    r->flags = flags;
    r->orig_start_sample = (uint64_t)start_sample;
    r->sample_count = (uint32_t)(end_sample - start_sample);
    r->asr_offset_ms = (uint32_t)(s_map.acc_samples * 1000ull / s_map.sr);
    s_map.acc_samples += r->sample_count;
    s_map.count++;
    return (int)s_map.count - 1;
}

size_t segmap_count(void)
{
    return s_map.count;
}

const seg_record_t *segmap_get(size_t index)
{
    return index < s_map.count ? &s_map.rec[index] : NULL;
}

static inline void put_u16(uint8_t **p, uint16_t v)
{
    *(*p)++ = (uint8_t)(v >> 8);
    *(*p)++ = (uint8_t)(v);
}

static inline void put_u32(uint8_t **p, uint32_t v)
{
    *(*p)++ = (uint8_t)(v >> 24);
    *(*p)++ = (uint8_t)(v >> 16);
    *(*p)++ = (uint8_t)(v >> 8);
    *(*p)++ = (uint8_t)(v);
}

static inline void put_u64(uint8_t **p, uint64_t v)
{
    for (int i = 7; i >= 0; i--) {
        *(*p)++ = (uint8_t)(v >> (i * 8));
    }
}

size_t segmap_pack(uint8_t *out, size_t max_bytes)
{
    if (!out) {
        return 0;
    }
    size_t need = s_map.count * SEGMAP_RECORD_SIZE;
    if (need > max_bytes) {
        return 0;
    }
    uint8_t *p = out;
    for (size_t i = 0; i < s_map.count; i++) {
        const seg_record_t *r = &s_map.rec[i];
        put_u16(&p, r->seg_id);
        put_u16(&p, r->flags);
        put_u64(&p, r->orig_start_sample);
        put_u32(&p, r->sample_count);
        put_u32(&p, r->asr_offset_ms);
        put_u32(&p, 0);  /* reserved */
    }
    return need;
}

uint32_t segmap_total_ms(void)
{
    return (uint32_t)(s_map.acc_samples * 1000ull / s_map.sr);
}
