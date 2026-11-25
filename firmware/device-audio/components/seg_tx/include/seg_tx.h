#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "esp_err.h"

#ifdef __cplusplus
extern "C" {
#endif

/* 段音频回传：PSRAM 环形缓冲 + 独立发送任务。
 *
 * 音频先进环（覆盖旧数据），VAD 出段时把 [start_sample, end_sample) 从环里拷出来，
 * 交给发送任务用 base64 分行打到控制台串口：
 *
 *   SEG <seg_id> <count>
 *   AUD <base64...>
 *   AUD <base64...>
 *   END <seg_id> <count>
 *
 * 用文本行而不是二进制，是为了绕开控制台把 \n 转成 \r\n 的问题；
 * 上位机按行过滤即可，和日志混在一起也不会串。 */

esp_err_t seg_tx_init(size_t ring_seconds);

/* 每帧采音后调用，把最新 PCM 追加进环形缓冲。 */
void seg_tx_push(const int16_t *pcm, size_t n);

/* VAD 出段时调用：只把段的位置排进队列（不拷贝、不阻塞采音）。 */
esp_err_t seg_tx_send(int64_t start_sample, int64_t end_sample, uint16_t seg_id);

/* 统计：已发送段数、被丢弃段数（队列满或已被环形缓冲覆盖）。 */
void seg_tx_stats(uint32_t *sent, uint32_t *dropped);

/* 当前是否处于连续流模式（Kconfig: 诊录助手-音频回传 → 连续流模式）。 */
bool seg_tx_streaming(void);

#ifdef __cplusplus
}
#endif
