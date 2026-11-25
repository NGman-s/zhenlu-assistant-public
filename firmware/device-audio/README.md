# firmware —— 诊录助手 ESP32 终端固件

**当前状态**：采音 → VAD 分段 → 段表 这条链路已在真机跑通；语音段上传、界面还没做。

- 芯片：ESP32-S3-WROOM-1-N16R8（16 MB Flash + 8 MB PSRAM）
- 麦克风：INMP441（I2S 数字 MEMS，24 bit）
- 框架：ESP-IDF **5.1.2**，装在 `D:\esp32\Espressif`

## 一、接线

| INMP441 | ESP32-S3 |
|---|---|
| VDD | 3V3 |
| GND | GND |
| L/R | GND（选左声道） |
| SCK (BCLK) | IO5 |
| WS | IO4 |
| SD (DIN) | IO6 |

引脚可在 `menuconfig → 诊录助手-采音配置` 里改，默认值存在 `sdkconfig.defaults`。

## 二、目录与职责

```
firmware/
├─ main/main.c              采音循环：读帧 → 喂 VAD → 出段回调 → 写段表 → 打日志
├─ components/
│  ├─ audio_in/             I2S 采音：32 bit 槽取 24 bit 左对齐数据、双声道自动选路、
│  │                        80 Hz 二阶高通（Q14 定点）、增益
│  ├─ vad/                  端点检测：20 ms 帧能量 + 噪声底直方图 + 双门限 + 中值滤波
│  └─ segmap/               段表：每段 24 字节大端记录，采样数为主、毫秒为派生
├─ sdkconfig.defaults       首次构建的默认配置（纯 ASCII，避免 GBK 解码问题）
└─ CMakeLists.txt           生成 compile_commands.json 供 VS Code 智能提示
```

## 三、编译与烧录

### 方式 A：VS Code（推荐）

用 VS Code 打开 **本目录**（`D:\esp32\firmware`，不是上层目录），状态栏依次点：

1. 🔨 编译
2. ⚡ 烧录
3. 📺 串口监视（`Ctrl + ]` 退出）

或命令面板：`ESP-IDF: Build your project` / `Flash` / `Monitor`。

### 方式 B：命令行

```powershell
cd D:\esp32\firmware
idf.py build
idf.py -p COM5 flash monitor
```

> 注意：请用 ESP-IDF 自带的 Python 环境，不要用 Anaconda 的 python 跑 `idf.py`。

## 四、参数调优（不用改代码）

`menuconfig → 诊录助手-端点检测（VAD）`：

| 参数 | 默认 | 作用 | 什么时候调 |
|---|---|---|---|
| 起段门限 `VAD_ENTER_DB` | 9 dB | 高于「噪声底 + N dB」才开始一段 | 环境吵就调大 |
| 收尾门限 `VAD_EXIT_DB` | 6 dB | 低于它开始累计静音 | 尾巴太长调大，句子被切碎调小 |
| 静音挂起 `VAD_HANG_MS` | 280 ms | 静音多久算一段结束 | 说话停顿多就调大 |
| 段首回退 `VAD_PRE_MS` | 300 ms | 起点往前多留 | 吃字就调大 |
| 段尾保护 `VAD_GUARD_MS` | 100 ms | 终点往后多留 | 一般不动 |
| 最短段 `VAD_MIN_MS` | 200 ms | 更短的段丢弃 | 咳一声就出段时调大 |
| 单段最长 `VAD_MAX_MS` | 30000 ms | 超过强制切段 | 必须小于环形缓冲（60 s），否则段音频会被覆盖 |
| 起段峰值 `VAD_PEAK_OPEN` | 500 | 起段还要求峰值够大 | 底噪大、误触发多就调大 |
| 维持峰值 `VAD_PEAK_ACTIVE` | 400 | 段进行中的峰值要求 | 段尾拖太长就调大 |

采音参数在 `menuconfig → 诊录助手-采音配置`（引脚、增益）。

## 五、日志怎么看

正常启动：

```
I (865) audio_in: init ok: 16000 Hz, bclk=5 ws=4 din=6, gain=0 dB, hp=80 Hz
I (872) vad: init: enter=9.0 exit=6.0 dB, hang=14帧, pre=15帧, min=10帧, peak=500/400
I (880) segmap: init: 16000 Hz, 最多 512 段/会话
I (885) app: 开始采音，20 ms/帧
```

说话时出段：

```
I (9094)  app: 段 #0  [ 6.10 s →  8.02 s]  时长 1.92 s  asr_offset     0 ms
I (12814) app: 段 #1  [10.04 s → 11.74 s]  时长 1.70 s  asr_offset  1920 ms
```

每 10 秒两行统计：

```
I (10914) app: 统计: 帧 502 | 语音占比 13.1% | 段数 1 | 噪声底 -70.0 dB | 段表 1 条 / 总时长 1920 ms
I (10915) app: 链路: 采样 160640 | 时间偏差 +2 ms | 段发送 1 / 丢弃 0
```

第二行是健康检查：

- **时间偏差**：真实时间与「采样数 ÷ 16」之差。持续为正说明有样本没读到（DMA 溢出/读超时），此时段表时间戳会整体偏早；超过 ±200 ms 会单独告警
- **段发送 / 丢弃**：队列满或环形缓冲覆盖时会累加"丢弃"，正常演示应该一直是 0

排障对照：

| 现象 | 含义 |
|---|---|
| `噪声底 -100.0 dB`、`语音占比 0%` | 麦克风没信号：查 VDD/GND/SCK/WS/SD |
| 一段几十秒不断开 | 底噪太高：调大 `VAD_EXIT_DB` 或 `VAD_PEAK_ACTIVE` |
| 一句话被切成几段 | 门限太狠：调小 `VAD_EXIT_DB`，或调大 `VAD_HANG_MS` |
| 一直不出段 | 门限太高：调小 `VAD_ENTER_DB` / `VAD_PEAK_OPEN` |
| 日志里 `10 秒内没读到样本` | I2S 没数据：查接线与供电 |

## 六、段表格式（交给上传模块用）

每段 24 字节，大端：

| 偏移 | 字段 | 说明 |
|---|---|---|
| 0 | `seg_id` (u16) | 会话内段号 |
| 2 | `flags` (u16) | 预留 |
| 4 | `orig_start_sample` (u64) | 原始时间轴起点（采样数） |
| 12 | `sample_count` (u32) | 本段采样数 |
| 16 | `asr_offset_ms` (u32) | 在拼接音频里的偏移（毫秒） |
| 20 | `reserved` (u32) | 预留 |

**时间轴约定**：`orig_start_sample` 是原始录音的绝对采样位置；`asr_offset_ms` 是"把各段拼起来送给 ASR"时的累计偏移，由累计采样数换算，不用浮点累加，长会话不漂移。

## 七、下一步

1. 把段音频经串口传到电脑（PSRAM 环形缓冲 + 二进制帧），落 WAV
2. 上位机收段 → 调 `tools/asr/asr.py` → 验证端到端
3. 评测集（安静/嘈杂/快慢语速各若干），用 `tools/eval` 出指标

## 八、踩过的坑（别再踩）

- 中文路径会让 ESP-IDF 的 `export.ps1` 导出乱码 PATH → 装到纯英文路径
- `sdkconfig.defaults` 里有中文注释会被 kconfgen 按 GBK 解码报错 → 保持 ASCII
- gcc / ccache 默认写 `C:\Users\...\Temp`、`...\ccache`，权限不足会编译失败 → 指到项目内 `.tmp`
- xtensa 上 `uint32_t` 是 `long unsigned int`，日志格式必须用 `PRIu32`/`PRId64`，否则 `-Werror=format`
- IDF 5.1 的 S3 I2S 没有 `msb_right` 字段，左对齐用 `left_align`
- `main` 组件用 `esp_timer` 必须在 `CMakeLists.txt` 的 `PRIV_REQUIRES` 里声明
