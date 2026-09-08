# 改进 AI 解析 prompt：输出题干结构拆解与干扰项类型

## 背景

用户备考 CIPT（全英文考试，90 题 / 150 分钟，考场不允许带词典），当前刷题的主要瓶颈是英文阅读：

1. 生词多（基础词 + 隐私领域术语）
2. 词都认识但长句读不懂题意 —— 尤其是场景题里"到底在问什么"被埋在铺垫后面

现有 AI 解析只回答"为什么这个答案对、其他为什么错"，属于**知识点**辅导，完全没有覆盖第 2 类困难（**读题**辅导）。

## 目标

在不改数据库表结构、不改前端渲染的前提下，让 AI 解析额外产出两块内容：

1. **题干结构拆解** —— 角色、场景、约束、题干限定词、到底问什么
2. **干扰项类型** —— 每个错误选项属于哪一类干扰，以及为什么错

## 非目标

- 不新增 `Question` 表字段、不做结构化存储（保持 `explanation` / `explanation_zh` 两个 text 字段）
- 不改前端组件（现有 `whitespace-pre-wrap` 渲染分段文本即可）
- 不做单题"重新解析"入口（已有 `backend/scripts/clear_question_explanations.py` 覆盖重生成需求）

## 方案

### 1. AI 返回契约扩展（向后兼容）

新默认 prompt 要求 LLM 返回：

```json
{
  "explanation": "英文整体解析",
  "explanation_zh": "中文知识点解析（只讲正确答案的原理）",
  "stem_breakdown": {
    "qualifier": "MOST",
    "role": "题干视角/主体",
    "scenario": "发生了什么",
    "constraint": "限定条件",
    "asked": "到底问什么（含限定词含义）"
  },
  "distractors": [{"key": "A", "type": "范围过窄", "reason": "..."}]
}
```

`stem_breakdown` / `distractors` 均为**可选**字段。`Exam.ai_profile.explanation_system_prompt`
是用户可编辑的，存量自定义 prompt 仍返回旧的 2 键结构，必须继续可用。

### 2. 服务层组装（`ai_service.explain_question`）

由**服务端**按固定顺序把结构化字段渲染成分段中文文本，而不是让 LLM 自己拼版式 —— 版式由代码控制才稳定。

存入 `explanation_zh` 的最终文本：

```
【题干拆解】
限定词：MOST（问"最优"而不是"可行"）
角色：...
场景：...
约束：...
问的是什么：...

【知识点解析】
<LLM 的 explanation_zh>

【干扰项分析】
A（范围过窄）：...
C（术语混淆）：...
```

降级规则：`stem_breakdown` 和 `distractors` 都缺失时，`explanation_zh` 原样存入（等价于改动前的行为）。
`explanation` 字段读取改为容错，缺键不再 `KeyError`。

### 3. 干扰项类型采用封闭集合

给 LLM 固定 8 类，输出才可比、可统计，用户也能积累"我总是栽在哪一类"的认知：

术语混淆 · 范围过窄 · 范围过宽 · 时机错误 · 层级错位 · 看似正确但非最优 · 与题干约束冲突 · 无关干扰

### 4. 题干限定词

`qualifier` 显式抽取 MOST / BEST / LEAST / EXCEPT / NOT / PRIMARY / FIRST 等，直接针对"把问的方向读反"这一高频错因。

### 5. 存量 exam 的 prompt 迁移（关键）

`migration 003` 已经把旧 CIPT prompt **硬编码写入** `exams.ai_profile` 行。
`_exam_ai_profile()` 的取值是 `ai_profile.get(...) or DEFAULT_...`，存量行里该键非空，
所以**只改 Python 常量对存量考试项目完全无效**。

新增 `migration 004`：仅当 `ai_profile->>'explanation_system_prompt'` 与旧默认值
（旧通用默认 / 旧 CIPT 默认）**逐字节相等**时才升级为新 prompt；用户自定义过的行不动。

## 验收标准

| 条件 | 必须 |
|---|:---:|
| 新默认 prompt 含 `stem_breakdown` / `distractors` 键与 8 类干扰项枚举 | ✅ |
| `explain_question` 能把结构化字段组装成分段 `explanation_zh` | ✅ |
| 旧 2 键返回结构仍可用（自定义 prompt 不被破坏） | ✅ |
| LLM 漏返 `explanation` 键不抛 `KeyError` | ✅ |
| migration 004 的旧 prompt 字面量与 migration 003 写入的值完全一致 | ✅ |
| 不新增数据库列、不改前端组件 | ✅ |
| 单元测试覆盖以上路径且通过 | ✅ |

## 生效方式（部署后）

1. `alembic upgrade head` —— 升级存量 exam 的 prompt
2. `python backend/scripts/clear_question_explanations.py --apply` —— 清空旧格式解析缓存，
   下次答题重新生成（`has_question_explanation()` 命中缓存就不会重算，不清则看不到新格式）
