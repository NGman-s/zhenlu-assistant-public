
# 诊录助手数据库接口文档

版本：V1.0

## 1. 通用说明

所有数据库接口均基于 Python sqlite3 实现。

数据库连接统一使用：

```python
from db import get_connection
```

接口参数中涉及问诊记录时，原则上同时使用：

- org_id：机构编号
- session_id：问诊编号

这样可以限定数据查询范围。

## 2. 机构管理 organization.py

### 创建机构

```python
create_organization(org_id, org_name)
```

参数：
- org_id：机构编号
- org_name：机构名称

返回：机构信息字典。

### 查询机构

```python
get_organization(org_id)
```

返回：机构信息字典；不存在时返回 None。

### 查询机构列表

```python
list_organizations(include_inactive=False)
```

参数：
- include_inactive：是否包含停用机构。

### 修改机构状态

```python
set_organization_status(org_id, is_active)
```

参数：
- is_active：True 表示启用，False 表示停用。

## 3. 用户管理 user.py

### 创建用户

```python
create_user(
    user_id,
    org_id,
    username,
    display_name,
    role="doctor"
)
```

role 支持：
- doctor：医生
- admin：管理员

注意：该接口只管理用户资料，不负责密码和登录认证。

### 查询用户

```python
get_user(user_id, org_id)
```

必须同时提供用户编号和机构编号。

### 查询用户列表

```python
list_users(
    org_id,
    role=None,
    include_inactive=False
)
```

可以按机构和角色筛选。

### 修改用户状态

```python
set_user_status(user_id, org_id, is_active)
```

## 4. 问诊管理 session.py

### 创建问诊

```python
create_session(
    session_id,
    org_id,
    doctor_id,
    status="recording"
)
```

创建问诊必须指定机构和医生。

支持状态：
- recording
- processing
- reviewing
- completed
- cancelled

### 查询问诊

```python
get_session(org_id, session_id)
```

返回问诊、机构和医生信息。

### 修改问诊状态

```python
update_session_status(
    org_id,
    session_id,
    status
)
```

### 查询问诊列表

```python
list_sessions(
    org_id,
    doctor_id=None,
    status=None,
    limit=100
)
```

支持按医生、问诊状态筛选。

## 5. 语音转写管理 transcript.py

### 批量保存转写

```python
save_transcripts(
    org_id,
    session_id,
    sentences
)
```

sentences 数据格式：

```python
[
    {
        "sentence_no": 1,
        "content": "我咳嗽三天了。",
        "start_ms": 0,
        "end_ms": 2500
    }
]
```

返回：成功保存的句子数量。

### 查询全部转写

```python
get_transcripts(org_id, session_id)
```

返回：转写记录列表。

### 根据时间定位原文

```python
find_transcript_at_time(
    org_id,
    session_id,
    time_ms
)
```

返回：对应转写句子；没有匹配结果时返回 None。

采用左闭右开时间区间。

## 6. 音频分片管理 audio_chunk.py

### 保存分片

```python
save_audio_chunk(
    org_id,
    session_id,
    seq,
    sample_start,
    sample_count,
    sample_rate,
    codec,
    storage_path,
    payload_len,
    checksum,
    upload_status="pending"
)
```

主要参数：
- seq：分片编号，从1开始。
- sample_start：原始录音的起始采样位置。
- sample_count：本分片采样数量。
- sample_rate：采样率。
- codec：编码格式。
- storage_path：音频文件路径。
- payload_len：载荷长度。
- checksum：校验信息。

返回：音频分片记录。

### 查询音频分片

```python
get_audio_chunks(org_id, session_id)
```

### 根据时间定位音频

```python
find_audio_chunk_at_time(
    org_id,
    session_id,
    time_ms
)
```

### 更新上传状态

```python
update_audio_chunk_status(
    org_id,
    session_id,
    seq,
    new_status
)
```

允许的状态转换：

- pending → uploaded
- pending → failed
- uploaded → acknowledged
- uploaded → failed
- failed → uploaded

acknowledged 为终态。

注意：该模块管理的是音频元数据，不负责真正上传和读取音频文件。

## 7. 病历查询 medical_record.py

### 查询完整病历

```python
get_medical_record(org_id, session_id)
```

返回数据包括：

- 问诊信息
- 医生信息
- 全部病历版本
- 病历字段内容
- 字段原始转写来源
- 来源句子的起止时间

找不到问诊时返回 None。

### 查询单独版本

```python
get_record_version(
    org_id,
    session_id,
    version_no
)
```

找不到指定版本时返回 None。

## 8. 病历写入 record_writer.py

### 保存病历版本

```python
save_medical_record_version(
    org_id,
    session_id,
    version_no,
    version_type,
    created_by,
    fields
)
```

版本类型：

- AI草稿
- 医生修改版
- 医生确认版

AI 草稿的 created_by 使用 None。

医生版本必须提供同一机构内有效的医生账号编号。

fields 格式：

```python
[
    {
        "field_name": "主诉",
        "field_value": "咳嗽三天。",
        "information_status": "recorded",
        "source_sentence_nos": [1]
    },
    {
        "field_name": "既往史",
        "field_value": None,
        "information_status": "not_mentioned",
        "source_sentence_nos": []
    }
]
```

信息状态：
- recorded：有记录的信息
- not_mentioned：未提及
- explicitly_denied：明确否认

返回：新建的 version_id。

每次成功保存病历版本，还会自动创建一条操作日志。

## 9. 操作日志 operation_log.py

### 创建操作日志

```python
create_operation_log(
    org_id,
    action,
    target_type,
    target_id=None,
    session_id=None,
    user_id=None,
    details=None
)
```

details 支持字典、列表、字符串或 None。

### 查询单条日志

```python
get_operation_log(org_id, log_id)
```

### 查询日志列表

```python
list_operation_logs(
    org_id,
    session_id=None,
    user_id=None,
    action=None,
    limit=100
)
```

### 事务内部日志写入

```python
insert_operation_log(conn, ...)
```

用于其他业务模块在自己的数据库事务中写入操作日志，不单独提交事务。

## 10. 异常处理约定

常见异常：

- ValueError：输入数据不合法、记录不存在或违反业务约束。
- FileNotFoundError：数据库文件不存在。
- FileExistsError：初始化时发现正式数据库已存在。
- sqlite3.Error：底层数据库错误，未被业务接口转换时可能直接抛出。

业务调用方应当捕获异常，并记录错误日志。

## 11. 安全与部署说明

1. 所有机构业务查询都需要提供机构编号。
2. 机构编号应由后端根据已认证用户的身份确定，不能直接信任客户端传入值。
3. 数据库不负责用户登录认证。
4. 音频文件不直接存放在 SQLite 中。
5. 病历旧版本不能直接覆盖。
6. 操作日志不应作为唯一审计或安全保障手段。
7. 生产环境部署前需要进行权限、并发、备份及数据安全验证。
