# 模拟问诊数据

本目录只包含虚构病例和合成语音，不包含真实患者数据。

## 文件

| 文件 | 内容 |
| --- | --- |
| `case-01.json` | 呼吸系统问诊，信息较完整。包含症状、病程、既往史、用药史与青霉素过敏史。 |
| `case-02.json` | 呼吸系统问诊，信息缺失。未询问既往史、用药史和过敏史，用于验证“未提及”。 |
| `mock-consultation-case-01.wav` | 与 `case-01` 对应的合成中文问诊音频，约 1 分 46 秒，16 kHz / 16 bit / 单声道。 |
| `mock-consultation-case-02.wav` | 与 `case-02` 对应的合成中文问诊音频，约 51 秒，16 kHz / 16 bit / 单声道。 |

## JSON 字段

- `key`：病例标识，也是 mock ASR 匹配示例音频的标识。
- `dialogue`：逐句虚构问诊对话。`start_ms` / `end_ms` 是生成合成音频时记录的真实区间，不是模型推测的时间。
- `draft`：mock 草稿服务的预期输出，`source_indexes` 是从 0 开始的对话句序号。

## 模拟服务如何使用这些数据

1. 上传文件名为 `mock-consultation-case-01.wav` 或 `mock-consultation-case-02.wav` 时，mock ASR 使用对应病例：
   - 返回对话逐句文本；
   - 返回示例音频生成时记录的可靠时间区间。
2. 上传其他文件时，mock ASR 使用默认虚构病例，并明确提示：
   - 未匹配示例音频；
   - 所有句子不提供时间戳，服务端不会伪造时间。
3. mock 草稿服务按转写文本匹配病例，引用对应句子 ID 生成五个字段。未配置的字段统一返回“未提及”，不会改写为“无”。

## 生成合成音频（可选）

已提供的 WAV 文件可直接使用。若要重新生成，需要 Windows PowerShell 和
`Microsoft Huihui Desktop` 中文语音：

```bash
python scripts/generate_demo_audio.py
```

脚本会逐句合成对话，拼接为 16 kHz WAV，并把每句话的开始/结束毫秒写回
JSON。合成语音只用于开发演示，人物、病情和音频均为虚构。
