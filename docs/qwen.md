# 千问病历草稿接入

当前支持阿里云百炼 OpenAI 兼容 Chat Completions 接口。默认保持 mock，不配置密钥时仍可演示。仅允许虚构病例；本项目尚无真实患者数据所需的权限隔离、审计和数据管理能力。

## 配置

1. 在阿里云百炼控制台确认业务空间、地域、模型权限和该业务空间的 OpenAI 兼容 Base URL。密钥与地域/业务空间需匹配。
2. 将 `backend/.env.example` 复制为 `backend/.env`，在本机配置以下变量。`backend/.env` 已加入 `.gitignore`；不要将真实密钥写进示例文件、前端、日志、聊天或仓库。

```ini
ZHENLU_DRAFT_PROVIDER=qwen
ZHENLU_QWEN_BASE_URL=https://<实际业务空间ID>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
ZHENLU_QWEN_MODEL=qwen3.7-plus
ZHENLU_QWEN_API_KEY=<本机填写密钥>
ZHENLU_QWEN_TIMEOUT_SECONDS=120
```

模型也可设为 `qwen3.8-flash`。本示例为北京地域格式，请以百炼控制台实际提供的地址为准，替换尖括号内容。服务端会追加 `/chat/completions`，也接受完整的 Chat Completions 地址。远程地址要求 HTTPS；仅本机测试允许 HTTP。要恢复离线演示，将 `ZHENLU_DRAFT_PROVIDER` 改回 `mock` 并重启后端。

3. 启动后端及前端，创建虚构会话，点击“手动录入问诊内容”，每行输入一段，保存后点击“生成病历草稿”。音频可选。生成前界面会提示问诊文字将发送给模型服务。

本机也可以通过系统环境变量或密钥管理工具注入 `ZHENLU_QWEN_API_KEY`；不要把实际密钥写入脚本或终端历史。

## 处理方式

- 按配置调用指定模型，不在启动时请求外部服务；只有点击生成/重新生成时才发送当前会话的问诊段落、段落 ID 和说话人，不发送会话名、患者编号或音频文件。问诊文字本身可能含敏感信息。
- 使用五字段 JSON Schema，要求内容来自原文、未提及信息写“未提及”，并引用有效句子 ID。服务端拒绝缺失字段、错误类型、无来源的非空字段、无效来源或截断的响应；不会把原始模型响应或密钥写进错误提示。
- 模型引用了有效句子，不代表句子足以支持结论。结果可能遗漏、误解或虚构，必须由医生逐项核对；系统不生成诊断或治疗建议。
- 模型失败可重试；重新生成失败或并发版本冲突时保留既有草稿和医生修改。模拟转写或手动演示文本经过真实模型生成后，确认文本仍标记模拟流程。
- 目前为同步请求，设置超时且不自动重试。长请求、断电恢复、排队、限流、费用统计尚未完善；模型调用可能产生费用。当前没有对已下载的第三方病例自动调用或上传模型的功能。

## 官方资料

- [阿里云百炼文本模型](https://help.aliyun.com/zh/model-studio/text-generation-model)
- [结构化输出与 JSON Schema](https://help.aliyun.com/zh/model-studio/qwen-structured-output)
- [OpenAI 兼容 Chat Completions](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions)
