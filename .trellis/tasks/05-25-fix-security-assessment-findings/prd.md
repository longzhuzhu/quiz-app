# fix-security-assessment-findings

## Goal

修复授权安全评估报告 `/home/ubuntu/tools/security/quiz_nianyu_security_assessment.md` 中对当前应用可落地的安全问题，降低生产环境暴露面、跨域读取、弱密码、暴力破解、存储型 XSS、缺失安全响应头和 AI Base URL SSRF 风险。

## What I already know

* 报告列出 7 个主问题：V-01 OpenAPI 暴露、V-02 CORS 过宽、V-03 存储型 XSS、V-04 前后端密码策略不一致、V-05 登录无速率限制、V-06 安全响应头缺失、V-07 AI 功能潜在 SSRF。
* 现有领域语言使用“考试项目”“考试项目标识”“考试项目所有者”，不使用“全局唯一标识”描述 slug。
* `CONTEXT.md` 已明确：考试项目默认只对所有者可见，管理员可以只读查看其他用户的考试项目和题库。
* `backend/app/main.py` 当前关闭了 Swagger UI 和 ReDoc，但未显式关闭 `/openapi.json`。
* `backend/app/main.py` 当前 CORS 配置为 `allow_origins=["*"]`、`allow_credentials=True`、`allow_methods=["*"]`、`allow_headers=["*"]`。
* 当前只发现 no-cache 头，未发现 CSP、X-Frame-Options、X-Content-Type-Options、HSTS 等通用安全响应头。
* `backend/app/schemas/auth.py` 注册密码仅 `min_length=1`；修改密码和管理员重置密码已有 6 位限制。
* `backend/app/api/routes/auth.py` 登录接口未发现速率限制。
* `backend/app/services/settings_service.py`、`backend/app/services/ai_service.py` 与 `backend/app/api/routes/settings.py` 对 AI `base_url` 未发现协议、内网、回环地址限制；AI HTTP 请求存在 `verify=False`。
* `backend/app/api/deps.py` 的 `get_exam_context()` 按 `owner_id=current_user.id` + `X-Exam-Slug` 解析考试项目，当前代码与报告中 X-Exam-Slug 越权假设不一致。
* `backend/app/api/routes/quiz.py` 的 session detail 同时校验 session 所属考试项目和 `session.user_id == current_user.id`，当前代码与 Quiz Session IDOR 假设不一致。

## Assumptions (temporary)

* 本任务优先修复报告“修复优先级建议”表中的 7 个主项。
* 报告中 IDOR、条件竞争、信息泄露等探索性发现先作为验证项，不默认扩大为本轮必须改代码项，除非确认纳入范围。
* 后端是主要修复边界；前端只在实际存在 `v-html` 或密码策略展示不一致时做同步改动。

## Open Questions

* None.

## Requirements (evolving)

* 本轮范围覆盖 7 个主漏洞，并额外收敛报告中明确的信息泄露点；IDOR 和条件竞争只做代码证据核对，除非发现当前代码确有缺口。
* 生产环境不得公开 OpenAPI JSON、Swagger UI、ReDoc；开发环境可通过环境开关保留 OpenAPI JSON 便于调试。
* CORS 必须限制到明确允许的 Origin，不能反射任意 Origin 且允许 credentials；生产只允许 `https://quiz.nianyu.qzz.io`，本地开发通过 Vite proxy 访问 `/api`，不依赖跨域。
* 保留管理员读取 AI API Key 明文的能力，但必须降低跨域读取和意外暴露风险。
* 注册响应只返回成功消息，不再返回 `id`、`is_admin`、`created_at` 等用户字段；登录和 `/auth/me` 用户响应保持现状。
* 用户可提交的题目与词汇内容保持原文存储，但不得在前端形成可执行 HTML/JS；前端必须使用纯文本渲染路径。
* 注册、修改密码、管理员重置密码的后端密码策略必须一致，统一为最少 6 位。
* 登录失败必须具备基础速率限制并返回 `429`；采用轻量内存限流，不新增外部依赖。
* 后端响应应添加基础安全响应头；CSP 采用保守基础策略，优先覆盖 `frame-ancestors 'none'`、`object-src 'none'`、`base-uri 'self'` 等低兼容风险限制。
* AI Base URL 仅允许公网 `https://`，必须阻止 `http://`、loopback、link-local、private network、metadata IP 等目标，并恢复 TLS 证书校验。

## Acceptance Criteria (evolving)

* [ ] `/openapi.json`、`/docs`、`/redoc` 在生产配置下不可访问。
* [ ] 恶意 Origin 的 CORS preflight 不再返回允许读取的 Origin + credentials 组合。
* [ ] 创建包含 `<script>` / event handler payload 的 question/vocab 后，页面或 API 渲染路径不会执行脚本。
* [ ] API 注册 1 位密码失败，且错误语义与现有接口风格一致。
* [ ] 连续错误登录超过阈值后返回 `429 Too Many Requests`。
* [ ] 常见安全响应头存在于 API 与 SPA fallback 响应。
* [ ] AI Base URL 指向 `127.0.0.1`、`localhost`、`169.254.169.254`、RFC1918 私网地址时被拒绝。
* [ ] 注册成功响应不再包含用户对象和内部字段。
* [ ] AI API Key 明文读取能力保留给管理员，但依赖收紧后的 CORS 和安全头降低跨站读取风险。
* [ ] 已核对 X-Exam-Slug 与 quiz session IDOR 当前有 owner 校验；如无需改代码，在结果中明确说明证据。

## Definition of Done

* Tests added/updated where the repo has practical test hooks, or manual verification commands recorded when no test framework exists.
* Relevant backend validation and middleware behavior verified.
* Frontend behavior verified if frontend rendering code changes.
* Docs/notes updated only when domain terminology or hard-to-reverse decisions change.
* Rollout/rollback considerations noted for production-affecting config such as CORS allowed origins.

## Technical Approach

* 在 `backend/app/main.py` 增加环境控制的 OpenAPI 暴露开关，生产关闭 `/openapi.json`、`/docs`、`/redoc`，开发可保留 OpenAPI JSON。
* 将 CORS 从通配改为仅允许 `https://quiz.nianyu.qzz.io`，禁止任意 Origin 反射。
* 增加基础安全头中间件，CSP 采用保守基础策略，避免高风险兼容性破坏。
* 注册密码后端最小长度改为 6 位，与前端、修改密码、管理员重置密码一致。
* 登录接口增加轻量内存失败限流，超过阈值返回 `429`。
* XSS 采用“原文存储 + 前端纯文本渲染”策略；当前未发现 HTML sink，实施中补充必要验证。
* AI Base URL 仅允许公网 HTTPS，拒绝 HTTP、localhost、loopback、link-local、私网、metadata IP，并恢复 TLS 证书校验。
* 注册响应 schema 收敛为 message-only；登录和 `/auth/me` 响应保持现状。

## Decision (ADR-lite)

**Context**: 安全报告同时包含真实漏洞、探索性风险和若干产品权限模型建议，需要避免一次性扩大到架构重做。  
**Decision**: 本轮修复 7 个主漏洞并额外收敛注册响应信息泄露；IDOR 与条件竞争只做当前代码证据核对，发现真实缺口再处理。  
**Consequences**: 可以快速降低线上主要风险，同时保留后续对分布式限流、审计日志、UUID 化等更大改动单独设计的空间。

## Out of Scope (explicit)

* 不重构认证模型或 JWT 存储方式。
* 不引入分布式限流基础设施。
* 不改变管理员是否能查看全部用户/考试项目的产品权限模型。
* 不把自增 ID 全面迁移为 UUID。
* 不处理条件竞争，除非实现中发现与本轮安全边界直接相关的当前缺口。

## Technical Notes

* Report: `/home/ubuntu/tools/security/quiz_nianyu_security_assessment.md`
* Domain glossary: `CONTEXT.md`
* ADRs: `docs/adr/0003-url-exam-slug-and-active-exam.md`, `docs/adr/0004-no-legacy-routes-for-multi-exam.md`
* Main app/middleware: `backend/app/main.py`
* Auth schemas/routes: `backend/app/schemas/auth.py`, `backend/app/api/routes/auth.py`
* AI settings/services: `backend/app/api/routes/settings.py`, `backend/app/schemas/settings.py`, `backend/app/services/settings_service.py`, `backend/app/services/ai_service.py`
* Exam context: `backend/app/api/deps.py`, `backend/app/services/exam_service.py`
* Question/vocab routes: `backend/app/api/routes/questions.py`, `backend/app/api/routes/vocab.py`
* Quiz session route: `backend/app/api/routes/quiz.py`
* Frontend XSS sink check: `frontend/src` 未发现 `v-html`、`innerHTML`、`insertAdjacentHTML` 或 `dangerouslySetInnerHTML`。
* Frontend register flow: `frontend/src/stores/auth.js` 的 `register()` 不使用注册响应体中的 `user`，注册成功后仍需用户登录。
