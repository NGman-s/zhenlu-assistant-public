# 诊录助手（第一阶段模拟原型）

面向医生审核的语音病历流程原型：建立问诊会话、上传模拟音频、查看逐句转写、
生成结构化病历草稿、由医生修改并确认，最后复制为纯文本。

当前阶段不接入真实患者数据。默认语音识别与草稿生成均使用 mock 服务；另提供可选的阿里云百炼千问草稿接口，配置后会将问诊文字发送给该服务。没有 API 密钥也可使用模拟流程。

## 已实现

- 会话：创建、列表、状态、刷新后恢复已保存内容。
- 音频：上传合法音频到本地目录、播放、格式与大小校验。
- 转写：逐句展示、模拟标识、来源定位所需句子 ID 与可选毫秒时间区间。
- 手动录入：可直接按行填写问诊内容，无需上传音频；默认生成手动模板，配置千问后可生成带来源的草稿。
- 草稿：主诉、现病史、既往史、用药史、过敏史五个字段；“未提及”原样展示。
- 审核：字段编辑、显式保存、revision 并发保护、确认锁定、确认版本快照。
- 修改保护：重新生成时，医生修改过的字段不被覆盖，系统新结果作为建议展示，需手动采纳。
- 来源关联：点击字段来源可高亮原文；示例音频可定位播放；无可靠时间时不伪造。
- 复制：仅确认后可复制纯文本，并带模拟数据说明。
- 错误提示：上传为空/格式不支持/超限、步骤顺序错误、会话不存在、确认后修改、版本冲突等。

不在本阶段范围：正式硬件授权、实时转写、HIS 写入、医疗建议、多用户权限、真实 ASR。

## 技术栈

- 前端：React 19、TypeScript、Vite 6、原生 CSS。
- 后端：Python 3.11+、FastAPI、SQLAlchemy、SQLite。
- 音频：本地文件存储；示例音频使用 Windows 中文语音合成生成。
- 草稿提供方：默认 mock，可配置千问兼容接口。

## 项目目录

```text
.
├─ backend/
│  ├─ app/
│  │  ├─ providers/          # 转写与草稿协议、mock 实现、示例数据加载
│  │  ├─ routers/            # 会话、音频、转写、草稿、确认、演示接口
│  │  ├─ services/           # 上传存储、状态流转、确认与纯文本导出
│  │  ├─ config.py           # 环境配置
│  │  ├─ models.py           # SQLite 数据模型
│  │  ├─ schemas.py          # 请求/响应结构
│  │  ├─ serializers.py      # API 序列化与来源解析
│  │  └─ main.py             # FastAPI 应用与启动装配
│  ├─ tests/                 # 后端自动化测试
│  ├─ data/                  # 运行时数据库与上传音频（不提交）
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/
│  ├─ src/
│  │  ├─ components/         # 侧栏、上传、转写、草稿、来源、弹窗等
│  │  ├─ App.tsx
│  │  ├─ api.ts
│  │  ├─ types.ts
│  │  ├─ utils.ts
│  │  └─ styles.css
│  ├─ package.json
│  └─ vite.config.ts
├─ sample-data/              # 两套虚构问诊 JSON + 合成 WAV
├─ scripts/                  # 合成示例音频的可选脚本
├─ docs/api.md               # 接口说明
└─ README.md
```

## 环境要求

- Python 3.11 或更高（使用了 `StrEnum`），已在 Python 3.12 验证。
- Node.js 20 或更高，已在 Node 24 验证。
- npm 10 或更高。
- 操作系统不限；重新生成示例音频的脚本需要 Windows PowerShell 中文语音。
- 不需要任何外部 API 密钥。

## 快速启动

### 后端

在项目根目录执行：

```powershell
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

macOS / Linux：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

检查：<http://127.0.0.1:8000/api/health>；交互式接口文档：<http://127.0.0.1:8000/docs>。

### 前端

另开终端：

```bash
cd frontend
npm install
npm run dev
```

如果 npm 官方源访问较慢，可使用 `npm install --registry=https://registry.npmmirror.com`。

打开 <http://127.0.0.1:5173>。Vite 已将 `/api` 代理到
`http://127.0.0.1:8000`，因此页面无需配置额外后端地址。

如后端使用了其他端口，请同步修改 `frontend/vite.config.ts` 的代理目标；
如前端使用其他端口，请同步修改 `backend/.env` 中的 `ZHENLU_CORS_ORIGINS`。

## 模拟流程

除了示例转写，也可直接选择“手动录入问诊内容”，每行输入一段。默认创建病历模板并逐项填写；配置千问后可生成草稿。手动内容保存后暂不支持编辑，不提供音频时间定位；所有字段必须逐项核对。此流程仅供虚构病例演示。

1. 点击“新建问诊会话”，使用虚构称呼创建会话（例如“演示患者 A”）。
2. 在“没有本地音频？”区域点击：
   - “呼吸系统问诊 · 信息较完整”：演示完整来源追溯、用药和过敏史。
   - “呼吸系统问诊 · 信息缺失”：演示三个字段显示“未提及”。
   也可以选择本地音频手动上传。
3. 点击“开始模拟转写”，查看逐句对话。页面显示“模拟转写”、提供方与提示语；
   示例音频带有合成时记录的真实时间区间。
4. 点击“生成结构化草稿（模拟）”，查看五个字段。
5. 点击字段右侧“查看来源”，右侧/下方来源面板展示原文，转写中对应句子高亮；
   示例音频可“定位播放”。
6. 修改任一字段后点击“保存修改”。字段标记为“医生修改”，自动草稿原值可在
   “查看系统原始草稿”中对比。
7. 点击“重新生成（模拟）”：系统字段更新；医生修改保留，新结果作为“系统新建议”
   显示。点击“填入建议值”后再保存，才会计入医生当前内容。
8. 保存全部修改后点击“确认病历”，在弹窗中确认。确认后草稿锁定，生成只读确认版本。
9. 点击“复制病历文本”，得到带患者、会话编号、确认时间、五个字段和模拟说明的纯文本。
10. 刷新页面，会话、音频、转写、草稿、确认版本和当前选择的会话都会恢复。

## 接口、数据与存储

- 完整接口说明：[docs/api.md](docs/api.md)。
- 两套虚构病例与音频：[sample-data/README.md](sample-data/README.md)。
- SQLite 数据库：`backend/data/zhenlu.db`。
- 上传音频：`backend/data/uploads/{session_id}/`。
- 两份文件都在运行时生成，已被 `.gitignore` 排除。

重置演示数据（先停止后端，确认无需保留任何会话）：

```powershell
Remove-Item backend\data\zhenlu.db
Get-ChildItem backend\data\uploads -Exclude .gitkeep | Remove-Item -Recurse
```

## 实现选择与取舍

- **一次会话一段音频**：第一阶段不做分片、重传或多音频拼接。音频成功后不可替换。
- **显式步骤按钮**：上传、转写、生成草稿分别触发，便于观察状态和错误；mock 处理为同步。
- **医生修改保护**：字段记录 `origin`（`ai`/`doctor`）、`ai_value` 和编辑时间；
  重新生成只更新 AI 字段，医生字段的新结果只写入 `suggestion`。确认时保存独立快照并锁定。
- **revision 乐观锁**：保存、重生成、确认都携带 `expected_revision`，避免旧页面静默覆盖。
- **来源校验**：草稿服务返回的句子 ID 必须属于当前转写，服务端丢弃不存在的 ID。
- **时间戳策略**：仅在上传文件与内置示例音频内容校验一致时使用生成脚本记录的句子时间；其他上传的 mock 结果一律为
  `null`，界面显示“无可靠时间戳”，不会推测。
- **未保存保护**：切换或新建会话前提示未保存修改，刷新或关闭页面时由浏览器提示；版本冲突后保留页面输入，方便复制后刷新。
- **建议来源**：显式采纳系统建议时同时保存该建议对应的来源；手动编辑仍保留原草稿来源，并提示其不一定代表修改后的内容。
- **模拟标识**：转写、草稿、示例音频、复制文本和侧栏均明确标出模拟性质和提供方。
- **等待页面刷新**：选中的会话 ID 存储在 `localStorage`，刷新后恢复。
- **演示数据隔离**：所有姓名、病情和音频均为虚构；未接入任何真实患者数据源。

## 验证结果

在 2026-10-27 的开发环境中完成：

- 后端自动化测试覆盖：
  - 创建会话 → 上传示例音频 → 转写 → 生成草稿 → 编辑保存 → 重新生成 → 确认 → 复制文本；
  - “未提及”字段与来源为空、确认文本不出现“无”；
  - 医生修改经重新生成后不被覆盖，并生成显式建议；
  - 来源 ID 服务端校验；
  - 无可靠时间戳时不伪造；
  - 版本冲突、并发保存、确认后锁定、重新生成期间的并发修改、格式不支持、空文件、超限、重复上传；
  - 提供方失败后状态为 `failed` 且可重试。
- 前端：`npm run build` 通过 TypeScript 检查与生产构建。
- Chromium 实际页面验证：
  - 1440×1000 桌面布局：三栏审核区无横向溢出，页头、步骤、上传、转写、草稿、来源均可见；
  - 390×844 移动布局：单栏堆叠、无横向溢出；
  - 两套示例病例完整跑通，包括“未提及”、来源高亮、音频定位；
  - 手动选择有效音频、非法 `.txt` 上传错误提示；
  - 修改后保存、重新生成保护、确认、复制成功提示；读回的剪贴板文本包含患者、
    会话编号、五个字段、医生修改值和模拟说明；
  - 刷新后仍停留在先前选中的会话并恢复全部数据。

运行验证命令：

```powershell
cd backend
.venv\Scripts\python.exe -m pytest -q

cd ..\frontend
npm run build
```

## 已知问题与限制

- **mock ASR 不解析真实音频内容**：按文件名和内容校验匹配示例病例；其他上传得到默认虚构病例，
  并明确提示未匹配。接入真实 ASR 后才会基于音频内容识别。
- 示例音频由中文 TTS 合成，不是真实问诊录音，不具备临床效力。
- 只有示例音频有句子时间；真实上传的转写没有可靠时间信息，也不提供音频定位。
- 确认版本目前不可撤回或继续修订；需要修改只能新建会话。数据模型保存了版本号，
  但本阶段没有“重新开审”界面。
- 转写内容不可编辑；医生只能编辑结构化草稿。
- 单一音频、无分片/上传续传；处理为同步请求，没有后台队列；若进程在处理中退出，
  状态可能停留在 `transcribing`/`generating_draft`。
- 上传仅按扩展名校验，不验证真实音频内容，也不转码。演示文件未加密，无访问控制。
- 无登录、机构/医生/患者隔离、审计日志和数据删除流程；**不可用于真实患者数据**。
- 纯文本复制为单模板，没有逐字段复制和机构模板配置。
- 数据库表在启动时自动创建；已有 SQLite 数据库会在启用文字输入前迁移转写表。未引入完整的数据库迁移系统。
- 只在 Chromium 系浏览器完成交互验证，未测试 Safari 或 Firefox。

## 下一步接入真实 ASR 所需的信息

实现入口见 [backend/app/providers/base.py](backend/app/providers/base.py) 与
[backend/app/providers/registry.py](backend/app/providers/registry.py)。

接入真实 ASR 前需要确认：

1. 服务商、模型版本、接口地址和鉴权方式；密钥只能通过环境变量/密钥管理服务注入。
2. 支持的音频格式、采样率、大小、单段时长、并发和频率限制。
3. 是否返回句子级时间戳；若返回，需要明确采样位置到原录音毫秒的映射，并保留原音频
   用于回听。若不能保证可靠时间，保持 `start_ms`/`end_ms = null`。
4. 是否支持说话人分离；首版可不区分医生/患者，使用“未知”也可接受。
5. 超时、限流、错误码、重试与计费规则。真实调用往往不再是同步毫秒级，
   需要改为后台任务、轮询/回调、任务状态与失败恢复。
6. 录音告知同意、数据跨境/留存/删除、去标识化和供应商数据处理协议。
7. 需要将其实现为 `TranscriptionProvider`（返回逐句 `AsrResult`），在注册表中注册，
   并通过 `ZHENLU_ASR_PROVIDER` 切换。

千问接入见 [配置说明](docs/qwen.md)。模型只负责整理草稿；服务器校验结构和来源 ID，但无法仅凭来源 ID 保证事实正确，仍需医生逐项核对。

## 配置

复制 `backend/.env.example` 为 `backend/.env` 后按需调整：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ZHENLU_DATABASE_URL` | `backend/data/zhenlu.db` 的 SQLite URL | 数据库连接 |
| `ZHENLU_UPLOAD_DIR` | `backend/data/uploads` | 本地音频目录 |
| `ZHENLU_SAMPLE_DATA_DIR` | `sample-data` | 虚构病例目录 |
| `ZHENLU_MAX_AUDIO_MB` | `50` | 单段音频大小上限 |
| `ZHENLU_ASR_PROVIDER` | `mock` | 转写提供方 |
| `ZHENLU_DRAFT_PROVIDER` | `mock` | 草稿提供方：`mock` 或 `qwen` |
| `ZHENLU_QWEN_BASE_URL` | 空 | 百炼业务空间 OpenAI 兼容接口地址 |
| `ZHENLU_QWEN_MODEL` | `qwen3.7-plus` | 可切换为 `qwen3.8-flash` |
| `ZHENLU_QWEN_API_KEY` | 空 | 百炼密钥，仅后端使用 |
| `ZHENLU_QWEN_TIMEOUT_SECONDS` | `120` | 模型请求超时秒数 |
| `ZHENLU_MOCK_DELAY_SECONDS` | `0.35` | mock 处理延迟，便于观察处理中状态 |
| `ZHENLU_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 允许的前端源 |
| `ZHENLU_TIMEZONE_OFFSET_HOURS` | `8` | 确认文本时间显示时区 |

当前不包含任何密钥。请勿把真实密钥、真实患者信息或真实录音写入代码、环境变量示例或仓库。

本实现是第一阶段软件流程原型，不等同于完整产品或验收指标。

## USB 连接程序开发原型

Windows 下可先不接硬件，模拟插入设备启动工作台、拔出后等待并关闭本地服务。操作方法与限制见 [desktop/README.md](desktop/README.md)。当前只是设备检测及流程原型，并未实现设备授权或防复制。

设备身份验证的开发代码在 `firmware/device-key` 和 `desktop/device_identity.py`；开发板已完成原型验证，使用范围和限制见 [连接程序说明](desktop/README.md)。

病历草稿可选接入千问服务，默认为模拟模式；配置说明见 [docs/qwen.md](docs/qwen.md)。
