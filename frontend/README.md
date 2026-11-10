# 医生工作空间前端

React 19 + TypeScript + Vite，沿用项目原生 CSS。正式页面包含首页、新建问诊、三栏审核、病历记录、机构模板、设置和可选服务端登录页。没有嵌入本地演示账号、模拟认证、示例病例、合成音频、独立 HTML 演示包或测试数据。

## 启动与构建

```powershell
npm ci
npm run dev
npm run build
```

前端默认在 5173 端口运行；Vite 将 `/api` 代理到 `http://127.0.0.1:8000`。构建产物在 `dist/`，不提交到 Git。生产服务应同源提供页面与 `/api`；设备连接程序继续使用原构建路径。

## 页面与数据流

| 模块 | 行为 |
| --- | --- |
| `#home` | 文字 / 音频并列入口、后端实际待办和确认记录、继续会话 |
| `#new` | 创建会话后依次保存文字或上传 / 识别音频，再生成草稿；显示逐步进度；失败保留已建立会话，重试继续 |
| `#workbench` | 左原文与音频、中病历、右来源；小屏页签；编辑、建议比较、逐项核对、确认只读 |
| `#records` | 按状态筛选、按患者 / 编号 / 会话 ID 搜索、打开会话 |
| `#templates` | 字段映射、标题、顺序、启用开关、空值和换行、身份信息、另存模板 |
| `#settings` | 当前用户 / 单机运行状态、信息密度和模板入口 |

音频回听只在 `has_reliable_timestamps=true` 且来源起止时间有效时开放；时间值为 null 时不虚构 00:00。字段可关联多个来源，播放到对应终点自动暂停，支持整段播放和速度选择。服务器需支持音频 Range 请求；FastAPI 文件响应应保留这一行为。

草稿修改提交 `expected_revision`。409 冲突会显示服务器错误并保留医生尚未提交的文字，不自动覆盖或重试旧版本。确认前要求逐项核对与患者核对；后端确认成功后只读，复制导出仅使用 `latest_record`。浏览器复制失败时展示可选中的文本，TXT 文件在前端生成。

## 复用的已有后端接口

所有接口在 `src/api.ts`，不另设本地数据模拟层。

| 操作 | 请求 |
| --- | --- |
| 会话列表 / 详情 | `GET /api/sessions`、`GET /api/sessions/{id}` |
| 创建 | `POST /api/sessions`，`{patient_name, patient_ref}` |
| 上传音频 | `POST /api/sessions/{id}/audio`，multipart `file` |
| 音频识别 | `POST /api/sessions/{id}/transcript` |
| 文字原文 | `POST /api/sessions/{id}/transcript/manual`，`{text}` |
| 生成草稿 | `POST /api/sessions/{id}/draft` |
| 保存医生修改 | `PATCH /api/sessions/{id}/draft`，`{expected_revision, fields:[{field_key,value,accept_suggestion?}]}` |
| 重新生成 | `POST /api/sessions/{id}/draft/regenerate`，`{expected_revision}` |
| 确认 | `POST /api/sessions/{id}/confirm`，`{expected_revision}` |
| 设备 | `GET /api/device/status`，两秒轮询；断连暂停新建、生成与确认，保留保存能力 |

`src/types.ts` 保持后端既有类型。五个字段使用 `chief_complaint`、`present_illness`、`past_history`、`medication_history`、`allergy_history`；没有新增需后端猜测的字段 ID。

## 登录接口：预留契约，后端尚未实现

仓库目前运行在单机单用户模式，没有账号认证服务。默认 `VITE_AUTH_MODE=none` 保持可运行，界面显示“单机模式”，**不伪装成已登录医生，也没有本地密码验证**。

后端提供真实认证后，将 `frontend/.env.example` 复制到 `frontend/.env.local`，设置 `VITE_AUTH_MODE=server` 并重启 / 重建前端。启用后，前端先验证当前用户，未登录不读取会话；失败不会自动回退到单机模式。没有后端认证时启用此配置会显示登录服务不可用。

以下路径可通过对应 `VITE_AUTH_*_PATH` 配置调整，仅接受同源路径。它们是双方待对齐的契约，不是本次新增的后端路由：

| 配置 | 默认路径与请求 | 成功响应 |
| --- | --- | --- |
| `VITE_AUTH_ME_PATH` | `GET /api/auth/me` | 下述会话 JSON |
| `VITE_AUTH_LOGIN_PATH` | `POST /api/auth/login`，`{account,password}` | 下述会话 JSON，并由服务端设置会话 Cookie |
| `VITE_AUTH_LOGOUT_PATH` | `POST /api/auth/logout`，`{}` | `204 No Content`（推荐）或 JSON；服务端撤销会话 Cookie |

```json
{
  "user": {
    "id": "server-user-id",
    "name": "医生姓名",
    "institution": "机构名称",
    "role": "doctor"
  },
  "expires_at": "2030-01-01T00:00:00Z"
}
```

`expires_at` 为可选 ISO 时间；有值时前端按时间锁屏，无值时通过 HTTP 401 和页面恢复可见时的当前用户校验处理失效。密码和会话凭证不存入 localStorage / sessionStorage；用户身份保存在当前 React 内存中，刷新重新请求 `/me`。

推荐使用服务端 HttpOnly、SameSite 会话 Cookie；前端 `credentials: same-origin`。若后端下发可读 `csrftoken` Cookie，前端写请求携带 `X-CSRFToken`；服务端应实现 CSRF 校验，并与团队实际约定对齐。账号权限、机构与患者归属必须在所有会话、修改、确认及音频接口上由后端授权校验，前端模式开关不是权限边界。

401 或过期会隐藏工作空间、暂停音频，保留当前页面未保存的字段 / 表单 / 弹窗；原账号重新登录后恢复。关闭页面或刷新不会持久化未提交病历。退出前提醒未保存内容；服务端注销成功后卸载工作空间。

## 前端扩展与边界

- 模板使用 `localStorage`，存储键 `zhenlu.templates.{user.id}`；单机模式使用 `local-single-user`。只存模板配置，不存患者病历。尚无机构模板服务接口，不声称跨设备同步。
- 逐项“已核对”是当前页面状态，草稿修订后清空；没有新增后端审核字段。
- “保留医生内容”在本次审核中隐藏该建议，确认仍发送当前修订；后端目前没有单独驳回建议接口，该决定不会单独持久化。采用不同的建议值仍走已有 `accept_suggestion` 字段。
- 来源关联由后端返回，前端只读；没有把演示版的手工重绑来源功能伪装为已接通接口。
- API 返回的历史模拟记录仍显示原有来源标记，避免把历史模拟内容当成真实结果；没有新增模拟数据。
- 会话列表、详情、音频、原文、草稿和确认记录以服务端为准；测试登录版与离线演示文件留在开发者本机，不提交。

## 验证

`npm run build` 执行 TypeScript 严格检查与 Vite 打包。此次本机浏览器验证采用仓库接口形状的受控响应，覆盖文字 / 音频链路、生成失败续办、409 保留输入、模板导出、区间停止、确认只读以及服务端认证模式的 401 恢复；未调用付费 ASR / 大模型，不能代替真实供应商和认证服务联调。
