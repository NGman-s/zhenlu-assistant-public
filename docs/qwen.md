# 千问病历草稿接入

当前支持阿里云百炼 OpenAI 兼容 Chat Completions 接口。病历生成和会话问答使用千问，需要配置有效地址及密钥。仅允许虚构病例；本项目尚无真实患者数据所需的权限隔离、审计和数据管理能力。

## 配置

1. 在阿里云百炼控制台确认业务空间、地域、模型权限和该业务空间的 OpenAI 兼容 Base URL。密钥与地域/业务空间需匹配。
2. 将 `backend/.env.example` 复制为 `backend/.env`，在本机配置以下变量。`backend/.env` 已加入 `.gitignore`；不要将真实密钥写进示例文件、前端、日志、聊天或仓库。

```ini
ZHENLU_DRAFT_PROVIDER=qwen
ZHENLU_QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
ZHENLU_QWEN_MODEL=qwen3.7-plus
ZHENLU_QWEN_API_KEY=<本机填写密钥>
ZHENLU_QWEN_TIMEOUT_SECONDS=45
```

模型也可设为 `qwen3.8-flash`。本示例使用百炼北京地域的 DashScope 兼容地址；密钥须属于同一地域。也可使用控制台“业务空间管理”中提供的专属 API Host，但要复制完整域名，而不是自行拼写空间名称。服务端会追加 `/chat/completions`，也接受完整的 Chat Completions 地址。远程地址要求 HTTPS；仅本机测试允许 HTTP。环境变量优先于 `.env`，修改配置后需重启后端。

3. 启动后端及前端，创建虚构会话，点击“手动录入问诊内容”，每行输入一段，保存后点击“生成病历草稿”。音频可选。生成前界面会提示问诊文字将发送给模型服务。

本机也可以通过系统环境变量或密钥管理工具注入 `ZHENLU_QWEN_API_KEY`；不要把实际密钥写入脚本或终端历史。

## 处理方式

- 按配置调用指定模型，不在启动时请求外部服务；只有点击生成/重新生成时才发送当前会话的问诊段落、段落 ID 和说话人，不发送会话名、患者编号或音频文件。问诊文字本身可能含敏感信息。
- 使用五字段 JSON Schema，要求内容来自原文、未提及信息写“未提及”，并引用有效句子 ID。服务端拒绝缺失字段、错误类型、无来源的非空字段、无效来源或截断的响应；不会把原始模型响应或密钥写进错误提示。
- 模型引用了有效句子，不代表句子足以支持结论。结果可能遗漏、误解或虚构，必须由医生逐项核对；系统不生成诊断或治疗建议。
- 模型失败可重试；重新生成失败或并发版本冲突时保留既有草稿和医生修改。手动录入直接进入千问生成流程；历史记录按原始来源标记展示。
- 已支持持久化后台任务、幂等编号、过期任务恢复和逐次调用用量记录，原同步接口保持兼容。非思考模式、temperature=0，默认总时限 45 秒、单次 20 秒、最多重试一次；仅临时网络故障、超时、限流和服务端故障自动重试。结构和来源错误不重试。配置实际单价后估算费用，未知费用明确保留。详见[后端联调说明](后端开发进度与联调.md)。
- 当前会话问答和角色整理可分别配置为 qwen，复用上述模型连接；提交这些任务也会发送本次会话资料。没有对第三方病例自动调用或上传模型的功能。

## 官方资料

- [阿里云百炼文本模型](https://help.aliyun.com/zh/model-studio/text-generation-model)
- [结构化输出与 JSON Schema](https://help.aliyun.com/zh/model-studio/qwen-structured-output)
- [OpenAI 兼容 Chat Completions](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions)
