# 诊录助手

面向医生审核的问诊记录工作台。输入问诊文字或上传录音，通过 Fun-ASR 转写和千问模型生成五字段病历，关联原文来源，由医生修改、确认并复制。

## 快速启动

需要 Python 3.11+、Node.js 20+ 和 npm 10+。以下命令均使用 PowerShell，并从项目根目录开始执行。

### 1. 配置 .env 和 API Key

首次使用时，将 `backend/.env.example` 复制一份并命名为 `backend/.env`。已有 `.env` 时直接编辑该文件。

在 `.env` 中，将下面两个配置项 `=` 后的内容完整替换为自己的阿里云百炼 API Key，包括模板中的占位说明，保存文件。

```ini
ZHENLU_QWEN_API_KEY=你的千问APIKey
ZHENLU_FUN_ASR_API_KEY=你的Fun-ASR APIKey
```

千问负责生成结构化病历，Fun-ASR 负责音频转写。密钥需具有对应服务的调用权限，并与配置的接口地域、业务空间匹配。`.env` 存放本机密钥，已由 Git 忽略。

### 2. 启动后端

在第一个 PowerShell 窗口执行。首次使用需要创建虚拟环境并安装依赖。

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

后端健康检查为 [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)，接口文档为 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

### 3. 启动前端

另开一个 PowerShell 窗口，进入项目根目录后执行。首次使用需要安装依赖。

```powershell
Set-Location frontend
npm install
npm run dev
```

浏览器打开 [http://localhost:5173](http://localhost:5173)。前端将 `/api` 请求代理至后端的 `8000` 端口，使用期间保持两个终端运行。在各自终端按 `Ctrl+C` 可停止服务。

后续启动时，分别在 `backend` 和 `frontend` 目录执行上述最后一条启动命令即可。修改 `.env` 后需重启后端。

## 主要功能

- 创建和管理会话，刷新后恢复已保存的内容。
- 手动录入问诊文字，或上传录音并调用 Fun-ASR 获得逐句转写。
- 使用千问生成主诉、现病史、既往史、用药史、过敏史，附原文句子来源。
- 根据实际返回的时间戳定位播放录音，缺失时间保持为空。
- 编辑保存、revision 并发校验、重新生成建议、确认快照和纯文本复制。
- 后端提供对话角色整理、带来源和版本的会话问答、持久化任务、幂等请求、中断恢复和调用用量记录。
- Windows 连接程序支持 USB 检测及 ESP32-S3 签名验证，控制本地服务启停。

运行服务使用云端提供方。启动前需配置百炼密钥及接口地址，音频和问诊文字会发送至相应服务，调用按供应商规则计费。项目目前用于本机单用户开发验证，测试资料需具有相应处理授权。

## 技术栈与目录

- 前端使用 React 19、TypeScript、Vite 6 和原生 CSS。
- 后端使用 Python 3.11+、FastAPI、SQLAlchemy 和 SQLite。
- 音频保存在本机文件目录，数据库保存元数据、转写、草稿、来源和确认版本。

```text
backend/app/providers/   Fun-ASR、千问及显式角色规则
backend/app/routers/     会话、音频、病历、角色、问答和任务接口
backend/app/services/    工作流、版本保护、调度和导出
backend/tests/          自动化测试，独立替身及测试素材
frontend/src/           医生审核工作台
frontend/dist/          构建后供桌面连接程序使用的静态页面
desktop/                Windows 设备连接与签名验证
firmware/device-key/    ESP32-S3 身份验证固件
docs/                   接口与模型接入说明
```

## 配置说明

服务地址、密钥与地域、业务空间需匹配。角色整理可选择 `rules`，按明确前缀识别角色，或选择 `qwen`，根据文本推断并附依据。环境变量优先于 `.env`，修改后需要重启后端。配置校验失败会报告错误。

完整参数见 `backend/.env.example` 和 [千问配置说明](docs/qwen.md)。

## 使用流程

1. 新建问诊会话。
2. 选择手动录入，每行输入一段并保存，或上传音频后点击“开始转写”。
3. 点击“生成病历草稿”，等待千问返回五字段及来源。
4. 点击“查看来源”核对原文，有可靠时间戳时可以定位回听。
5. 编辑字段并保存。重新生成时，医生修改受到保护，新结果作为建议展示。
6. 确认病历，生成只读版本，再复制文本。

手动录入最多 200 个非空行、20,000 字符，保存后需要更正原文时另建会话。确认版本锁定，后续修改使用新会话。

## 存储与维护

默认数据库为 `backend/data/zhenlu.db`，音频位于 `backend/data/uploads/`。可通过 `ZHENLU_DATABASE_URL` 和 `ZHENLU_UPLOAD_DIR` 指定其他路径。历史记录的来源标记和确认快照随数据保存。

在 `backend` 目录运行维护命令。

```powershell
.\.venv\Scripts\python.exe -m app.maintenance check
.\.venv\Scripts\python.exe -m app.maintenance backup --output .\data\backups\manual.sqlite3
```

备份目标需使用新文件名，音频目录单独备份。SQLite 升级前自动创建一致性备份。

## 验证

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pytest -q
Set-Location ..
.\backend\.venv\Scripts\python.exe -m pytest -q desktop/tests
Set-Location frontend
npm run build
```

测试替身与录音素材独立放在 `backend/tests`，测试使用临时数据库及供应商协议响应替身。真实服务的质量、延迟和费用需通过已获授权的资料另行评测。

## 当前范围

- 页面已接入病历录入、转写、生成与审核。角色整理、会话问答和后台任务轮询提供后端接口供后续页面接入。
- Fun-ASR 使用实时 WebSocket 协议传输已上传音频，耗时接近音频时长。WAV 输入要求单声道 16-bit PCM，格式与超时参数需结合录音长度配置。
- 每会话保存一段音频，支持 SHA-256 校验和同文件重传去重。
- ESP32-S3 当前固件提供设备身份验证，采音及上传属于后续硬件联调工作。
- 多用户权限、审计、数据生命周期和生产部署属于后续交付内容。

接口说明见 [docs/api.md](docs/api.md)，设备使用见 [desktop/README.md](desktop/README.md)。
