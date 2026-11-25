# 设备音频接入（ESP32 → 本地后端）

本文说明设备音频怎么进到现有后端。核心结论：**整场对话一次上传**，不要逐句上传。

> 接线、供电与上电自检见 [hardware.md](hardware.md)。

## 1. 为什么不是"一句话一次请求"

现有后端是「一个会话 = 一个音频文件 = 一次转写」：

- `POST /api/sessions/{id}/audio` 每会话只接受一个文件，重复上传返回 `audio_exists`；
- Fun-ASR 走实时 WebSocket，把文件按 3200 字节分块喂进去，句间上下文靠同一次任务维持；
- 转写句子的 `start_ms/end_ms` 直接用于工作台回听定位。

如果按 VAD 段逐条上传：每次都要新建任务，上下文清零、句间指代丢失、拼接处容易错位，
正是"断断续续导致误判"的来源。所以设备只负责**连续采音**，切分与上传由会话边界决定。

## 2. 串口协议

- 物理层：UART0（板载 CH343），**921600**，8N1
- 编码：文本行，`\n` 结尾；音频用 base64
- 音频参数：16 kHz / 16-bit / 单声道（与后端 WAV 要求一致）

| 行 | 含义 | 说明 |
| --- | --- | --- |
| `SESSION_START <采样>` | 会话开始 | 检测到说话；采样为该时刻的绝对采样位置 |
| `CHK <采样> <base64>` | 音频块 | 每 100 ms 一块（1600 采样 / 3200 字节），采样为块首的绝对位置 |
| `TURN <起> <止> <段号>` | 话轮边界 | 仅作标记，**不触发上传** |
| `SESSION_END <总采样>` | 会话结束 | 静音 8 秒触发；桌面端据此收尾并上传 |
| `DROP <采样>` | 音频缺口 | 设备环形缓冲被覆盖，桌面端应告警 |

其它行（`I (123) app: …` 之类的日志）桌面端直接忽略。

### 时间轴约定

所有位置都是**绝对采样数**（从开机采音算起），不是相对时间。桌面端按
`offset = (采样 - 起始采样) × 2` 字节 seek 写入 PCM 文件，没写到的位置读出来是零，
因此缺口自动补成静音，**总时长与原始录音严格一致**，转写时间戳可以直接定位回听。

## 3. 会话边界（"自适应"在这里）

固件侧的边界：

- **开始**：VAD 判定说话，发 `SESSION_START`
- **一句结束**：连续静音 8 秒，发 `SESSION_END`（**注意：这只是"这句说完了"，不代表整场结束**）
- 中途的短停顿不会触发任何事件，音频照常连续发送

桌面端（`recorder.py`）负责把多句合成一场：

- 收到 `SESSION_START` 时保留起点前 300 ms，避免吃掉第一个字的声母
- **`SESSION_END` 后不立刻上传**，而是再等 `--idle-timeout`（默认 10 秒）
- 若这期间又出现新的 `SESSION_START`，说明医生只是停顿，继续写同一个文件
- 只有"最后一句之后静音约 18 秒（固件 8 秒 + 代理 10 秒）"才收尾上传；按 Ctrl+C 立即收尾
- 上传与转写在**后台线程**进行，不阻塞串口读取，否则后续对话会丢

## 4. 桌面端：`desktop/recorder.py`

```powershell
# 依赖（与 device_identity 相同）
python -m pip install -r desktop\requirements.txt

# 录音 + 上传（后端需先启动）
python desktop\recorder.py --port COM5

# 录音 + 上传 + 立即转写（阻塞，耗时≈录音时长）
python desktop\recorder.py --port COM5 --transcribe

# 只录音不上传
python desktop\recorder.py --port COM5 --no-upload

# 离线回放抓包文件，不接硬件（调试用）
python desktop\recorder.py --replay capture.txt --no-upload
```

输出示例：

```
打开 COM5 @ 921600 …
就绪：开始问诊即可；停顿不要紧，说完后静音约 18 秒会自动收尾上传（Ctrl+C 立即收尾）
  已开始接收音频，正在等待说话…（说完停一会儿自动收尾）
  会话开始（采样 16000，含 300 ms 前导）
  最后一句后已静音 10 秒，收尾。
  会话结束：15.5 s，0.5 MB，话轮 5 个，丢块 0
  已上传会话 0f3c…
  开始转写（耗时约等于录音时长，可继续说下一场）…
  转写完成
```

上传流程：`POST /api/sessions` → `POST /api/sessions/{id}/audio`（带 `X-Audio-SHA256`）。

## 5. 固件开关

`menuconfig → 诊录助手-音频回传`：

| 选项 | 默认 | 说明 |
| --- | --- | --- |
| 连续流模式 | 开 | 关掉则退回 `SEG/AUD/END` 段模式，供 `tools/serial/recv_segments.py` 调试 |
| 环形缓冲长度 | 60 s | 吸收发送抖动；台面出现 `DROP` 时可加大 |

## 6. 已知限制

1. **收尾需要等静音**：固件 8 秒 + 代理 10 秒，共约 18 秒（`--idle-timeout` 可调）。想立刻上传就按 Ctrl+C。
2. **转写耗时 ≈ 录音时长**（现有 Fun-ASR 实现是"把文件按实时速率喂进去"）。真正的边说边出字需要增量转写，属于后端改造。
3. **设备身份尚未合并**：`firmware/device-key` 的 ZL1 验签固件与本音频固件目前是两份，需要合成一份。
4. **开头可能丢零点几秒**：端侧 VAD 起段需要 2 帧去抖，加上识别模型偶尔漏掉极短的起始音节；如需更稳可把 `VAD_PRE_MS` 从 300 提到 500。
5. `DROP` 只告警不重传：缺口会变成静音，长会话若桌面端读得慢需要加大环形缓冲。
6. 单次上传受后端 `ZHENLU_MAX_AUDIO_MB`（默认 50 MB）限制，约 26 分钟 16 kHz 单声道。
7. **前端有两种起法**：`npm run build` + 设置 `ZHENLU_DEVICE_STATE_FILE` 走受管模式（需要设备心跳，否则写操作被 423 拦下）；开发调试建议 `npm run dev`（5173），没有设备门禁。

## 7. 受管模式（插上设备才能写）

后端支持"设备在才允许写"的门禁：设置 `ZHENLU_DEVICE_STATE_FILE` 后，
后端读该文件的心跳（超过 8 秒视为断开），断开时把写操作全部拒绝（HTTP 423），
界面顶部提示"设备已断开"。

录音代理可以直接充当心跳源：

```powershell
# 后端（受管模式）
$env:ZHENLU_DEVICE_STATE_FILE = 'D:\esp32\device-state.json'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# 录音代理（同时写心跳）
D:\anaconda\python.exe desktop\recorder.py --port COM5 --state-file D:\esp32\device-state.json
```

行为：

| 状态 | 界面 | 写操作 |
| --- | --- | --- |
| 录音代理运行中（每 3 秒写心跳） | 正常 | 允许 |
| 代理退出/拔线（心跳超过 8 秒） | 顶部黄条"设备已断开" | 拒绝（423） |

> `mode` 目前写的是 `usb-detection`（只表示"设备在"），
> 真正的签名验签需要用 `desktop/agent.py --identity`，两者的门禁语义不同。

## 8. 测试

`desktop/tests/test_recorder.py` 覆盖拼包逻辑（时间轴、缺口补零、跨会话、坏包容错）：

```powershell
python desktop\tests\test_recorder.py      # 独立运行，不依赖 pytest
# 或 pytest desktop/tests
```
