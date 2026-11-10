# 诊录助手 SQLite 数据库原型

## 1. 项目定位

本目录是“诊录助手”项目的独立 SQLite 数据库原型，主要用于展示轻量化数据库的数据组织方式、核心业务模块和基础测试流程。

本原型使用 Python 标准库中的 `sqlite3` 操作 SQLite 数据库，不依赖额外的数据库服务。

**需要说明：**

- 本原型是独立数据库实现，不是主项目现有数据库层的替换版本。
- 主项目现有后端使用 FastAPI 和 SQLAlchemy，本原型目前尚未接入现有 API、后端 ORM 模型或前端。
- 本原型主要用于数据库结构设计、功能验证和方案展示，不能直接视为已经完成生产部署的数据库系统。
- 演示数据均为虚构数据，不应将真实患者隐私数据放入本原型。

## 2. 数据库设计

数据库围绕机构、用户、问诊、语音转写和结构化病历等业务环节组织数据。

当前包含以下 9 张主要数据表：

| 数据表 | 主要用途 |
|---|---|
| organizations | 机构信息 |
| users | 机构用户及角色信息 |
| sessions | 问诊会话信息 |
| audio_chunks | 音频分片索引及相关元数据 |
| transcript_sentences | 语音转写文本及句子信息 |
| record_versions | 病历版本记录 |
| record_fields | 结构化病历字段 |
| field_sources | 病历字段来源追踪 |
| operation_logs | 业务操作记录 |

数据库通过主键、外键、约束、索引和触发器维护基础数据关系与完整性。

## 3. 目录结构

主要文件说明：

- `schema.sql`：数据库表结构、约束、索引和触发器。
- `db.py`：SQLite 数据库连接和外键设置。
- `init_db.py`：数据库初始化。
- `seed_demo.py`：生成虚构演示数据。
- `organization.py`、`user.py`：机构和用户管理。
- `session.py`：问诊会话管理。
- `audio_chunk.py`：音频分片索引管理。
- `transcript.py`：语音转写管理。
- `medical_record.py`：结构化病历查询。
- `record_writer.py`：病历版本写入。
- `operation_log.py`：操作日志管理。
- `test_*.py`：各模块及集成测试。
- `API.md`：模块函数接口说明。
- `scripts/create_test_databases.py`：创建独立测试数据库。

## 4. 环境要求

- Python 3
- Python 标准库 `sqlite3`
- Windows PowerShell 或其他能够运行 Python 的环境

本原型不需要单独安装 SQLite 数据库服务，也不需要额外安装第三方 Python 依赖。

## 5. 初始化本地演示数据库

在本目录打开终端，执行：

```powershell
python init_db.py
python seed_demo.py
```

## 6. 测试方法

测试应在本目录（包含 `schema.sql` 和 `scripts` 文件夹的目录）中执行，并使用独立测试数据库，避免影响正式演示数据库。

### 6.1 创建测试数据库

```powershell
python scripts/create_test_databases.py
```

### 6.2 模块测试

指定模块测试数据库：

```powershell
$env:DIAGNOSIS_DB_PATH = (Join-Path (Get-Location) "diagnosis_final_test.db")
python seed_demo.py
```

然后依次执行：

```powershell
python test_org_user.py
python test_session.py
python test_transcript.py
python test_audio_chunk.py
python test_medical_record.py
python test_operation_log.py
```

### 6.3 集成测试

集成测试使用另一个独立数据库，不需要预先执行 `seed_demo.py`。

```powershell
$env:DIAGNOSIS_DB_PATH = (Join-Path (Get-Location) "diagnosis_integration_test.db")
python test_integration.py
Remove-Item Env:DIAGNOSIS_DB_PATH
```

### 6.4 已记录的测试结果

此前的本地测试记录如下：

| 测试模块 | 已记录的测试项数量 |
|---|---:|
| 机构与用户 | 10 |
| 问诊会话 | 10 |
| 语音转写 | 8 |
| 音频分片 | 10 |
| 结构化病历 | 11 |
| 操作日志 | 9 |
| 合计 | 58 |

此前记录的集成测试包含 12 个执行步骤，均已通过。

以上数据是此前的本地验证记录，不代表本次错误目录下的测试全部通过。实际结果以在干净测试数据库中重新运行的结果为准。

## 7. 当前实现范围与限制

1. **认证与权限控制尚不完整**：数据库包含机构、用户和角色等基础信息，但尚未构建完整的登录认证和授权体系。
2. **机构隔离仍需后端配合**：机构标识等上下文必须由可信后端确定，不能直接信任客户端传入的机构标识。
3. **音频存储尚未完整实现**：当前音频分片模块主要管理分片索引和相关元数据，不等同于完整的音频上传、文件存储及校验系统。
4. **操作日志不具备防篡改审计能力**：当前日志属于数据库中的普通业务记录，不应视为不可修改的安全审计系统。
5. **生产运维能力尚未完善**：数据保留、删除策略、备份恢复和生产环境安全配置仍需进一步设计。
6. **尚未完成主项目集成**：当前原型未与主项目现有的 FastAPI、SQLAlchemy 模型、API 路由和前端页面完成对接。

本原型适合用于数据库设计展示、功能验证和后续集成开发参考，不应直接用于真实患者业务数据。

## 8. 后续集成方向

如果后续选择将本原型纳入主项目，需要进一步完成：

- 将数据库结构与主项目 SQLAlchemy ORM 模型统一。
- 根据主项目 API 设计调整数据访问接口。
- 建立统一的数据迁移和初始化机制。
- 完善机构隔离、用户认证和权限控制。
- 补充音频文件管理、数据备份和安全审计能力。
- 与现有前端及后端业务流程进行联调。

在完成上述工作之前，本目录应作为独立的 SQLite 数据库原型保留，不直接覆盖主项目现有的数据访问代码。