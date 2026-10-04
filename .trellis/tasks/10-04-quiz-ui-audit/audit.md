# Quiz UI 只读体验审计

日期：2026-10-04。使用 redesign-existing-projects，仅 Scan / Diagnose，不执行 Fix。

## 范围与证据

- 现有栈：Vue 3 + Pinia + Vue Router + Tailwind CSS 4 + Headless UI + Heroicons，纯 JavaScript。
- 源码范围：答题卡、练习页面、错题本、结果页、首页、历史页、全局导航、按钮和样式；另读错题 API 契约。
- 浏览器：本地 Vite 前端，Playwright 隔离会话，审计页面使用模拟 API 数据；没有启动后端、登录真实账号或写入真实学习记录。
- 桌面 1440×900；手机 390×844；320×568 补充检查首页与错题页。模拟数据为长英文场景题、四个长选项、30 题会话，覆盖单选与多选、已答反馈、错题展开、完成页。
- 稳定后的受测页面浏览器 console：0 errors / 0 warnings。初始模拟路由曾误截获 /src/api/client.js，修正模拟范围后重新加载；该错误属于审计工具配置，不属于产品缺陷。开发服务器输出另有后端未启动时 /api/auth/me 代理 ECONNREFUSED，故不声称整站或真实服务验证通过；这不影响已记录的模拟数据 UI 现象，也不等于真实部署存在相同故障。
- B = 浏览器复现并有源码依据；S = 源码确认。未检查真实 API 延迟、实际题库分布、真实 iOS 安全区、软键盘、读屏器与深色模式对比度。截图尺寸不是实际设备测试。
- P1 高：影响正确操作、状态可信度或核心学习闭环；P2 中：增加阅读/导航负担；P3 低：一致性与视觉细节。不将所有审美偏好都升级为缺陷。

## 1. 答题效率

| ID | 严重度/证据 | 当前问题与影响 | 建议 | 受影响文件与位置 |
|---|---|---|---|---|
| E1 | P1 / B | 多选题点选项文字后仍未选中，点原生复选框可以选中。label 的点击处理与原生 label 激活产生重复 toggle；所谓大点击区实际不可依赖。 | 以 input 的 change/v-model 为单一状态入口，整行 label 只负责扩大点击区。必须覆盖文字、空白、原生控件和键盘的回归检查。 | frontend/src/components/QuestionCard.vue:39–47,314–345 |
| E2 | P2 / B+S | 提交后“提交答案”仍启用，同时出现同为 primary 的“下一题”。点击已答选项会立即清空反馈，没有显式“重新作答”边界。 | 未答时单一主操作“提交”；提交后单一主操作“下一题”；改答/重做作为显式次级操作，保存旧结果直至新提交成功。 | frontend/src/components/QuestionCard.vue:107–114,331–334 |
| E3 | P2 / S | 没有应用级 A–D/数字选择、Enter 提交/下一题等快捷键；未按统一 radio name/fieldset 分组。 | 在正确的原生控件语义基础上补充可发现的快捷键，避免拦截输入框和多选行为。保留原生焦点，不把“缺少自定义 focus 样式”误写为“完全没有焦点”。 | frontend/src/components/QuestionCard.vue:38–54; frontend/src/components/BaseButton.vue:46–59 |

## 2. 题干阅读

| ID | 严重度/证据 | 当前问题与影响 | 建议 | 受影响文件与位置 |
|---|---|---|---|---|
| R1 | P2 / B+S | 桌面题干宽 864px，18px/29.25px，整段 font-medium；长英文情景题一整块，原始换行使用 white-space: normal 被折叠。字号和行高本身不是主要问题，行长、分段和整体加重才是。 | 保留段落/换行，题干用常规字重，限制英文阅读列约 65–75ch；原文含明确强调信息时才保留强调，不自动改写或推断限定词。 | frontend/src/components/QuestionCard.vue:31–35; frontend/src/App.vue:5; frontend/src/style.css |
| R2 | P2 / S | 翻译开关与题干相隔四个选项；切题和提交引发 props 变化时 showTranslation 重置为 false，持续使用翻译的学习者需要反复操作。 | 将翻译入口靠近题干，英文优先、中文次级；保留用户的会话显示偏好，避免提交时意外收起。 | frontend/src/components/QuestionCard.vue:57–60,195–211; frontend/src/components/TranslateButton.vue |

## 3. 选项阅读

| ID | 严重度/证据 | 当前问题与影响 | 建议 | 受影响文件与位置 |
|---|---|---|---|---|
| O1 | P2 / B | 标号与正文呈 A.Encrypt，无清晰间隔；长选项换行对齐到标号而非正文，多行对比需要反复找开头。 | 控件、标号、正文分列；标号固定窄列，正文悬挂对齐；用阅读行高而非重边框区分选项。 | frontend/src/components/QuestionCard.vue:38–53; frontend/src/views/WrongAnswersView.vue:106–125 |
| O2 | P1 / B+S | 提交后未选干扰项 opacity-50。错题复盘恰恰需要比较这些内容，界面却将其变成像不可读的禁用项；选项本身无“你的选择/正确答案”文本标签。 | 选项文字保持正常对比度；用边框、轻背景和明确标签表示结果，避免只依赖红绿；正确且已选的状态同时说明。 | frontend/src/components/QuestionCard.vue:385–418 |

## 4. 答题反馈

| ID | 严重度/证据 | 当前问题与影响 | 建议 | 受影响文件与位置 |
|---|---|---|---|---|
| F1 | P1 / B | 开启自动下一题后，错误回答也在 1500ms 后离开。手机实测进入第 2 题时 scrollY=577、题干 top=-372px，新题开头在屏幕上方。 | 默认错题停留、正确题可按偏好自动继续；等待期间提供取消；切题将题干/标题送到可见区，管理焦点。 | frontend/src/views/QuizView.vue:287–340; frontend/src/components/QuestionCard.vue |
| F2 | P2 / B+S | 反馈在 AI 工具行下方，主要只报对错和答案字母。缓存解析自动展开为小字号纯文本大块，且无折叠；“下一题”排在解析之后。 | 先给“你的答案 → 正确答案 → 核心原因”；把详细解析按题干、原理、干扰项分段并可折叠；短反馈和继续操作保持可达。AI 更新与答案更正放次级入口，并保留已有更正确认。 | frontend/src/components/QuestionCard.vue:56–115; frontend/src/components/ExplainButton.vue |
| F3 | P2 / S | 错误选项摇晃动画没有 reduced-motion 分支，反馈区域没有 live/status 语义。 | 移除惩罚式摇晃，保留安静稳定的反馈；添加适当状态播报并尊重减少动效偏好。 | frontend/src/components/QuestionCard.vue:73–105,416; frontend/src/style.css:25–31 |

## 5. 错题复习

| ID | 严重度/证据 | 当前问题与影响 | 建议 | 受影响文件与位置 |
|---|---|---|---|---|
| W1 | P1 / S | 错题详情展示正确答案，却没有上次错选的答案/选项；API 也未提供 user_answer，不能只靠前端样式补齐。摘要提前给答案，不适合直接做主动回忆。 | 明确区分“重做”和“看解析”；重做先隐藏答案，复盘展示上次错选与正确选项对照。后续若实施，需确认“最近一次错误”数据契约，不拿最近一次正确答案替代。 | frontend/src/views/WrongAnswersView.vue:62–153; backend/app/api/routes/wrong.py:48–82; backend/app/schemas/wrong.py |
| W2 | P1 / S+B | 结果页题干 truncate，内容无法展开，列表项不能打开完整复盘；“查看错题”进入整个项目错题本而非本次错题。详情还限制在 max-h-64 内部滚动区。 | 支持本次错题筛选和完整题目详情，保留原题序号与答案对照；项目错题本另作入口。避免手机嵌套滚动成为唯一路径。 | frontend/src/views/QuizResultView.vue:56–79; frontend/src/views/WrongAnswersView.vue |
| W3 | P2 / B | 错题展开时缓存中文已显示，按钮仍写“翻译”；点击“隐藏翻译”后中文仍显示。translationVisible 只绑定按钮，未控制题干和选项渲染。 | 让同一显示状态控制题干、选项和按钮；区分翻译是否存在与翻译是否显示。 | frontend/src/views/WrongAnswersView.vue:101–135,189,218–227 |
| W4 | P2 / S | 错题只有题库筛选，无搜索、按错题频次等视图、单题重练、已掌握列表或撤销。API 按最近错题排序后一次返回所有未掌握题；点击掌握立即移除。 | 先提供搜索、频次/最近排序、单题重练和掌握撤销；大量错题再加分页/分批获取。显示上次出错时间，统计注明“整个项目”口径，避免与题库筛选混淆。不要一次堆出十种筛选。 | frontend/src/views/WrongAnswersView.vue:28–40,248–262; backend/app/api/routes/wrong.py:55–61,135–171 |

## 6. 切题导航

| ID | 严重度/证据 | 当前问题与影响 | 建议 | 受影响文件与位置 |
|---|---|---|---|---|
| N1 | P1 / B | 未提交选项只保存在卡片本地；选中后切题再切回，勾选丢失，没有草稿或丢失提示。 | 按 questionId 保留当前会话草稿，明确“已选未提交/已提交”状态；与历史判定结果分开。 | frontend/src/components/QuestionCard.vue:195–211; frontend/src/views/QuizView.vue:158–180,268–270; frontend/src/stores/quiz.js |
| N2 | P2 / B+S | 未答时没有“下一题/跳过”，必须跳题号；手机题号条隐藏滚动提示，当前第 30 题时题号 30 的 x=1056px，不在 390px 屏幕内。桌面逐题列表同时展示“1”和“第1题”，较长。 | 始终提供前后切题；题号网格用于快速跳转，当前项自动进入可见区；手机使用按需展开题目面板，显示未答/错题入口。 | frontend/src/components/QuestionCard.vue:108–114; frontend/src/views/QuizView.vue:38–111,268–284 |

## 7. 进度可见性

| ID | 严重度/证据 | 当前问题与影响 | 建议 | 受影响文件与位置 |
|---|---|---|---|---|
| P1 | P1 / B | 顶部进度条按 (currentIndex+1)/length 算。直接跳到第30题，条为100%，已答仍0/30；手机隐藏了桌面已答/未答统计，难区分位置与完成度。 | “第30/30题”只表达当前位置；进度条按已提交数量算，持续显示“已答 x/30 · 未答 y”，配语义化进度值。 | frontend/src/views/QuizView.vue:11–13,30–34,43,72–95; frontend/src/components/QuestionCard.vue:25–29 |
| P2 | P2 / S | 只有最后一题提交后才出现“完成答题”，无常驻结束入口或未答题检查；结果页总题数、正确、错误三项没有未答数。跳答情况下结果不完整。 | 提供独立结束/交卷入口，结束前明确未答题数并可回到未答题；结果区分正确、错误、未答与准确率分母。 | frontend/src/components/QuestionCard.vue:112–113; frontend/src/views/QuizView.vue:348–354; frontend/src/views/QuizResultView.vue:40–53 |

## 8. 移动适配

| ID | 严重度/证据 | 当前问题与影响 | 建议 | 受影响文件与位置 |
|---|---|---|---|---|
| M1 | P1 / B | 390px 长题首屏提交按钮 y≈1163px；显示解析后同一滚动位置下“下一题”y≈991px，高于844px视口下界。题号条和全局导航常驻，主操作却滚出视野。 | 答题模式用一个安静的底部操作区，保留主操作与简短进度；题号按需展开，全局导航收起到明确退出入口；为正文预留底栏空间。不能把题干本身压缩成更小字体。 | frontend/src/App.vue:4–13; frontend/src/components/MobileNav.vue:2–28; frontend/src/views/QuizView.vue:101–114; frontend/src/components/QuestionCard.vue:107–115 |
| M2 | P1 / B | 错题摘要为横向布局，掌握按钮与箭头占据阅读宽度；320px 题干仅122px，长英文变成几十行窄柱。 | 手机题干占满宽度，掌握/展开移到独立操作行；列表使用可展开的适度摘要，详情不截断。题号和主要按钮目前约32px高，建议放大到44–48px的触摸设计目标。 | frontend/src/views/WrongAnswersView.vue:63–87; frontend/src/components/BaseButton.vue:56–59; frontend/src/views/QuizView.vue:104–109 |
| M3 | P2 / S，待真机验证 | 题号条固定 bottom-14，全局 MobileNav 自己加 safe-area padding；两条栏的相对定位不随实际全局栏高度联动，存在 iOS 安全区覆盖风险。 | 共享底部高度与安全区计算，或合并为单栏；后续需用真实 iOS 浏览器、横屏和文字放大验证，不能依据桌面仿真声称已复现重叠。 | frontend/src/views/QuizView.vue:102; frontend/src/components/MobileNav.vue:2–3; frontend/src/style.css:40–41 |

## 9. 视觉层级

| ID | 严重度/证据 | 当前问题与影响 | 建议 | 受影响文件与位置 |
|---|---|---|---|---|
| H1 | P1 / B | 首页先呈四张统计卡、热力图和趋势，再呈“继续上次答题”与题库。390×844 首屏没有继续按钮。核心任务的优先级被数据展示挤走。 | 继续上次答题/开始练习/待复习错题优先；统计收成简洁一行，趋势移到次级学习概览。保留有价值的数据，不再让它们挡住开始入口。 | frontend/src/views/HomeView.vue:9–102; frontend/src/components/PracticeHeatmap.vue; frontend/src/components/PracticeTrendChart.vue |
| H2 | P2 / B+S | 题干全部中粗、工具行在反馈之前、提交与下一题同时高亮；重要反馈与辅助工具没有清晰优先关系。 | 信息层级固定为题干 → 选项 → 主操作/即时反馈 → 可展开解释 → 辅助工具；每个交互状态只有一个主动作。 | frontend/src/components/QuestionCard.vue:31–115; frontend/src/components/BaseButton.vue |

## 10. 不必要的 UI 噪音与状态缺口

| ID | 严重度/证据 | 当前问题与影响 | 建议 | 受影响文件与位置 |
|---|---|---|---|---|
| U1 | P2 / B+S | 首页四种装饰色，答题紫蓝渐变进度、重边框选项、胶囊元信息、红绿反馈和蓝色解析同时出现；全局导航、已答次数、复制、收藏单词和更正答案都常驻。红绿对错颜色有语义，问题是装饰色和工具权重过高。 | 中性底色+一种操作色，保留对错语义色；减少渐变、层层卡片边框和摇晃；将次数/复制/词汇/更新解析/更正等工具降权或按需显露，翻译保留便捷入口。 | frontend/src/style.css; frontend/src/views/HomeView.vue:9–69; frontend/src/components/QuestionCard.vue:5–114; frontend/src/components/NavBar.vue; frontend/src/components/MobileNav.vue |
| U2 | P2 / S | 练习加载失败直接回首页；错题/历史加载只有 finally 无错误态，初次失败可能呈现“暂无错题/暂无记录”，已加载时可能保留陈旧数据。空、失败、加载没有可靠区分。 | 使用明确可重试的内联错误态；保留内容但标注刷新失败，不把网络失败包装成已掌握或空记录。复用现有 SkeletonLoader，不为追求风格重写状态体系。 | frontend/src/views/QuizView.vue:242–260; frontend/src/views/WrongAnswersView.vue:229–238,266–270; frontend/src/views/HistoryView.vue:128–136 |

## 保留与不做

- 保留现有左对齐题目、18px题干、16px选项、整行选项交互的目标、明暗模式、已答结果恢复、骨架屏、提交中禁用与错误 toast；修正缺口而不是推翻已有功能。
- 不因“默认字体/图标常见”就更换字体和 Heroicons。系统字体目前可读，排版与操作可靠性优先。
- 不套用营销站手法：不加 hero、背景照片、噪点、玻璃特效、视差、破格网格、弹簧动画或夸张标题；不为艺术感牺牲原题准确性。
- 候选方向而非已批准设计：保留既有栈与流程，做聚焦答题界面。所有新交互和接口变更均需要之后单独确认，当前无实现授权。

## 建议优先顺序

1. 可靠性：E1 多选点击、N1 草稿、P1 进度口径、F1 错题自动跳过/切题阅读起点。
2. 手机核心路径：M1 主操作可达、M2 错题阅读宽度、H1 首页继续入口。
3. 复习闭环：O2 完整选项对比、W1 上次错选、W2 本次错题复盘、W3 翻译状态。
4. 排版与降噪：R1/O1 题干及选项结构、F2 解析分层、H2/U1 辅助控件降权。
5. 边界状态：U2 失败/空态、W4 掌握撤销与大列表、P2 未答检查、E3/F3 语义与键盘，M3 真机安全区验证。

## 后续若实施的验收建议（不在本次执行）

- 选项文字/空白/input/键盘各激活一次，只产生一次选中状态变化。
- 未提交草稿切题后恢复；草稿不计入已提交进度。
- 未答情况下跳至最后一题，完成度仍为0%；位置和进度分别显示。
- 错题默认停留；自动/手动切题后，题干起点可见，焦点合理。
- 长英文、长选项与长解析在320–390px、文字放大时可读；主操作不被底栏覆盖。
- 错题可比较历史错选与正确选项；本次结果可直接进入本次错题详情。
- 翻译按钮与内容显隐一致；已掌握误操作可撤销。
- API 失败显示失败而不是空记录；深色、读屏、减少动效与实际iOS需补测。

## 产物

research/ 保留桌面答题、手机答题、手机反馈、手机错题、手机结果与手机首页截图，全部是隔离数据；只用于说明当前组件布局，不代表真实题库内容或正确答案质量。

本次不运行产品构建/测试，不声称回归通过；只验证审计现象。任务保持 planning，无代码、依赖、配置、测试变更，无提交或部署。
