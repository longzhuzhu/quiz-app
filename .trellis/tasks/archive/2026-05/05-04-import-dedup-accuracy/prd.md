# PRD: 智能导入去重与准确率提升

## Problem

### 问题 1：重复导入导致题目重复
同一文件多次上传导入，或 LLM 在不同 chunk 中重复提取同一题目，都会导致 `questions` 表中出现大量重复题目。当前 bank_id=2 有 1233 道题，但按 content 去重只有 250 道唯一题目，同一题目最多重复 14 次。

**根因**：`_save_parsed_question()` 和 `_write_question_to_bank()` 完全没有去重检查。`duplicate_safety_score` 硬编码为 1.0，`duplicate_json` 字段从未写入。

### 问题 2：LLM 解析准确率低，远不如旧版正则
CIPT 283 题 PDF：
- 旧版正则解析：283 题，270 唯一（准确率 95%+）
- 新版 LLM 解析（Job 1）：243 题（漏了 40 题）
- 新版 LLM 解析（Job 2）：994 题（711 道是幻视/重复，准确率约 28%）

**根因**：
1. LLM Prompt 缺少"只提取有明确题号标记的题目"约束，从非题目文本中幻视出大量假题目
2. 答案参考表被附加到**每个 chunk** 末尾（行 843-844），LLM 可能将答案表条目本身当作题目提取
3. chunk 合并时边界不精确，导致同一题被两个 chunk 各提取一次
4. 旧版有 `_question_signature()` 去重，新版完全没有

---

## Acceptance Criteria

### AC-1：题内去重（同一 ImportJob 内）
- [ ] 同一 ImportJob 内，LLM 解析出的题目如果与已入库题目 content 相同（忽略空白差异），应自动跳过
- [ ] 跳过的重复题目记录在 `ImportParsedQuestion.review_status = "duplicate"`
- [ ] `ImportJob.imported_questions` 不计重复题

### AC-2：跨导入去重（同一 Bank 内已有题目）
- [ ] 导入前先查询 Bank 下已有题目，构建 `seen_signatures` 集合
- [ ] 新题目签名匹配已有题目时，跳过并标记为 `duplicate`
- [ ] 复用旧版 `_question_signature()` 签名逻辑（question_type + content + options + correct_answer）

### AC-3：同文件重复导入检测
- [ ] `create_smart_import_job()` 检查 `ImportJob.file_hash`，如果同 bank 下已有相同 file_hash 的 completed/partial_imported 任务，返回提示而非创建新任务
- [ ] 用户可选择"强制重新导入"覆盖此检查

### AC-4：LLM 幻视抑制
- [ ] Prompt 增加"只提取有明确题号标记（如 Q1、Question #N、数字编号等）的题目，忽略没有题号标记的段落"约束
- [ ] Prompt 增加"如果一段文字看起来像知识点讲解而非考试题目，不要将其转化为题目格式"
- [ ] `_quality_check()` 增加 `source_question_no` 检查：无题号的题目 `duplicate_safety_score` 降至 0.5

### AC-5：答案参考表优化
- [ ] 答案参考表不再附加到每个 chunk，改为仅在 `_build_llm_prompt()` 中作为 system prompt 的参考信息
- [ ] 答案参考表从 chunk_text 中移除，chunk_text 只包含题目原文

### AC-6：准确率验证
- [ ] CIPT 283 题 PDF 重新导入后，`imported_questions` 应 >= 270（与旧版相当）
- [ ] 唯一题目占比 >= 90%（无大量重复）
- [ ] 自动入库的题目中，content 与原文匹配率 >= 85%

---

## Design

### 去重签名（复用旧版逻辑）

```python
def _question_signature(question_type: str, content: str, options: list, correct_answer: list) -> tuple:
    """生成题目唯一签名，用于去重"""
    normalized_options = json.dumps(
        sorted(options, key=lambda o: o.get("label", "")),
        sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ) if isinstance(options, list) else str(options)
    normalized_answer = ",".join(sorted(a.strip().upper() for a in correct_answer)) if correct_answer else ""
    return (
        question_type,
        (content or "").strip(),
        normalized_options,
        normalized_answer,
    )
```

### 去重检查时机

1. **`_save_parsed_question()` 入库前**：检查 `seen_signatures`（Bank 已有 + 本 Job 已入库）
2. **`_write_question_to_bank()` 写入前**：双重保险，再次检查 Question 表

### `_save_parsed_question()` 修改

```python
def _save_parsed_question(db, parsed, import_job, seen_signatures, answer_key_map=None):
    # ... 现有质量检查逻辑 ...

    sig = _question_signature(parsed.question_type, parsed.content, parsed.options_json, correct_answer_list)
    if sig in seen_signatures:
        parsed.review_status = "duplicate"
        parsed.issues_json = {**(parsed.issues_json or {}), "duplicate": "与已有题目重复"}
        db.commit()
        return

    seen_signatures.add(sig)

    # ... 后续自动入库逻辑 ...
```

### `_split_into_chunks()` 修改

答案参考表不再拼入 chunk_text：

```python
# Before:
chunk_text += f"\n\n--- 答案参考表 ---\n{answer_key_text}"

# After: 只返回原始题目文本，答案参考表通过 _build_llm_prompt 传递
chunks.append({
    "chunk_no": i,
    "start_page": ...,
    "end_page": ...,
    "chunk_text": chunk_text,  # 不含答案表
})
```

### Prompt 增强关键片段

```
"11. 只提取有明确题号标记的题目（如 Q1、Question #1、1. 等编号格式），"
    "忽略没有题号标记的段落、知识点讲解、案例分析说明等非题目内容。\n"
"12. 如果一段文字是知识讲解而非考试题目，不要将其转化为题目格式。\n"
```

### `_quality_check()` 增强无题号检测

```python
# 无 source_question_no 的题目，降低 duplicate_safety_score
if not parsed.source_question_no or parsed.source_question_no == "unknown":
    duplicate_safety_score = 0.5
    issues.append({"field": "source_question_no", "severity": "MEDIUM", "message": "无题号标记，可能不是正式题目"})
else:
    duplicate_safety_score = 1.0
```

---

## Scope

### In Scope
- `_save_parsed_question()` 增加去重签名检查
- `_write_question_to_bank()` 增加去重检查
- `create_smart_import_job()` 增加同文件重复导入检测
- `_split_into_chunks()` 移除答案参考表拼接
- `_build_llm_prompt()` Prompt 增强（题号约束、幻视抑制）
- `_quality_check()` 无题号检测降分
- `run_smart_import()` 传递 `seen_signatures`

### Out of Scope
- 向量去重（pgvector）— 预留但本阶段不实现
- ImportJob 取消/重试 UI — 后续任务
- 前端变更 — 本任务仅修改后端逻辑

---

## Files to Modify

| File | Change |
|------|--------|
| `backend/app/services/smart_import_service.py` | 核心修改：去重签名、Prompt 增强、答案表优化、质量检查增强 |
| `backend/app/api/routes/banks.py` | `import_questions()` 传递 seen_signatures 逻辑 |

---

## Risks

| Risk | Mitigation |
|------|-----------|
| 签名匹配过于严格导致相似但不完全相同的题目被跳过 | 签名基于 content 精确匹配 + options 排序 + answer 排序，与旧版一致 |
| Prompt 约束过强导致 LLM 遗漏真实题目 | source_question_no 检查仅降分至 0.5，不阻断自动入库；添加题号但置信度高的题目仍可入库 |
| 答案参考表从 chunk_text 移除后 LLM 找不到答案 | 答案参考表仍在 system prompt 中提供，只是不再拼到 user content 里 |
