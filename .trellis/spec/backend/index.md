# 后端开发指南

> 后端处于 Flask -> FastAPI 迁移期。旧代码在 `backend/` 根目录，新代码在 `backend/app/` 下。两套系统共存，新功能统一走 FastAPI。

---

## 文档索引

| 文档 | 说明 |
|------|------|
| [目录结构](./directory-structure.md) | Flask/FastAPI 双套目录布局、命名规则、蓝图变量 |
| [数据库规范](./database-guidelines.md) | ORM 模式对比（Flask vs FastAPI）、查询风格、序列化、并发 upsert |
| [错误处理](./error-handling.md) | Flask 错误返回、FastAPI HTTPException、自定义异常、四种 try/catch 模式 |
| [日志规范](./logging-guidelines.md) | 现状几乎空白、推荐模式、唯一使用 logging 的文件 |
| [代码质量](./quality-guidelines.md) | 类型注解对比、依赖注入、返回格式、服务层风格、配置方式 |

---

## 迁移状态

- Flask 旧版：仍在运行，`backend/routes/` + `backend/services/` + `backend/models.py`
- FastAPI 新版：`backend/app/` 下完整分层，已有 15 个路由模块
- 共存方式：Flask 端口 5003，FastAPI 另有入口（`run_api.py`），共享同一数据库
