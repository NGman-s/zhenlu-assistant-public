# 诊录助手接口说明（v0.1）

- Base URL：`http://127.0.0.1:8000/api`
- 数据格式：请求与响应均为 UTF-8 JSON；音频上传使用 `multipart/form-data`。
- 交互式文档：启动后端后访问 `http://127.0.0.1:8000/docs`。
- 默认语音识别和病历草稿均为 mock；草稿也可配置千问服务，响应中的 `is_mock` 和 `notice` 标识结果来源。

## 1. 错误格式

除 422 校验错误外，业务错误统一返回：

```json
{
  "code": "unsupported_audio_format",
  "message": "不支持该音频格式（.txt）。支持：flac、m4a、mp3、ogg、wav、webm。"
}
```

422 校验错误返回：

```json
{
  "code": "validation_error",
  "message": "请求参数不合法，请检查后重试。",
  "details": []
}
```

常见错误码：

| HTTP | code | 场景 |
| ---: | --- | --- |
| 400 | `empty_audio` | 上传文件为空 |
| 400 | `unknown_field` | 草稿字段 key 不在五个标准字段中 |
| 404 | `session_not_found` | 会话不存在 |
| 404 | `audio_not_found` / `audio_file_missing` | 尚无音频或文件已丢失 |
| 404 | `transcript_not_found` / `draft_not_found` | 尚未转写或尚未生成草稿 |
| 404 | `record_not_confirmed` | 尚未确认，不能读取确认记录或文本 |
| 409 | `audio_required` | 未上传音频就请求转写 |
| 409 | `transcript_required` | 未完成转写就生成草稿 |
| 409 | `draft_required` | 尚无草稿就保存/确认 |
| 409 | `audio_exists` | 同一会话重复上传音频 |
| 409 | `session_has_processing` | 会话已有处理结果，不能替换音频 |
| 409 | `transcript_exists` / `draft_exists` | 重复执行一次性生成操作 |
| 409 | `session_confirmed` | 已确认后继续修改、生成或上传 |
| 409 | `revision_conflict` | 草稿 revision 过期，需刷新后重试 |
| 413 | `audio_too_large` | 音频超过 `ZHENLU_MAX_AUDIO_MB` |
| 415 | `unsupported_audio_format` | 扩展名不在允许列表 |
| 502 | `asr_failed` / `empty_transcript` | 转写提供方失败或返回空文本 |
| 502 | `draft_generation_failed` | 草稿提供方失败 |
| 500 | `internal_error` | 未预期的服务端错误 |

## 2. 数据约定

### 2.1 时间与来源

- 所有 API 时间字段为 UTC ISO 8601 字符串，例如 `2026-10-27T08:51:00Z`。
- 转写句子 `start_ms` / `end_ms` 可为 `null`。当识别服务没有可靠时间信息时必须为 `null`，服务端和界面都不会填充推测值。
- 示例音频的时间戳来自合成音频生成记录，仅在文件名匹配且内容与内置示例一致时使用；其他上传的 mock 转写没有可靠时间戳。
- 草稿字段的 `sources` 是从转写句子中按 ID 解析出的原文。服务端会丢弃不属于当前转写的来源 ID。

### 2.2 草稿来源与版本

- `origin` 为 `ai` 或 `doctor`。
- `ai_value` 保留系统首次生成的原始值；医生修改后 `value` 变化，`ai_value` 不变。
- `revision` 是草稿乐观锁。所有修改、重新生成、确认请求都必须携带当前 `expected_revision`。
- 保存字段可传入 `accept_suggestion: true`，显式采纳当前建议的文字及其来源；该字段值必须与当前建议一致。未传入时视为普通医生编辑。
- 重新生成时：
  - `origin=ai` 的字段可更新；
  - `origin=doctor` 的字段不会被覆盖，系统结果写入 `suggestion`，需医生主动采纳。
- 确认后的记录是独立快照，草稿被锁定，不可继续编辑或重新生成。

### 2.3 主要对象

`SessionDetail` 同时是上传、转写、草稿、确认等操作接口的统一返回结构：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 会话 ID |
| `patient_name` / `patient_ref` | string / string? | 虚构患者称呼与可选编号 |
| `status` | string | 见下方状态表 |
| `status_label` | string | 中文状态标签 |
| `error_message` | string? | 最近一次处理失败的用户提示 |
| `created_at` / `updated_at` | string | UTC 时间 |
| `has_audio` / `has_transcript` / `has_draft` | bool | 资源是否存在 |
| `confirmed_version` | int | 已确认版本号 |
| `audio` | object? | 音频元数据与播放 URL |
| `transcript` | object? | 转写、模拟标识与逐句内容 |
| `draft` | object? | 五字段草稿、来源、建议和 revision |
| `latest_record` | object? | 最近一次确认记录快照与纯文本 |

`audio` 字段：

```json
{
  "id": "…",
  "filename": "mock-consultation-case-01.wav",
  "content_type": "audio/wav",
  "size_bytes": 3409356,
  "duration_ms": 106446,
  "uploaded_at": "2026-10-27T08:51:00Z",
  "url": "/api/sessions/{session_id}/audio"
}
```

`transcript` 字段：

```json
{
  "id": "…",
  "provider": "mock-consultation-asr-v1",
  "is_mock": true,
  "language": "zh-CN",
  "notice": "当前为模拟转写结果：…",
  "created_at": "2026-10-27T08:51:10Z",
  "has_reliable_timestamps": true,
  "segments": [
    {
      "id": "…",
      "seq": 0,
      "speaker": "医生",
      "text": "您好，请坐。今天主要是哪里不舒服？",
      "start_ms": 300,
      "end_ms": 5127
    }
  ]
}
```

`draft` 字段：

```json
{
  "id": "…",
  "provider": "mock-rule-based-draft-v1",
  "is_mock": true,
  "notice": "当前为模拟病历草稿：…",
  "revision": 1,
  "status": "editing",
  "created_at": "2026-10-27T08:51:20Z",
  "updated_at": "2026-10-27T08:51:20Z",
  "has_doctor_edits": false,
  "has_suggestions": false,
  "fields": [
    {
      "key": "chief_complaint",
      "label": "主诉",
      "value": "咳嗽、咳痰5天，伴发热2天。",
      "ai_value": "咳嗽、咳痰5天，伴发热2天。",
      "origin": "ai",
      "is_doctor_edited": false,
      "edited_at": null,
      "is_unmentioned": false,
      "sources": [
        {
          "id": "…",
          "seq": 1,
          "speaker": "患者",
          "text": "医生，我咳嗽、咳痰五天了，这两天还有点发烧。",
          "start_ms": 5577,
          "end_ms": 10558
        }
      ],
      "suggestion": null
    }
  ]
}
```

`latest_record` 字段：

```json
{
  "id": "…",
  "version": 1,
  "draft_revision": 2,
  "confirmed_at": "2026-10-27T08:53:00Z",
  "text": "诊录助手 · 问诊记录\n患者：演示患者 A（DEMO-001）\n…",
  "fields": [
    {
      "key": "chief_complaint",
      "label": "主诉",
      "value": "…",
      "origin": "doctor",
      "sources": []
    }
  ]
}
```

字段 key 固定为：

| key | label |
| --- | --- |
| `chief_complaint` | 主诉 |
| `present_illness` | 现病史 |
| `past_history` | 既往史 |
| `medication_history` | 用药史 |
| `allergy_history` | 过敏史 |

## 3. 接口清单

### 3.1 系统

#### `GET /health`

返回服务状态和当前提供方。

```json
{
  "status": "ok",
  "asr_provider": "mock-consultation-asr-v1",
  "asr_is_mock": true,
  "draft_provider": "mock-rule-based-draft-v1",
  "draft_is_mock": true,
  "mock_mode": true
}
```

### 3.2 会话

#### `POST /sessions`

创建问诊会话。

```json
{
  "patient_name": "演示患者 A",
  "patient_ref": "DEMO-2026-001"
}
```

- `patient_name`：必填，1–80 字符，自动去除首尾空格。
- `patient_ref`：可选，最多 120 字符。

返回 `201` 与 `SessionDetail`，初始 `status=awaiting_audio`。

#### `GET /sessions`

返回按更新时间倒序的会话摘要：

```json
{
  "items": [
    {
      "id": "…",
      "patient_name": "演示患者 A",
      "patient_ref": "DEMO-2026-001",
      "status": "draft_ready",
      "status_label": "草稿待审核",
      "created_at": "…",
      "updated_at": "…",
      "has_audio": true,
      "has_transcript": true,
      "has_draft": true,
      "confirmed_version": 0
    }
  ]
}
```

#### `GET /sessions/{session_id}`

返回完整 `SessionDetail`，包含音频、转写、草稿和最近确认记录。页面刷新后也通过该接口恢复全部已保存内容。

### 3.3 音频

#### `POST /sessions/{session_id}/audio`

`multipart/form-data`，字段名 `file`。

```bash
curl -X POST "http://127.0.0.1:8000/api/sessions/{session_id}/audio" \
  -F "file=@sample-data/mock-consultation-case-01.wav"
```

- 允许扩展名：`.wav`、`.mp3`、`.m4a`、`.ogg`、`.webm`、`.flac`。
- 大小上限由 `ZHENLU_MAX_AUDIO_MB` 控制，默认 50 MB。
- 第一阶段每个会话仅允许一段音频；上传成功后状态变为 `audio_ready`。
- 文件保存在 `backend/data/uploads/{session_id}/`，文件名使用服务端生成的 ID。
- 返回 `201` 与 `SessionDetail`。
- 不校验音频内容与扩展名是否真实匹配，不进行转码；这是演示阶段的已知限制。

#### `GET /sessions/{session_id}/audio`

流式返回本地音频文件，供页面播放。没有音频时返回 `404 audio_not_found`。

### 3.4 语音转写

#### `POST /sessions/{session_id}/transcript`

触发当前配置的转写提供方。mock 阶段为同步请求，返回 `SessionDetail`。

- 前置条件：会话已有音频，且尚无转写。
- 上传示例音频文件名时，mock ASR 返回对应虚构对话的真实示例时间戳。
- 上传其他文件时，mock ASR 使用默认虚构病例，所有时间戳为 `null`，并在 `notice` 中说明。
- `transcript.is_mock=true`，`transcript.provider` 标识模拟服务。
- 若提供方抛错，会话状态变为 `failed`、`error_message` 给出提示，接口返回 `502`；再次调用可重试。

#### `GET /sessions/{session_id}/transcript`

只返回转写对象 `transcript`，结构同上。

### 3.5 病历草稿

#### `POST /sessions/{session_id}/draft`

基于当前转写生成五个字段。前置条件：已有转写、尚无草稿。返回 `SessionDetail`。

- 五个字段全部返回；未提及的信息值为“未提及”，不会改成“无”。
- 服务端校验并过滤来源句子 ID，只保留当前转写中真实存在的句子。
- `is_mock=true` 表示由内置规则生成，未调用真实大模型。
- 千问提供方会发送对话文本及句子 ID，并要求严格结构和有效来源；无效结果返回错误，不创建草稿。

#### `GET /sessions/{session_id}/draft`

只返回草稿对象 `draft`。

#### `PATCH /sessions/{session_id}/draft`

保存医生修改。

```json
{
  "expected_revision": 1,
  "fields": [
    {
      "field_key": "chief_complaint",
      "value": "咳嗽、咳黄白痰伴发热5天，医生已核对。"
    }
  ]
}
```

- `fields` 至少 1 项、至多 5 项，字段 key 不可重复。
- 值不能为空，自动去除首尾空格。
- 仅允许五个标准字段。
- 有实际变化时：字段 `origin` 变为 `doctor`，写入 `edited_at`，草稿 `revision` 加 1。
- 若已存在系统建议，医生保存修改后该建议被清除。
- `expected_revision` 与当前 revision 不一致时返回 `409 revision_conflict`。
- 已确认会话返回 `409 session_confirmed`。

#### `POST /sessions/{session_id}/draft/regenerate`

重新生成草稿，用于演示后续生成结果的保护行为。

```json
{ "expected_revision": 2 }
```

- 对 `origin=ai` 的字段：更新 `value`、`ai_value` 和来源。
- 对 `origin=doctor` 的字段：**绝不覆盖**。如果新结果不同，写入：
  - `suggestion.value`
  - `suggestion.sources`
  - `suggestion.created_at`
- 医生可通过 `PATCH` 主动把建议值保存为当前值（此时 `origin=doctor`，建议清除）。
- 无论是否有建议，`revision` 均加 1。

### 3.6 确认、版本与复制

#### `POST /sessions/{session_id}/confirm`

```json
{ "expected_revision": 3 }
```

- 前置条件：存在草稿、未确认、revision 匹配。
- 将当前字段值、来源、`origin` 和纯文本快照写入独立确认记录。
- 会话状态变为 `confirmed`，`confirmed_version` 为该会话的第 N 版。
- 草稿 `status=confirmed` 并被锁定；后续所有修改、重生成、确认和上传均返回 `409`。
- 返回 `SessionDetail`，其中 `latest_record` 为本次确认结果。

#### `GET /sessions/{session_id}/record`

返回最近一次确认记录快照。字段结构见 `latest_record`。

#### `GET /sessions/{session_id}/record/text`

只返回纯文本，供“复制结果”使用：

```json
{
  "version": 1,
  "confirmed_at": "2026-10-27T08:53:00Z",
  "text": "诊录助手 · 问诊记录\n患者：演示患者 A（DEMO-2026-001）\n…"
}
```

未确认时返回 `404 record_not_confirmed`。

纯文本包含患者称呼、会话编号、确认时间、五个字段和说明行。mock 数据生成的文本会明确写有仅供演示的说明。

### 3.7 演示数据（开发辅助）

#### `GET /demo/cases`

返回内置虚构病例列表和音频 URL，用于页面“载入示例病例”。

#### `GET /demo/cases/{case_key}/audio`

返回示例 WAV 音频。仅用于开发演示。

## 4. 状态

| status | 含义 |
| --- | --- |
| `awaiting_audio` | 会话已创建，待录入文字或上传音频 |
| `audio_ready` | 音频已保存，待转写 |
| `transcribing` | 转写处理中（mock 为同步请求，状态短暂存在） |
| `transcribed` | 转写完成，待生成草稿 |
| `generating_draft` | 草稿生成中（mock 为同步请求） |
| `draft_ready` | 草稿待医生审核 |
| `confirmed` | 已确认并锁定 |
| `failed` | 最近一次提供方处理失败，可通过 `error_message` 查看原因 |

正常流程：

```text
awaiting_audio → audio_ready → transcribed → draft_ready → confirmed
```

任一提供方失败时进入 `failed`；对应资源尚未写入，修复或重试后可重新执行当前步骤。

## 5. 替换真实服务

代码中的提供方协议位于 `backend/app/providers/base.py`：

- `TranscriptionProvider.transcribe(audio_path, original_filename) -> AsrResult`
- `DraftGenerationProvider.generate(transcript) -> DraftResult`

在 `backend/app/providers/registry.py` 注册后，通过环境变量选择：

```bash
ZHENLU_ASR_PROVIDER=<provider-name>
ZHENLU_DRAFT_PROVIDER=<provider-name>
```

真实 ASR 接入时需要确认的信息：

1. 服务商、模型与接口地址，鉴权方式（密钥只通过环境变量或密钥管理服务提供）。
2. 支持的音频容器、采样率、单文件时长/大小和并发限制。
3. 是否返回句子或词级时间戳；若返回，应以采样位置或毫秒映射到原录音，并保证可回听定位。
4. 是否支持说话人分离；首版也可只用“医生/患者/未知”。
5. 超时、限流、重试、错误码与计费规则。真实调用通常比 mock 慢，需要改为后台任务、任务轮询和更强的失败恢复，而不是当前同步请求。

千问草稿提供方已经实现，配置见 [qwen.md](qwen.md)。真实服务使用时仍需确认：

1. 服务商、模型版本、接口协议和鉴权方式。
2. 结构化输出约束（JSON schema）与五字段定义。
3. 是否支持逐句来源 ID 引用；提示词必须把转写句子 ID 提供给模型，服务端仍会校验来源。
4. 未提及信息的统一输出规则（“未提及”，不得推断为“无”）。
5. 延迟、上下文长度、费用、日志留存和数据合规要求。

密钥、真实患者数据、真实录音均不应出现在仓库、测试夹具或前端代码中。
# 手动问诊内容

`POST /api/sessions/{session_id}/transcript/manual` 接收 `{"text":"第一段\n第二段"}`。音频可选，按非空行保存，最多 200 行、20000 字符；已有转写或正在处理时不可提交。手动内容不含音频时间戳。使用默认模拟草稿服务时，生成的是需要手动填写的模板；启用千问后可生成草稿。当前仅用于虚构病例演示。
