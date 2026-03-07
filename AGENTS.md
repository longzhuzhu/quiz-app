# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

CIPT（认证信息隐私技术师）考试备考应用，前后端分离架构。支持题库管理、在线练习（顺序/随机/错题）、错题本、AI 翻译与解析、答题历史。

## 常用命令

### 后端

```bash
pip install -r backend/requirements.txt   # 安装依赖
python run.py                              # 启动 Flask（debug 模式，端口 5003）
```

### 前端

```bash
cd frontend
npm install        # 安装依赖
npm run dev        # Vite 开发服务器（自动代理 /api 到 127.0.0.1:5003）
npm run build      # 生产构建（输出到 frontend/dist/）
```

注意：没有测试框架和 lint 工具配置。

## 架构

### 技术栈

- **后端：** Python / Flask 3 + SQLAlchemy + SQLite（`backend/quiz.db`）+ JWT 认证
- **前端：** Vue 3（`<script setup>` + JS）+ Vite + Pinia + Tailwind CSS 4 + Headless UI

### 前后端通信

- 前端通过 Axios 调用 `/api/*` RESTful 接口
- 开发模式：Vite 代理 `/api` → `http://127.0.0.1:5003`（`frontend/vite.config.js`）
- 生产模式：Flask 直接托管 `frontend/dist/`，所有非 API 路由返回 `index.html`（`backend/app.py`）

### 后端结构

- `run.py` — 入口，将 `backend/` 加入 sys.path 后启动 Flask
- `backend/app.py` — 应用工厂 `create_app()`，注册蓝图和 SPA fallback
- `backend/config.py` — 配置（DB、JWT 7天有效期、AI API、50MB 上传限制）
- `backend/models.py` — 6 个 SQLAlchemy 模型：User、QuestionBank、Question、QuizSession、QuizAnswer、WrongAnswer
- `backend/routes/` — API 蓝图：auth、banks、questions、quiz、wrong、ai
- `backend/services/` — 业务逻辑：auth_service、ai_service、import_service

### API 蓝图前缀

| 前缀 | 功能 |
|------|------|
| `/api/auth` | 注册、登录、当前用户 |
| `/api/banks` | 题库 CRUD、文件导入（PDF/XLSX/DOCX） |
| `/api/questions` | 题目 CRUD、分页 |
| `/api/quiz` | 答题会话（开始/答题/结束/历史） |
| `/api/wrong` | 错题本（列表/练习/标记掌握/统计） |
| `/api/ai` | AI 翻译（单题/批量）、AI 解析 |

### 权限模型

- 公开：注册、登录
- 认证用户（`@jwt_required()`）：答题、错题本、AI 功能
- 管理员（`User.is_admin`）：题库/题目管理、批量翻译。管理员校验仅在后端 API 层

### 前端结构

- `frontend/src/api/client.js` — Axios 实例，请求拦截器自动附加 JWT，401 响应自动登出
- `frontend/src/router/index.js` — Vue Router（History 模式），`meta.auth` 路由守卫
- `frontend/src/stores/` — Pinia store：auth、bank、quiz
- `frontend/src/views/` — 页面组件
- `frontend/src/components/` — 复用组件（QuestionCard、FileUpload、TranslateButton、ExplainButton）

### 数据模型要点

- Question 的 `options` 字段为 JSON 格式存储
- Question 支持 `content_zh`（翻译）和 `explanation_zh`（解析）字段，由 AI 功能填充并缓存
- 题目类型：`single`、`multiple`、`truefalse`
- 答题模式：`sequential`、`random`、`wrong_practice`

### AI 配置

通过环境变量控制（`AI_API_BASE_URL`、`AI_API_KEY`、`AI_MODEL`），默认使用 OpenAI 兼容 API。
