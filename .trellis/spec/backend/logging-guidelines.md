# 日志规范

> 项目日志现状几乎空白。Flask 版无任何 logging，FastAPI 版仅 smart_import_service 使用 Python 标准 logging。

---

## 现状

- Flask 版（`backend/routes/`、`backend/services/`）：**零 logging**，错误仅通过 HTTP 响应返回前端
- FastAPI 版（`backend/app/services/`）：仅 `smart_import_service.py` 使用 logging
- 独立脚本：用 `print()` 临时替代

---

## 唯一使用 logging 的文件

```python
# backend/app/services/smart_import_service.py 行11-42
import logging

logger = logging.getLogger(__name__)

# 行42
logger = logging.getLogger(__name__)

# 行333
logger.error("Chunk %d 解析失败: %s", chunk.chunk_no, exc)

# 行602
logger.info("题库 %d 已存在相同题目 (id=%d)，跳过写入", bank_id, existing.id)
```

这是全后端唯一正确使用 `logging` 模块的文件。

---

## print() 临时替代

```python
# backend/scripts/import_iapp_glossary.py 行87-95
def main():
    print('正在从 IAPP 获取隐私术语表...')
    terms = fetch_glossary_terms()
    print(f'获取到 {len(terms)} 个术语')
    ...
    print(f'导入完成：新增 {added} 个，跳过 {skipped} 个已存在术语')
```

---

## 推荐模式

与 `smart_import_service.py` 保持一致：

```python
import logging

logger = logging.getLogger(__name__)
```

- 错误日志：`logger.error("...")`
- 关键业务事件：`logger.info("...")`
- 不使用 `print()`，不依赖 uvicorn 日志输出业务信息

---

## 当前缺陷

- 所有 Flask 路由和服务的错误仅通过 HTTP 响应返回，服务端无任何持久化记录
- 外部 API 调用（AI 翻译等）失败时无日志，只能从前端错误信息反推
- Worker 进程虽有 status_message 字段记录状态，但不走标准 logging

---

## 长 Worker 任务的关键节点 logger 约定

后台 worker（`smart_import_service` 等长任务）涉及重试、降级、心跳、去重等异步分支，单纯的"开始/失败"日志无法回溯具体路径。约定以下 5 类节点必须有 logger（实例：`smart_import_service.py`）：

| 节点 | 级别 | 触发位置 | 字段 |
|------|------|---------|------|
| 重试前 | `warning` | L1 retry sleep 之前 | `chunk_no`, `retry_count`, 异常类型与消息 |
| 降级入口 | `warning` | L2 单题降级开始 | `chunk_no`, 总段数 |
| 预算超时 kill | `warning` | L2 累计耗时超 budget | `chunk_no`, 已处理段数, 跳过段数 |
| Heartbeat 失败 | `warning` | `heartbeat_job` 抛异常的 try/except 内 | `bg_job.id`, 异常类型 |
| 去重命中 | `info` | DUPLICATE 行 add 前 | `import_job_id`, `source_question_no`, `reason` |

理由：

- **不淹没异常**：heartbeat 失败仅 warning 不 raise，避免压住原 chunk 异常的 stack trace
- **可重放轨迹**：5 类节点 + chunk_no 即可在事后从日志回放整 chunk 走的是 `parsed` / `parsed_retry` / `parsed_fallback` / `parsed_partial` 哪条路径
- **运维侧验证**：与 `chunk.issues_json` / `reconciliation` 形成双源，DB 字段可信但不实时；logger 实时但易丢

详见 [import-pipeline.md](./import-pipeline.md) Scenario A/B/C。
