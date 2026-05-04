# 前端开发指南

> 本项目前端开发的规范与模式索引。

---

## 概述

本目录包含前端开发的所有规范文档，每份文档记录项目代码的**实际模式**，而非理想状态。

---

## 规范索引

| 文档 | 说明 |
|------|------|
| [directory-structure.md](./directory-structure.md) | 目录结构与文件组织 |
| [component-guidelines.md](./component-guidelines.md) | 组件模式、Props/Emits 约定、智能组件模式 |
| [hook-guidelines.md](./hook-guidelines.md) | Composables 模式：单例 vs 实例、generation 防竞态 |
| [state-management.md](./state-management.md) | Pinia Setup Store、异步错误处理分层、路由守卫 |
| [type-safety.md](./type-safety.md) | 纯 JS 类型约定、Ref 初始值暗示类型、可选链防护 |
| [quality-guidelines.md](./quality-guidelines.md) | API 调用组织、Axios 配置、错误三级体系、路由 meta |

---

## 填写原则

1. 记录**实际做了什么**，不是理想状态
2. 引用**真实文件路径**和行号
3. 保持简洁，不要冗余解释
4. 项目使用纯 JavaScript，不用 TypeScript
