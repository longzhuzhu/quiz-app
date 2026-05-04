# Diagnosis Step 0 — CIPT 283 题 PDF smart_import 失血点量化

> 执行人：Trellis Research Agent · 仅读 + 离线分析；**未调用 LLM、未改任何代码**
> 数据源：
> - PDF 静态分析脚本：`research/scripts/static_pdf.py`（输出 `static_pdf.out.json`）
> - DB 诊断脚本：`research/scripts/db_diag.py`（输出 `db_diag.out.json`）
> - PostgreSQL：`postgresql+psycopg://quiz@localhost:5433/quiz`（`backend/.env` 中的 `DATABASE_URL`）
> - 命中的 ImportJob：`id=7, file_name='CIPT 283题.pdf', total_pages=178, total_chunks=31`

## TL;DR

| 阶段 | 期望题数 | 实际命中 | 净失血 |
|------|----------|----------|--------|
| ① pdfplumber 抽取 | 283 | 283（题号正则 100% 命中）| 0 |
| ② `_clean_text` ligature 清洗 | 477 个 `\x00` | 残留 0 | 0 |
| ③ `_split_into_chunks` 切分 | 283 题号 | 31 个 chunk × 题号并集 = 283 | 0 |
| ④ LLM 解析 | 31 chunks | 30 chunks 成功 + **1 chunk 整体 timeout** | **24 题（题号 222–245）** |
| ⑤ Reparse 卫生 | 259 唯一题号 | parsed_questions 表 275 行（**16 个题号被重复入库**）| 反向"虚胖" |

**核心结论**：丢失主因是**单点 LLM 调用 timeout**（chunk 27 = 24 题 = 全部丢失题号），不是 PDF 抽取层、不是 chunking、不是 answer-key 误触发、不是 ligature 残留。**剩余的"账面 274 imported - 实际 259 唯一题号 ≈ 15 个虚胖入库"是 reparse 路径造成的副作用**。

---

## A. 抽取层

### A.1 pdfplumber 基础统计

| 项 | 值 |
|----|---|
| 总页数 | 178 |
| 抽取后 raw 字符总数 | 332,359 |
| `_clean_text` 后字符总数 | 332,573 |
| 单页字符 min / max / avg | 15 / 3,951 / 1,868 |

### A.2 病态页（<300 字符）

| page_no | chars | 推测 |
|---------|-------|------|
| 1 | 54 | 封面 |
| 19 | 285 | 文字稀疏页（题目跨页留白）|
| 42 | 15 | **可能为分隔/图片页**，需关注 |
| 168 | 280 | 文字稀疏页 |

> 注：`_extract_pdf_pages` 的过滤条件是 `if text and text.strip()`（`smart_import_service.py:866`），上述 4 页都通过了过滤、内容已进入 normalized_text。**没有出现"静默跳过"**。

### A.3 关键正则在抽取后的命中

| 正则 | 命中（raw）| 命中（_clean_text 后）|
|------|-------|-------|
| `Question\s+#(\d+)\s+Topic\s+\d+` | 283 | **283** |
| `Correct\s+Answer:\s*[A-E]` | 282 | **282** |

> "Correct Answer" 比题数少 1 → 定位到 **Q#135** 的答案行被 pdfplumber 渲染为 `Correct Answer: thB`（前面贴了 `th` 噪声字）。该题最终仍被 LLM 正确解析入库，**不属于失血**。

### A.4 Ligature / NUL 残留

| 项 | raw | `_clean_text` 后 |
|----|-----|------|
| `\x00` 计数 | **477** | **0** |
| Unicode ligature `ﬀﬁﬂﬃﬄ` 计数 | 0 | 0 |
| 其它控制字符（除 \n\t\r）| — | **0** |

NUL 样例（已被 `_clean_text` 替换为正常单词，见 `backend/app/services/import_service.py:50-77`）：

```
fs/newsletters/<NUL>rm09 → form09
back- o<NUL>ce            → office
discuss Jane's <NUL>rst    → first
```

**结论**：`_clean_text` 完整覆盖本 PDF 的 NUL ligature；没有 Unicode 直接 ligature；`_normalize_text` 中的控制字符正则 `[\x00-\x08\x0b\x0c\x0e-\x1f]`（`smart_import_service.py:916`）也无残留可清。**抽取层不是失血点**。

---

## B. Chunking

### B.1 `_split_into_chunks` 行为

| 项 | 值 |
|----|---|
| Normalize 后字符数 | 332,750 |
| Chunk 数 | **31** |
| 单 chunk 题数 max / avg | **24** / 9.13 |
| 单 chunk 字符数超过 `CHUNK_MAX_CHARS=12000` | **0**（最大 11,926） |
| 题号横跨多个 chunk（crossover） | **0** |
| 1..283 在 chunks 并集 vs `range(1,284)` 的 diff | **空集** |

### B.2 每个 chunk 的题号清单（按 chunk_no）

| ch# | chars | qcount | qnums |
|-----|-------|--------|-------|
| 1 | 9601 | 4 | 1–4 |
| 2 | 10183 | 5 | 5–9 |
| 3 | 11699 | 9 | 10–18 |
| 4 | 11373 | 11 | 19–29 |
| 5 | 11926 | 11 | 30–40 |
| 6 | 11684 | 6 | 41–46 |
| 7 | 11620 | 7 | 47–53 |
| 8 | 11894 | 11 | 54–64 |
| 9 | 11067 | 5 | 65–69 |
| 10 | 11571 | 4 | 70–73 |
| 11 | 10766 | 10 | 74–83 |
| 12 | 8868 | 3 | 84–86 |
| 13 | 11616 | 5 | 87–91 |
| 14 | 11652 | 6 | 92–97 |
| 15 | 11525 | 9 | 98–106 |
| 16 | 9937 | 6 | 107–112 |
| 17 | 11568 | 5 | 113–117 |
| 18 | 11390 | 8 | 118–125 |
| 19 | 10740 | 3 | 126–128 |
| 20 | 11297 | 8 | 129–136 |
| 21 | 11721 | 15 | 137–151 |
| 22 | 11335 | **22** | 152–173 |
| 23 | 9535 | 15 | 174–188 |
| 24 | 11358 | 14 | 189–202 |
| 25 | 9676 | 3 | 203–205 |
| 26 | 11120 | 16 | 206–221 |
| **27** | **11848** | **24** | **222–245** ← LLM timeout 重灾区 |
| 28 | 11011 | 18 | 246–263 |
| 29 | 9422 | 3 | 264–266 |
| 30 | 11297 | 13 | 267–279 |
| 31 | 2617 | 4 | 280–283 |

### B.3 切分模式选择

`QUESTION_SPLIT_PATTERNS`（`smart_import_service.py:52-57`）四个 pattern 实际命中：

| pattern（行号 53–56）| 命中数 |
|---|---|
| `(?:^\|\n)\s*Question\s+#?\d+` | 283 |
| `(?:^\|\n)\s*QUESTION\s*[:#]\s*\d+` | 283 |
| `(?:^\|\n)\s*NEW\s+QUESTION\s+\d+` | 0 |
| `(?:^\|\n)\s*NO\.\s*\d+` | 0 |

> `_split_by_question_markers` 取 `len(matches)` 最大者；前两条同分（均 283）。两者都能正确切分，对本 PDF 等价。

### B.4 `_extract_answer_key` 触发判断

```text
answer_key_triggered: False
answer_key_total_entries: None
```

`ANSWER_KEY_PATTERN`（`smart_import_service.py:60-63`）**未命中**。该 PDF 中没有"答案表"段，因此本任务里不存在"答案表被剥离/题干被误当答案表"风险。失血点候选 ⑧ 在本 PDF 上**不成立**。

### B.5 结论

* 切分阶段所有 283 个题号 100% 进入了 chunk；
* 没有 chunk 超过 `CHUNK_MAX_CHARS`；
* 没有 crossover；
* answer-key 误触发不发生。
* **chunking 不是失血点**。唯一可改进的工程点：chunk 27 含 24 题且字符数 11,848 接近 12k 上限，是 LLM 请求耗时与 token 量最重的一个；后面 ⑤ 节会看到它正是唯一一个 timeout chunk。

---

## C. DB 既有数据（PostgreSQL · `import_jobs.id=7`）

> SQLite (`backend/quiz.db`) 中**不存在** `import_job`/`import_chunk`/`import_parsed_question`/`import_review_item`/`llm_parse_cache` 表（仍是旧版 Flask schema）。FastAPI 新版表全部在 PostgreSQL 中。
> 已用 `backend/.env` 的 `DATABASE_URL` 连上 PG，下列数据来自 PG。

### C.1 ImportJob 顶层数字

```json
{
  "id": 7, "bank_id": 4, "file_name": "CIPT 283题.pdf",
  "status": "review_required",
  "total_pages": 178, "total_chunks": 31,
  "parsed_questions": 275,
  "imported_questions": 274,
  "review_questions": 0,
  "failed_chunks": 1
}
```

> `review_questions=0` 是因为之前两条 LOW_CONFIDENCE 复核已被 accepted、一条 STEM_TOO_SHORT 已被 skipped（见 C.3）；该字段是**当前未决数**，不是历史累计。

**对账（用户视角"丢 13 道"）**：
* 用户看到的题库题数 ≈ `imported_questions = 274`，而不是 270；其中含 16 个被 reparse 重复入库的"虚胖行"（C.5）；扣除虚胖后实际唯一题号 = **259**。
* 真实丢失题号集 = `283 - 259 = 24`，全部为 **222–245**（chunk 27 的题）。
* "约 270 道"是用户的粗略印象；准确数字是 **唯一题号 259 / 期望 283**，缺口 24。

### C.2 ImportParsedQuestion 分桶（按 `import_status`/`review_status`）

| import_status | review_status | count |
|---|---|---|
| imported | auto_accepted | 272 |
| imported | accepted | 2 |
| skipped | skipped | 1 |
| **总和** | | **275** |

* `review_status='duplicate'` 行数 = **0**（说明 SCENARIO 多子题被签名误判 DUPLICATE 的失血点候选 ③ 在本 PDF 上**未发生**）。

### C.3 ImportReviewItem 分桶（按 `review_type`/`severity`/`status`）

| review_type | severity | status | count |
|---|---|---|---|
| LOW_CONFIDENCE | MEDIUM | accepted | 2 |
| STEM_TOO_SHORT | MEDIUM | skipped | 1 |

* 没有 `OPTION_COUNT_ABNORMAL` / `ANSWER_NOT_IN_OPTIONS` / `NOISE_DETECTED` 触发。
* 1 条 STEM_TOO_SHORT skipped 即唯一一条 `import_status='skipped'`；用户在题库列表里少看到的就是这一条。

### C.4 ImportChunk 状态

| status | count |
|---|---|
| parsed_cached | 28 |
| parsed | 2（chunk 23、chunk 29）|
| **failed** | **1**（chunk 27）|

`chunk_no=27, status='failed', issues_json={"error":"timed out"}, len(chunk_text)=11,848`，覆盖题号 **222–245**。

### C.5 LLM 真正解析出的题号 vs 期望

| 维度 | 数量 |
|---|---|
| `llm_response_json` 全集出现的唯一 `source_question_no` | **259** |
| 与 1..283 的 diff（**LLM 漏题清单**）| **[222–245]** （24 题，等于 chunk 27 全集）|
| `import_parsed_questions` 表的 `source_question_no` 行数 | 275 |
| 该表的唯一题号数 | **259** |
| 同题号被重复写入（reparse 副作用）的题号集 | **174–180, 182–188, 265, 266**（共 16 个题号）|

> **关键事实**：`parsed_questions=275` 与 `unique_qnums=259` 的差额 16 ≠ 1（与"`parsed_questions - imported = 1`"看起来不一致）。原因是这 16 行**全部被自动入库**（content/options 与初次入库版本略有差异，未被 `_question_signature` 命中），在 `imported_questions=274` 里同样虚胖了。换言之：
>   * **真实唯一入库题数 ≈ 274 - 15 ≈ 259**（其中 1 行 reparse 命中 signature 被跳过 → 解释"`275 - 274 = 1` 的 skipped"）；
>   * 用户看到题库里"约 270 多"实际混入了 ~15 行重复内容。

### C.6 `LlmParseCache`

* 总行数 = **40**（>31 chunks，说明确有 reparse 触发新缓存写入）。
* `_build_cache_key` 仅按 `PROMPT_VERSION + chunk_hash` 做 sha256（`smart_import_service.py:1245-1248`）；只要 `chunk_text` 完全一致就会命中缓存，因此 chunk 27 即便重试也会命中"上次 timeout 没有写缓存"的状态——**即重试不会改善 chunk 27**（除非清缓存或换 model）。

### C.7 chunks 27 的 chunk_text 头/尾抽样（已确认正常题目内容）

```
首 200 chars: Question #222 Topic 1
A computer user navigates to a page on the Internet. The privacy notice pops up and the user clicks the box to accept cookies, then continues to scroll the page to read the infor...

末 200 chars: ...g Techniques (PETs) would be best suited to support her analysis but reduce privacy risks?
A. Use sample data.
B. Use synthetic data.
C. Use anonymized data.
D. Use pseudonymized data
Correct Answer: B
```

→ 输入文本是干净的，问题在于**LLM 调用本身超时**，不在内容质量。

---

## D. 关键常量

来自 `backend/app/services/smart_import_service.py`：

| 常量 / 模式 | 值 / 行号 |
|---|---|
| `PROMPT_VERSION` | `"v1"`（行 46）|
| `CHUNK_MAX_CHARS` | `12000`（行 47）|
| `CHUNK_MIN_CHARS` | `500`（行 48）|
| `AUTO_ACCEPT_CONFIDENCE` | `Decimal("0.90")`（行 49）|
| `QUESTION_SPLIT_PATTERNS[0]` | `(?:^\|\n)\s*Question\s+#?\d+`，IGNORECASE（行 53）|
| `QUESTION_SPLIT_PATTERNS[1]` | `(?:^\|\n)\s*QUESTION\s*[:#]\s*\d+`，IGNORECASE（行 54）|
| `QUESTION_SPLIT_PATTERNS[2]` | `(?:^\|\n)\s*NEW\s+QUESTION\s+\d+`，IGNORECASE（行 55）|
| `QUESTION_SPLIT_PATTERNS[3]` | `(?:^\|\n)\s*NO\.\s*\d+`，IGNORECASE（行 56）|
| `ANSWER_KEY_PATTERN` | `(?:Answer\s*Key\|Answers?\s*:\|ANSWER\s*KEY\|正确答案)[:\s]*\n([\s\S]+?)$`（行 60-63）|
| `ANSWER_ENTRY_PATTERN` | `(\d{1,4})[.\s)]+\s*([A-Ea-e](?:\s*[,，]\s*[A-Ea-e])*\|True\|False)`（行 66-69）|
| `NOISE_PATTERNS[0]` | `CIPT\s+(?:Exam\|Dumps\|Questions\|Practice)`（行 73）|
| `NOISE_PATTERNS[1]` | `Page\s+\d+\s*(?:of\|/)\s*\d+`（行 74）|
| `NOISE_PATTERNS[2]` | `Passing\s+Score.*Time\s+Limit`（行 75）|
| `NOISE_PATTERNS[3]` | `IAPP\s+Certified\s+Information`（行 76）|
| `NOISE_PATTERNS[4]` | `www\.\S+\.(com\|net\|org)`（行 77）|
| `NOISE_PATTERNS[5]` | `ExamQuestions\s+v\d`（行 78）|
| `NOISE_PATTERNS[6]` | `by\s+Willow`（行 79）|
| `NOISE_PATTERNS[7]` | `File\s+Version\s+\d`（行 80）|

注释要点：
* `ANSWER_KEY_PATTERN` 使用 `$` + `[\s\S]+?` 末尾贪婪匹配（候选失血点 ⑧）。本 PDF 未触发，但若未来 PDF 末尾文本含 `Answers:` 字样仍存在风险。
* `NOISE_PATTERNS` 仅在 `_quality_check.noise_clean_score` 中按"被 ×0.7 一次"使用（不会一票否决），影响极小。

---

## E. 归因结论 & 建议

### E.1 13/24 道丢失分布（按定量证据）

> 用户口头说的"丢 13 道"低估了真实丢失数；**真实唯一入库题号 = 259**，缺口 = **24**。把 274 - 259 = 15 个虚胖行去掉后才与"约 270 多"吻合。

| 失血通道 | 数量 | 占比 | 证据 |
|---|---|---|---|
| **LLM 调用 timeout（chunk 27 整体丢弃）** | **24 题（222–245）** | **100%** | C.4–C.5：`status='failed', issues_json.error='timed out'` |
| chunking 切分丢题号 | 0 | 0% | B.1：`missing_after_split=[]` |
| answer-key 误触发剥离题干 | 0 | 0% | B.4：`answer_key_triggered=False` |
| `_question_signature` 误判 SCENARIO 子题为 DUPLICATE | 0 | 0% | C.2：`review_status='duplicate'` 行 = 0 |
| pdfplumber 静默跳过病态页 | 0 | 0% | A.2：4 个 <300 字符页全部进入 normalized_text |
| `_clean_text` ligature 残留导致字符破坏 | 0 | 0% | A.4：`\x00` 残留 0 |
| LLM 在非 timeout chunk 内"漏题不答" | 0 | 0% | C.5：30 个成功 chunk 的输出题号集等于输入题号集 |
| LLM JSON 解析失败整 chunk 报废 | 0 | 0% | C.4：`status='parse_failed'` 数 = 0 |
| Reparse 副作用导致**虚胖**（不丢题，反入库重复） | +15 重复行 | — | C.5：16 个题号在 parsed_questions 中重复出现，仅 1 行被 signature 拦截 |

### E.2 静态层（PDF 抽取 / chunking / answer-key / ligature）已可以排除的失血点

* L1（OCR 抽取增强）—— **本 PDF 不需要**，pdfplumber 抽取完整。
* `_extract_answer_key` 末尾贪婪匹配（候选 ⑧）—— **本 PDF 未触发**，留在通用加固里即可。
* `_split_into_chunks` 切分丢题号、crossover、超长（候选 ①前置）—— **未发生**。
* SCENARIO 多子题被签名误判 DUPLICATE（候选 ③）—— **未发生**。
* ligature / 控制字符残留（候选 ⑦）—— **未残留**。

### E.3 必须实跑 LLM 才能验证的失血点（本次未实跑）

* Prompt 规则 #11/#12 引发"保守丢弃"（候选 ⑤）。
* JSON 解析失败整 chunk 报废（候选 ⑥）。
* LLM 在长 chunk 内静默漏题（候选 ①）。

> 但 **C.5 已经从既有 `llm_response_json` 离线对账**，间接确认上述三类在本任务中**均未发生**（30 个成功 chunk 的输入/输出题号集严格相等）。
> 再次实跑时这三个问题随机性较高，建议在改造完成后用集成测试验证，而非现在补诊断。

### E.4 改造优先级建议（数据驱动）

1. **L4 / 重试与单题降噪（最高优先级）**：chunk 27 timeout 是唯一根因，应同时实现 (a) chunk 失败时按题号自动 1-题-1-call 重试；(b) 缓存 key 不入超时失败、确保 reparse 真的会重新发；(c) `call_ai_api` 加超时与重试上限；(d) `parsing` 阶段的 finalize 把"输入题号集 vs 实际入库题号集"算账写入 `error_log`，作为 reconciliation 报告。
2. **L6 / Reparse 卫生（次高）**：`run_reparse` 在保留已 imported 行的同时，应基于 `(chunk_id, source_question_no)` 去重新建 parsed_questions，避免 174–188 / 265–266 这种"虚胖"。`_question_signature` 增加 `source_question_no` 维度即可堵住。
3. **L2 / Deterministic-First 不是阻塞项**：当前 LLM 在非 timeout chunk 上 100% 命中题号，引入 deterministic baseline 主要意义是兜底 chunk 整体 timeout 与未来 prompt 回归，而不是修今天的 24 题。
4. **L1（OCR）/ ⑦（ligature）/ ⑧（answer-key）/ ③（DUPLICATE 误判）** 在本 PDF 上是 0 失血，无需为本任务的 ≥98% 目标专门改。

### E.5 最低成本补诊断建议

如果还需进一步验证（以本任务交付为目标，**完全可跳过**），最低成本方案：

* **单点重放**：取 `import_chunks` 中 chunk_no=27 的 `chunk_text`，用 `call_ai_api(messages, db, scene='smart_import')` 实跑 1 次（仅 1 次 LLM 调用），断言：
  * 不再 timeout（如果 timeout 持续，说明需要把 chunk 27 切成 2 份或换更高性能 model）；
  * 输出 `questions[*].source_question_no` 的并集 ⊇ {222..245}。
* **不需要重跑全量**：30 个成功 chunk 的 `llm_response_json` 已经在 DB 里、对账已完成，不需要消耗额外配额。

---

## Raw artifacts

| 路径 | 内容 |
|---|---|
| `research/scripts/static_pdf.py` | 静态 PDF / chunking / answer-key 分析脚本 |
| `research/scripts/static_pdf.out.json` | 上述脚本的全量输出（A、B 节数据源）|
| `research/scripts/db_diag.py` | PG `import_job=7` 全量诊断脚本 |
| `research/scripts/db_diag.out.json` | 上述脚本的全量输出（C 节数据源）|

> 复跑：`python3 research/scripts/static_pdf.py` 与 `python3 research/scripts/db_diag.py`（前者依赖 `pdfplumber`，后者依赖 `psycopg`，均已在 backend 依赖中）。
