# CIPT Quiz App

CIPT（Certified Information Privacy Technologist）认证信息隐私技术师考试备考应用。支持题库管理、在线练习、错题本、AI 翻译与解析、专业词汇本等功能。

## 功能特性

- **题库管理** — 支持从 PDF / XLSX / DOCX 文件导入题目，自动识别 ExamTopics 等常见格式
- **在线答题** — 顺序练习、随机练习、错题练习三种模式，支持页面刷新后恢复答题
- **错题本** — 答错自动收集，支持按题库过滤、标记掌握、发起错题练习
- **AI 翻译** — 单题翻译和批量翻译，结果缓存到数据库避免重复调用
- **AI 解析** — AI 生成中英文题目解析，帮助理解知识点
- **专业词汇本** — 系统级专业词汇（支持从 IAPP 导入）+ 个人单词收藏
- **答题历史** — 分页查看历史记录及答题详情
- **响应式设计** — 适配桌面端和移动端

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python / Flask 3 + SQLAlchemy + SQLite + JWT |
| 前端 | Vue 3 (`<script setup>`) + Vite + Pinia + Tailwind CSS 4 + Headless UI |
| AI | OpenAI 兼容 API（可配置其他服务） |

## 快速开始

### 前置要求

- Python 3.10+
- Node.js 18+
- npm 9+

### 1. 克隆仓库

```bash
git clone https://github.com/longzhuzhu/quiz-app.git
cd quiz-app
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```env
SECRET_KEY=your-secret-key
JWT_SECRET_KEY=your-jwt-secret-key
AI_API_BASE_URL=https://api.openai.com/v1
AI_API_KEY=your-api-key
AI_MODEL=gpt-4o-mini
```

> AI 相关配置为可选项。不配置时，翻译和解析功能不可用，其他功能正常使用。
> AI 配置也可在启动后通过管理后台页面修改，无需重启服务。

### 3. 启动后端

```bash
pip install -r backend/requirements.txt
python run.py
```

后端默认运行在 `http://localhost:5003`，首次启动会自动创建数据库。

### 4. 启动前端

```bash
cd frontend
npm install
npm run dev
```

前端开发服务器会自动代理 `/api` 请求到后端。

### 5. 访问应用

打开浏览器访问前端开发服务器地址（默认 `http://localhost:5173`）。

**第一个注册的用户自动成为管理员**，拥有题库管理、题目管理、AI 设置等权限。

## 生产部署

构建前端静态文件：

```bash
cd frontend
npm run build
```

Flask 会自动托管 `frontend/dist/` 目录，直接访问 `http://localhost:5003` 即可。

## 项目结构

```
quiz-app/
├── run.py                      # 应用入口
├── .env.example                # 环境变量模板
├── backend/
│   ├── app.py                  # Flask 应用工厂
│   ├── config.py               # 配置管理
│   ├── models.py               # 数据模型（8 个表）
│   ├── requirements.txt        # Python 依赖
│   ├── routes/                 # API 蓝图
│   │   ├── auth.py             #   认证（注册/登录）
│   │   ├── banks.py            #   题库管理
│   │   ├── questions.py        #   题目管理
│   │   ├── quiz.py             #   答题会话
│   │   ├── wrong.py            #   错题本
│   │   ├── ai.py               #   AI 翻译/解析
│   │   ├── vocab.py            #   词汇表
│   │   └── settings.py         #   系统设置
│   ├── services/               # 业务逻辑
│   │   ├── ai_service.py       #   AI API 调用
│   │   ├── auth_service.py     #   用户认证服务
│   │   └── import_service.py   #   文件导入解析
│   └── scripts/
│       └── import_iapp_glossary.py  # IAPP 术语导入脚本
├── frontend/
│   ├── vite.config.js          # Vite 配置（API 代理）
│   └── src/
│       ├── api/client.js       # Axios 实例（JWT 拦截器）
│       ├── router/index.js     # 路由配置
│       ├── stores/             # Pinia 状态管理
│       ├── views/              # 页面组件
│       └── components/         # 复用组件
└── reference/                  # 参考资料
```

## API 概览

| 前缀 | 功能 | 权限 |
|------|------|------|
| `/api/auth` | 注册、登录、当前用户 | 公开 / JWT |
| `/api/banks` | 题库 CRUD、文件导入 | JWT / 管理员 |
| `/api/questions` | 题目 CRUD、分页查询 | JWT / 管理员 |
| `/api/quiz` | 答题会话（开始/答题/结束/历史） | JWT |
| `/api/wrong` | 错题本（列表/练习/标记掌握/统计） | JWT |
| `/api/ai` | AI 翻译（单题/批量）、AI 解析 | JWT / 管理员 |
| `/api/vocab` | 专业词汇 + 个人单词本 | JWT / 管理员 |
| `/api/settings` | AI API 配置管理 | 管理员 |

## 数据模型

| 模型 | 说明 |
|------|------|
| `User` | 用户（用户名、邮箱、密码哈希、管理员标识） |
| `QuestionBank` | 题库（名称、描述、来源文件） |
| `Question` | 题目（内容、选项 JSON、正确答案、翻译、解析） |
| `QuizSession` | 答题会话（模式、进度、得分） |
| `QuizAnswer` | 单题作答记录 |
| `WrongAnswer` | 错题记录（答错计数、掌握标记） |
| `Vocabulary` | 词汇（专业/个人，支持中文翻译） |
| `SystemSetting` | 系统设置（键值对存储） |

## 题目导入

支持从以下格式的文件导入题目：

- **PDF** — 使用 pdfplumber 解析，支持 ExamTopics 导出格式
- **XLSX** — 使用 openpyxl 解析
- **DOCX** — 使用 python-docx 解析

导入时自动识别题型（单选 / 多选 / 判断），并从文末提取答案表。

## AI 配置

应用支持任何 OpenAI 兼容的 API 服务。配置方式：

1. **环境变量** — 在 `.env` 中设置 `AI_API_BASE_URL`、`AI_API_KEY`、`AI_MODEL`
2. **管理后台** — 登录管理员账号，在「设置」页面配置（优先级高于环境变量）

## License

MIT
