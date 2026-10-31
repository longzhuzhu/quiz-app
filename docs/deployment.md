# 生产部署说明

本文档给出当前项目的正式部署方式。默认推荐 **user systemd + nginx 反向代理**，不要求 root 常驻应用进程，部署和回滚也更直接。

## 1. 推荐方案：user systemd 部署

适用场景：

- 应用代码由当前 Linux 用户维护
- nginx / Cloudflare 等入口已经准备好
- 希望应用进程不以 root 身份运行

### 1.1 前置条件

- Python 3.10+
- Node.js 18+
- npm 9+
- 当前用户可以执行 `systemctl --user`
- **建议开启 linger**，这样即使用户退出登录，user systemd 仍会在开机后自动拉起服务

```bash
sudo loginctl enable-linger $USER
```

### 1.2 部署目录准备

```bash
git clone https://github.com/longzhuzhu/quiz-app.git
cd quiz-app
cp .env.example backend/.env
pip install -r backend/requirements.txt
cd frontend && npm install && npm run build
cd ..
```

### 1.3 创建 user systemd 单元

创建目录：

```bash
mkdir -p ~/.config/systemd/user
```

创建 Web 服务 `~/.config/systemd/user/quiz-app.service`：

```ini
[Unit]
Description=CIPT Quiz App
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/path/to/quiz-app
Environment=APP_HOST=0.0.0.0
Environment=APP_PORT=5003
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=-/path/to/quiz-app/backend/.env
ExecStart=/bin/bash -lc 'exec scripts/start-prod.sh'
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

创建 Worker 服务 `~/.config/systemd/user/quiz-app-worker.service`：

```ini
[Unit]
Description=CIPT Quiz App Worker
After=network-online.target quiz-app.service
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/path/to/quiz-app
Environment=PYTHONUNBUFFERED=1
Environment=JOB_WORKER_CONCURRENCY=10
EnvironmentFile=-/path/to/quiz-app/backend/.env
ExecStart=/bin/bash -lc 'exec scripts/start-worker.sh'
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
```

> `JOB_WORKER_CONCURRENCY=10` 是当前推荐值：它与解析槽位数配套，不同任务作用域可以并行执行，同一作用域仍保持互斥。

### 1.4 启动服务

```bash
systemctl --user daemon-reload
systemctl --user enable --now quiz-app.service quiz-app-worker.service
```

检查状态：

```bash
systemctl --user status quiz-app
systemctl --user status quiz-app-worker
```

查看日志：

```bash
journalctl --user -u quiz-app -f
journalctl --user -u quiz-app-worker -f
```

### 1.5 反向代理

应用默认监听 `127.0.0.1/0.0.0.0:5003`。如果前面有 nginx，反代到：

```nginx
location / {
    proxy_pass http://127.0.0.1:5003;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
}
```

### 1.6 更新流程

```bash
cd /path/to/quiz-app
git pull origin main
cd frontend && npm run build && cd ..
systemctl --user restart quiz-app quiz-app-worker
```

更新后建议执行：

```bash
systemctl --user status quiz-app
systemctl --user status quiz-app-worker
curl -I http://127.0.0.1:5003/
```

### 1.7 端口冲突排查

如果机器上同时存在旧的系统级 `quiz-app.service`，要先停掉或禁用，避免再次占用 `5003`：

```bash
sudo systemctl disable --now quiz-app.service
sudo systemctl disable --now quiz-app-worker.service
```

## 2. 可选方案：系统级 systemd 部署

如果你希望由 root 统一安装到 `/etc/systemd/system/`，项目也提供了安装脚本：

```bash
sudo bash scripts/install-systemd-service.sh
```

这个脚本会创建：

- `quiz-app.service`
- `quiz-app-worker.service`

适用场景：

- 机器本身就是统一由 root 管理的服务主机
- 希望用系统级 systemd 而不是 user systemd

## 3. 手动运行（不推荐长期使用）

仅用于临时排障或本机验证：

```bash
bash scripts/start-prod.sh
bash scripts/start-worker.sh
```

不建议长期依赖手动前台/后台 shell 进程，因为终端退出或会话回收时，服务可能被带掉。


## SQLite 单机部署（可选）

同一份代码可以部署为 PostgreSQL 或 SQLite，但每个部署只使用一种数据库。默认仍为 PostgreSQL；只有显式把 `DATABASE_URL` 配成文件型 SQLite 时才切换到 SQLite。

适用边界：

- 单机、单个 API 进程 + 一个 worker 进程，面向个人或少量用户。
- 不承诺高并发写入；不支持多个应用实例共享同一个 SQLite 文件，也不支持网络文件系统上的数据库文件。
- 业务功能与 PostgreSQL 部署一致；专用离线判重／清理 CLI（`backend/scripts/deduplicate_questions.py`）仍只支持 PostgreSQL。

### 配置

```dotenv
# backend/.env 中二选一。SQLite 必须使用绝对路径。
# PostgreSQL 示例：连接串形如 postgresql+psycopg://...（凭据由部署者填写，勿写入文档）
DATABASE_URL=sqlite:////var/lib/quiz-app/quiz.db
# 可选：与数据库同一锁域；默认 <数据库目录>/.db-locks/
# SQLITE_LOCK_DIR=/var/lib/quiz-app/.db-locks
```

要求：

- 数据库文件所在目录及锁目录必须可写，且 API 与 worker 使用完全相同的配置。
- 不要依赖启动目录的相对路径；配置解析会拒绝非绝对路径，避免误连另一个数据库文件。
- 不要与旧 Flask／测试遗留的 `backend/quiz.db` 混用，那不是一个受支持的部署数据库。

### 初始化与管理员

```bash
cd backend
../.venv/bin/python -m alembic upgrade head
```

全新 SQLite 空库会完成全部结构迁移；随后启动 API 与 worker：

```bash
systemctl --user start quiz-app quiz-app-worker
```

首个通过 `/api/auth/register` 注册的用户自动成为管理员。之后新增考试项目、题库与导入都使用现有页面和接口。若非空旧库缺少迁移 `003` 要求的 `nianyu` 管理员，迁移会明确失败，这是避免错误归属历史数据的保护，不得跳过。

### 并发与运行边界

- worker 在 SQLite 下强制一个业务执行线程，即使 `JOB_WORKER_CONCURRENCY` 更大也不会并行消费；配置值本身不会被修改。
- 解析并发槽位与单个导入任务的写者互斥使用同机原生文件锁；API 与 worker 是两个进程，不能用进程内线程锁替代。
- SQLite 没有 `FOR UPDATE`，关键写入由 `BEGIN IMMEDIATE` 取得写权限；网络请求（AI 调用）前必须先结束本地事务。
- WAL 未默认启用。启用前须验证运行库版本、备份与恢复流程；不能把 WAL 当作多写者能力。

### 升级与备份

```bash
# 维护窗口内先停止两个服务
systemctl --user stop quiz-app quiz-app-worker
# 备份一致性数据库文件与上传/导入原件存储（STORAGE_ROOT）
# 再执行迁移并重启
(cd backend && ../.venv/bin/python -m alembic upgrade head)
systemctl --user start quiz-app quiz-app-worker
```

- 运行期不要只复制主 `.db` 文件就当作在线备份；停写后备份，或使用 SQLite backup API。恢复时先恢复到新目录并验证，再切换。
- 数据库迁移与 PG 共用 001→013 一条链；不要用 `create_all` 或手工 stamp 代替升级。

## 多模型 AI 解析（迁移 011）

升级必须安排维护窗口：停止 API 与全部旧 worker，备份数据库，在后端虚拟环境执行 `python -m alembic upgrade head`，构建前端后再启动配套版本。迁移保留来源未知的旧解析，终结旧单解析预热任务；不能代替停止仍在运行的旧进程。

解析由 worker 执行，不再由 API 同步直调。所有 worker 的 `AI_EXPLANATION_CONCURRENCY` 必须一致，默认全站十个在途解析调用；`JOB_WORKER_CONCURRENCY` 决定该实例能运行多少后台任务，默认十个，低于槽位数时并发受线程数限制。额度不足排队，手动请求优先于静默预热，不影响其他 AI 场景的重试策略。

解析单次模型调用超时由 `AI_EXPLANATION_TIMEOUT_SECONDS` 控制（默认 120s）。输出格式不合格时会追加纠正消息再调用一次，单题最坏耗时约为超时值的两倍；解析任务租约固定为 360s 以覆盖该最坏路径，因此调大超时须同步确认租约仍有余量，否则 `recover_stale_jobs` 会把仍在执行的解析判为中断。

解析任务同时持有会话连接与 advisory lock 连接，满载并发需要两倍于槽位数的数据库连接。连接池容量（`pool_size + max_overflow`）必须覆盖「worker 线程数 + 解析槽位数」，否则任务会在获取连接处阻塞。

本次解析的网络、超时和上游失败不自动重试；失败后的静默预热也不重开同一输入任务。只有一次输出格式修复，或用户明确更新/重试。旧成功结果仍可读。worker 中断时不能保证上游停止计费，重新生成前应先核实任务终态。回滚须先停止新任务和新 worker，再核实新结果表与旧文本字段兼容；不要把任一模型结果冒充全部解析。

## CIPT 重复题审计工具

`backend/scripts/deduplicate_questions.py` 当前只接受 `nianyu / cipt / banks 13 15`，各库内判重。题干和原顺序选项一致即归同题，答案冲突单独阻断。默认只读，不调用 AI、不删除题目；不得放进启动、迁移或部署 hook。

连接从明确的受保护环境或 `backend/.env` 读取，禁止把连接口令放在命令行。文件读取要求正确归属与限制权限；若拒绝，不擅自修改生产文件权限，可由授权操作者在受保护环境注入已核实的 `DATABASE_URL`。

```bash
# 输出目录必须当前用户所有、0700；仓库外或明确git忽略位置，文件将为0600。
mkdir -p -m 700 "$HOME/.local/state/quiz-app/cipt-dedup"
.venv/bin/python backend/scripts/deduplicate_questions.py \
  --audit-id cipt-first-round \
  --output "$HOME/.local/state/quiz-app/cipt-dedup/audit.json"
```

报告含 keep/remove ID、原值和空白归一两种计数、答案/题型冲突、版本指纹和确认摘要；两种数量是包含关系，不相加。终端不输出题面全文或凭据。未完成会话引用、已完成会话的原题重做引用、作答/错题/统计/当日练习事实、后台任务引用，与答案/题型冲突、无效题面、未知/向量/导入引用、活跃任务及词频派生保护一样，全部进入 `blockers` 硬阻断。`cascades` 字段仅为报告格式兼容而保留，当前始终为空，不能用“接受删除代价”放行学习历史清理。只涉及代表题的已完成会话和学习事实不受影响；涉及未完成会话的重复组仍跳过。合并仅保留代表题现有的一份翻译、解析、考点，不取并集；ADR-0011 的附加信息舍弃不授权删除学习历史、破坏原题重做或舍弃词汇释义（参见 ADR-0009/0010/0011）。

新执行计划使用 schema 3，旧 schema 1/2 的审批文件（包括 JSON 存盘后读回）不得用于 apply，必须重新审计确认。备份外层保持 schema 2；已有 schema 2 旧计划备份仅在 rollback 中按原图像合同校验恢复，不因此重新开放旧计划执行。新备份的恢复同样校验学习保护，不能把备份当作绕过保护的入口。原 main 的外层 schema 1 备份因后台引用摘要口径不同，当前工具明确拒绝；须保留对应原版本工具，另行核验并获得恢复授权，不得改版本号、重算摘要或跳过指纹强行恢复。

`backend/scripts/fix_malformed_questions.py` 仅处理限定坏题，默认 dry-run；缺选项题若仍有会话、作答、错题、统计或练习事实则拒绝删除，未知附属外键引用同样拒绝，不靠级联删除绕过。仅选项 key 修正不删除题目或学习记录。不得为推进清理而改变会话状态或清空历史。本轮只整理代码与测试，不包含真实数据清理、模型调用或部署授权。

### 显式受控 AI

仅在获得发送题面及用量授权后运行：

```bash
.venv/bin/python backend/scripts/deduplicate_questions.py --ai \
  --audit-id cipt-first-round \
  --ledger "$HOME/.local/state/quiz-app/cipt-dedup/ledger.json" \
  --output "$HOME/.local/state/quiz-app/cipt-dedup/ai-report.json"
```

固定 `deepseek-v4.1-flash`，发送原始题干/选项与技术ID，不发送答案、用户名、历史、来源或凭据。累计最多100候选对/100请求，失败及格式纠正计入；恢复必须复用同一 audit_id/账本并改用新的输出文件名，不能换账本重置额度。旧规则账本被拒绝也不是重新授权。请求上限不是固定金额保证，目录存在也不保证推理兼容或判重质量。

模型结果仅为候选；未知、危险差异、注入、过长题面不强行判断，召回不证明全库无语义重复。确认具体 `groups:[[代表ID,成员ID,...]]` 私密文件后可通过 `--semantic-plan` 与 `--semantic-confirmation` 只读构建语义计划，每个成员需有独立代表证据，不能按传递闭包扩组。

### 真实清理与回滚另行确认

本次工具交付不授权真实 apply/rollback。未来须确认具体清单、完整摘要与回滚方案，并使 Web、worker及其他写入者离线/维护停写；工具不停止服务，`--maintenance offline-maintenance-confirmed` 只是操作者前提确认，不能证明停写。

`--apply PLAN --confirm DIGEST --backup BACKUP` 独立执行：重审归属/计划/关联，先写受限 durable pre/post，再单事务清理。全部阻断时不写库、不创建备份。`--rollback BACKUP` 根据实际 post-image 校验，拒绝后续漂移/新引用/ID冲突，不覆盖新修改。含敏感业务题面的备份与账本不得进git、普通日志或AI。

### 导入重试修复的部署边界

修复代码无 schema 迁移；部署仍需用户单独批准并按现有发布流程处理所有API/worker，不在审计脚本中自行重启。导入用 `WORKER_LEASE_SECONDS`（默认600s）和独立续约、不可变attempt fencing、manifest/响应/入库checkpoint；失租旧执行不能提交或改新attempt终态。复核与正在执行的同job冲突返回409，可稍后重试。

历史重复/不可靠manifest拒绝自动恢复而非清洗旧行。回退代码前先停止相关执行并核验checkpoint兼容，不抹元数据后盲跑。不同ImportJob同bank并发内容竞态及继承的人工accept导入计数虚报仍需单独治理；不能将本次修复称为全部导入问题已解决。
