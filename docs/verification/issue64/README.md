# Issue #64 实施与验证记录

最新核对：2026-10-12。初次实施依据：[正式规格](https://github.com/longzhuzhu/quiz-app/issues/64)及[已批准的实施计划](../../superpowers/plans/2026-10-11-vocabulary-study-issue64.md)。后续范围调整以本次用户明确要求及下列记录为准，历史段落不作为最终功能边界。

**状态：功能代码已实施，已执行下述自动验证；尚未满足全部上线门槛，未关闭 Issue。** 后续按用户授权已构建前端、执行迁移 `010` 并重启现有 Web 服务；最后的英文释义直显调整已重建前端。业务环境原始记录与截图仅保留在本地，不纳入公开 PR。完整后端测试的既有失败、真机、真人读屏和原生浏览器缩放检查仍需解决／补验。不能将部署成功视为规格全部验收通过的声明。

## 最新用户要求与验证结果

- 左右滑动、按钮及方向键切词复用有方向的淡出／淡入，分别 100ms、140ms；卡片外壳和焦点保持稳定。连续导航或离页会取消旧动画，新增切词动效遵循减少动态效果设置。
- 中间操作定名为「刷新」：仅手动触发已配置的 AI 翻译模型，一次重新生成并原子保存 `term_zh`、`definition`、`definition_zh`，已有内容也更新。英文词条、本轮结果与长期掌握不变。
- 新增 `POST /api/vocab/study/refresh`；生成后重新检查可见性和当前内容，已删除词不重建，较新的内容不被慢响应覆盖。失败／不完整结果不部分覆盖。请求中断时不能声称服务器一定未保存，界面提示结果可能未确认。
- 高频词新增两列中英文释义，通过迁移 `010` 保存；**这是后续用户授权的范围扩展，替代最初不新增迁移／不生成释义的限制**。部署前执行 `cd backend && python -m alembic upgrade head`。原卡组引用、掌握接口和本地草稿格式不变。
- 顶部进度按当前词位置计算，回看会回退，与是否标记无关；标记统计留在小结。卡片反面直接显示英文释义，不再有「展开英文释义」控件；缺失时不保留空段落，长内容仍可内部滚动。
- 最后一轮前端 `npm test`：**61 通过、0 失败、0 跳过、0 取消**，退出码 0；生产构建通过，`git diff --check` 通过。包含真实后端／隔离 PostgreSQL 闭环、英文直显、滑动／翻转、刷新与身份隔离、明暗主题和屏幕矩阵。外部 AI 响应使用测试替身，未以此证明模型生成内容的实际质量。
- 后端相关 5 个测试文件：**110 通过**。覆盖词汇 HTTP／可见性、AI 场景、PostgreSQL 竞争、迁移升降级及答题计时迁移兼容；计时迁移测试锁定 `009`，避免最小夹具误执行未来其他表迁移。
- 完整后端：**291 通过、7 失败、17 初始化错误**；失败／错误仍属于原智能导入夹具缺失 `question_banks.exam_id`。后续新增的 AI 请求契约另由上述相关套件覆盖，不将全量非绿冒充通过。
- 最新临时日志：`/tmp/quiz-direct-definition-tests.log`、`/tmp/quiz-direct-definition-build.log`、`/tmp/quiz-refresh-targeted-tests.log`、`/tmp/quiz-refresh-backend-tests.log`。这些路径是执行环境记录，不是 PR 中可下载的永久日志。下列非 `systemd-*` 截图与 JSON 只来自合成测试内容。

## 历史交互调整：整卡点击翻面

- 移除右下角翻面按钮，点击卡片正文、留白或底部提示均可切换；Enter／空格操作保持焦点在卡片上，展开释义独立操作。
- 使用两段各 160ms 的立体翻转，在侧立时替换唯一的内容面，不预埋隐藏中文；旋转时轻微收缩，避免遮住进度和导航。
- 按用户后续明确要求，翻卡动画不随系统“减少动态效果”关闭；其他元素保留原有设置。选词、长按、滚动不翻面，横滑只切词；保存中及动画中拒绝重复翻面，切词／离页取消旧动画。
- 本次前端全量 **50 通过、0 失败、0 跳过、0 取消，退出码 0**；包含真实后端闭环、动画帧检查、连续点击、动画取消、键盘与选词、屏幕矩阵及明暗主题自动无障碍检查。日志：`/tmp/quiz-card-flip-final.log`。下列非 `systemd-*` 截图及 JSON 已随回归更新。
- 生产构建单独复跑通过、退出码 0，产物位于 `/tmp/quiz-card-flip-build`；日志：`/tmp/quiz-card-flip-build.log`。`git diff --check` 通过。
- 本次未更新当前服务使用的 `frontend/dist`，未重启 systemd，未改后端代码或业务数据库；历史部署记录不代表这次交互已部署。真机及真人读屏等未验项保持不变。

## 初次实施内容与边界（历史）

- 保留项目词汇、我的单词本、高频词汇三入口；默认未掌握，可选全部／已掌握，高频必须明确题库。管理通过原项目 URL 的 `mode=manage` 进入。
- 新增 `/exams/:examSlug/vocab/study`：英文正面、中文背面、明确翻面、上一张／下一张和左未记住／右已记住。横滑只导航，保存成功才前进。窄屏及触控低矮横屏沉浸，桌面保留导航。
- 固定完整引用及顺序，位置与成功标记进度分开；三类小结、仅本轮未记住再练、仅本轮未标记补学。新轮不将长期掌握当作本轮结果。
- 新增只读 deck／items API，集合查询只取引用和排序字段，内容按身份分批读取；普通词无隐藏分页截断，高频先确定前 5000 个可见词再筛掌握。轻量核验不取释义，明确失效才调整分母。
- 学习 Module 统一处理三来源；内容每批 20、预取余量 5、读取并发最多 2、正文 LRU 最多 100；恢复和小结核验每批最多 500。
- IndexedDB 分离 manifest／checkpoint；Web Locks 提供上下文独占，BroadcastChannel 仅协商交接。待确认写入不当成功、不自动重放；能力／存储失败明确降级为页内学习。
- 个人草稿按账号隔离，不随项目复制；项目词和高频再按稳定项目／题库身份隔离。账号失效清理草稿和缓存，请求捕获认证／项目上下文并拒绝迟到响应。
- 旧管理展示层保留于 `VocabularyManageView.vue`，普通管理列表读取全部分页。原掌握 PUT 地址、绝对布尔字段与响应兼容；首次插入 savepoint 仅处理目标唯一键冲突，删除与写入采用一致锁顺序。
- **不新增数据库迁移、表、列、产品依赖、服务端轮次或自动 AI 调用。** HTML 字样作为纯文本显示，释义不落入续学数据库。没有原型开关或演示身份进入产品代码。

主要模块：

| 职责 | 文件 |
| --- | --- |
| 授权集合、排序、快照、按身份批读 | `backend/app/services/vocab_query_service.py` |
| 绝对掌握、首次写入冲突及锁协议 | `backend/app/services/vocab_progress_service.py`、现有 vocab／exam 服务 |
| HTTP 请求／响应校验 | `backend/app/schemas/vocab.py`、`backend/app/api/routes/vocab.py` |
| 学习轮次、计数、异步和退出 | `frontend/src/features/vocabularyStudy/study.js` |
| 内容调度、HTTP 身份、存储协调 | 同目录 `contentLoader.js`、`api.js`、`resume.js`、`lifecycle.js` |
| 概览、单卡及页面 | `VocabularyOverview.vue`、`VocabularyStudyCard.vue`、`VocabularyStudyView.vue` |

## 初次实施自动检查实测

| 检查 | 改动前基线 | 最终结果 |
| --- | --- | --- |
| 前端 `npm test`（脚本为 `node --test`） | 22 通过／0 失败／0 跳过 | **48 通过／0 失败／0 跳过／0 取消**，最终直接复跑该脚本退出码 0 |
| `cd frontend && npm run build -- --outDir /tmp/quiz-issue64-build` | 通过 | **通过**，未覆盖仓库 `dist` |
| `.venv/bin/python -m pytest backend/tests -q` | 220 通过／7 失败／17 初始化错误／0 跳过 | **251 通过／7 失败／17 初始化错误／0 跳过** |
| 词汇 HTTP、授权及 PostgreSQL 并发三文件 | 原授权文件 4 通过 | **35 通过／0 失败／0 跳过** |
| `git diff --check` | — | 通过 |

后端失败／错误节点与基线逐项比较，新增为 0、消失为 0。既有 7 个失败在 `test_smart_import_e2e_reconciliation.py`，17 个初始化错误在 `test_smart_import_scenario_content.py`，日志中的数据库错误涉及旧测试数据未提供 `question_banks.exam_id`。这些既有失败没有被删除、改成 skip 或算成通过；全后端非绿仍是上线门槛未满足，不在本次词汇重构中顺手改写导入模块。

完整运行日志位于本次执行环境的 `/tmp/quiz-issue64-frontend-repeat.log`、`/tmp/quiz-issue64-backend-final.log`、`/tmp/quiz-issue64-backend-vocab.log`、`/tmp/quiz-issue64-build.log`；这些临时日志不是仓库中的永久附件。上表及下列 JSON／截图为仓库内证据。收尾时一轮 npm 外层进程收到终止信号（退出码 143），虽然 Node 已报告 48 项通过，仍不将该轮当作正常退出；随后直接执行相同 `node --test` 脚本完整复跑，确认 48 项通过、退出码 0，独立生产构建也退出 0。

### 验证覆盖与 seam

- `backend/tests/test_vocab_study_api.py`：公开 HTTP、真实 SQLite 查询；普通完整集合、三来源授权、严格校验、高频截断顺序、批读顺序、不可用隐私、轻量 SQL 投影及取消掌握。
- `backend/tests/test_vocab_progress_concurrency.py`：专用临时 PostgreSQL、并行 HTTP、两种首次写入、删除竞争及非目标约束异常不吞掉。不是用 SQLite 代替并发验证。
- `frontend/tests/vocabularyStudy.test.js`：公开学习 Module 注入受控 Adapter；三类结果与改判、在途锁、未确认恢复、迟到响应、上下文失效、存储异常、5000 词导航及批读／核验／LRU 边界。
- `frontend/tests/vocabularyStudyBrowser.test.js`：真实 App／router／导航，仅在 HTTP 边界替换服务；真实 IndexedDB、真实 Web Locks 交接及账号清理、强制关闭在途写入、刷新／小结、失败重试、语义键盘／手势／纯文本内容等。
- `frontend/tests/vocabularyStudyE2E.test.js`：**真实登录、真实 FastAPI、专用隔离 PostgreSQL**，个人词与高频词翻面／保存／刷新，查询实际持久化结果；110 项目词、110 个人词和 5000 高频词引用契约，个人跨项目恢复及缺少认证／项目头的拒绝。外部 AI 不参与。
- 原词汇管理和答题收藏浏览器断言保留，增加项目词超过 100 条管理回归。各浏览器测试的 Vite optimizer cache 隔离，避免不同 fixture 插件相互污染。

新增关键浏览器／PostgreSQL 套件缺少工具会失败，不通过 skip 冒充验收。复现需已安装前端依赖、后端虚拟环境、`agent-browser` 和浏览器；PostgreSQL 测试使用非 root 用户的 `initdb`／`pg_ctl`，默认 `/usr/lib/postgresql/16/bin`，可用 `PG_BINDIR` 指定。数据库在临时目录独立启动／销毁，不清理业务数据库。

词汇专项命令：

```bash
.venv/bin/python -m pytest \
  backend/tests/test_vocab_study_api.py \
  backend/tests/test_vocab_progress_concurrency.py \
  backend/tests/test_vocabulary_visibility.py -q
```

## 视觉、无障碍与请求规模证据

- [来源概览](source-overview.png)、[移动正面](mobile-front.png)、[移动长释义背面](mobile-long-back.png)、[桌面背面](desktop-back.png)、[触控横屏](touch-landscape.png)、[1／1／1 本轮小结](round-summary.png)。截图来自测试内容，不是产品演示数据。
- [屏幕矩阵](screen-matrix.json)：320×568、390×844、767／768／769×800、1024×800、1440×900，明暗主题及 100%／200% **文本放大**共 28 组；另有 844×390 coarse pointer 模拟。检查横溢出、判断按钮高度和视口可达；未出现横溢出或按钮遮挡。
- [自动无障碍结果](accessibility.json)：学习区正／反面、明／暗主题 4 组 axe AA 检查，均 0 violation、0 incomplete。**范围仅学习区；不是全站认证，也不替代真人读屏。**
- [5000 词请求记录](performance.json)：桌面本地 HTTP fixture，1 次 deck 加 1 次首批 20 词 items；具体首卡时间、传输量及 DOM 节点数以该 JSON 的实测值为准，不沿用历史交互的精确数字。快照不含释义，未请求全库释义。
- 上述性能不是生产、真实 PostgreSQL 或移动真机性能保证；200% 文本放大不是原生浏览器页面缩放，coarse pointer 模拟也不是真机。

## 自审结论

| 维度 | 已采取的措施 | 剩余风险／限制 |
| --- | --- | --- |
| 可维护性 | 单一学习 Module；HTTP／存储／内容调度 Adapter；单卡无 I/O；查询授权集中；管理独立保留 | 生命周期涉及账号、路由、页签和服务端四层，未来修改应同时运行 Module 与真实浏览器套件 |
| 边界条件 | 三类结果独立于长期掌握；固定身份；未确认不重放；保存与后续读取分离；全轮核验成功才发小结；精准唯一键处理 | Web Locks／安全上下文不足会内存降级；清理失败有提示，不能保证浏览器拒绝存储时仍成功擦除历史数据 |
| 回归风险 | 原管理断言保留；原接口兼容；同词不同身份隔离；显式项目头保留；认证 generation 守卫；专用 PG 并发及真实后端闭环 | 全后端仍非绿；真机、真人读屏和完整人工验收矩阵未签收，不可仅凭桌面自动化放行 |

## 尚未完成的上线门槛

| 项目 | 记录 |
| --- | --- |
| 完整后端测试全绿 | 未达到：7 失败、17 初始化错误，与基线一致；需独立修复并回归 |
| iOS Safari 真机 | **未执行**：安全区、地址栏变化、原生返回、滚动、长按选词／复制、多指缩放 |
| Android Chrome 真机 | **未执行**：同上；桌面触控媒体模拟不能替代 |
| 真人读屏 | **未执行**：VoiceOver／TalkBack 及桌面读屏的隐藏中文、焦点与长释义阅读 |
| 原生浏览器 200% 页面缩放 | **未执行**：已有文本放大证据不能冒充此项 |
| 全部规格人工验收矩阵签收 | **未完成**：自动覆盖以本报告列出的测试为准，不推定所有组合和所有管理权限场景均已验收 |

没有将未执行项记为通过。上述缺失，尤其真机与全后端非绿，仍阻塞上线和 Issue 完成关闭。

## 发布与回退

先发布新增后端读取接口，再启用前端学习路由。后端接口暂不可用时明确重试，保留管理入口，不静默换源。

回退先恢复旧前端，再按需撤回新增只读接口；既有长期掌握与数据归属不变，不需回滚学习成果，旧前端可忽略本地学习草稿。原实施交付未部署；后续用户授权的当前 systemd 环境部署已单独记录，未执行数据库迁移或关闭需求。
