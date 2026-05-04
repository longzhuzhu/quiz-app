# Logging Guidelines

> How logging is done in this project.

---

## Overview

项目当前没有统一的日志框架配置。FastAPI 应用依赖 uvicorn 的默认日志输出。

---

## Log Levels

| Level | Usage |
|-------|-------|
| ERROR | 未预期的异常、外部服务调用失败 |
| WARNING | 可恢复的问题、降级路径、重试 |
| INFO | 关键业务事件（用户注册、导入任务创建、Worker 任务领取） |
| DEBUG | 请求参数、中间状态（仅开发环境） |

---

## Current State

- FastAPI 应用由 uvorn 运行，请求日志由 uvicorn 自动输出
- 业务代码中使用 Python 标准 `logging` 模块
- Worker 进程应记录任务领取、执行进度、心跳、失败重试

---

## What to Log

- 用户认证失败（不含密码）
- 导入任务状态变更
- Worker 任务领取和完成
- 外部 LLM API 调用（请求摘要、响应状态码、耗时）

---

## What NOT to Log

- 密码明文或哈希值
- JWT token 完整内容
- API 密钥
- 用户上传文件的完整内容
