#pragma once

#include <stdint.h>
#include <stddef.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* 段表：24 字节定长记录，网络字节序。
 * 字段定义见《音频算法与测试方案》表5。
 *
 * 关键纪律：位置一律用采样整数保存，asr_offset_ms 由"累计采样数"换算，
 * 不允许逐段换算成毫秒后再累加（会产生累计取整误差）。 */

#define SEGMAP_RECORD_SIZE 24
#define SEGMAP_MAX         512

typedef struct {
    uint16_t seg_id;
    uint16_t flags;
    uint64_t orig_start_sample;
    uint32_t sample_count;
    uint32_t asr_offset_ms;
} seg_record_t;

void segmap_init(uint32_t sample_rate);
void segmap_reset(void);

/* 追加一个语音段；返回下标，满则返回 -1。 */
int segmap_add(int64_t start_sample, int64_t end_sample, uint16_t flags);

size_t segmap_count(void);
const seg_record_t *segmap_get(size_t index);

/* 打包成网络字节序的连续记录，返回写入字节数（= count × 24）。 */
size_t segmap_pack(uint8_t *out, size_t max_bytes);

/* 全部段拼起来的音频总时长（毫秒）。 */
uint32_t segmap_total_ms(void);

#ifdef __cplusplus
}
#endif
