# CIPT BOK 4.0.0 考点分类树（权威来源）

## 来源与版本

- 文件：`reference/IAPP_CIPT_BOK_3Dec2025-FINAL.pdf`（11 页，文件名带 3Dec2025，但内容版本为 **4.0.0**）
- Approved by: CIPT EDB，Approved on: 2025-03-25
- Effective date: **2025-09-01**
- **Supersedes: 3.2.0**
- 抽取方式：`pdfplumber` 的 `extract_text()` + `extract_tables()`，页 4–11 为分域正文

## 与 `reference/CIPT-BOK-Supplement/README.md` 的关系

supplement README 对应的是 **3.2.0**，结构为七个罗马数字域（I. Foundational Principles … VII. Evolving or Emerging Technologies in Privacy），且第七域内存在 `D.` 编号重复的笔误（`D. Ongoing Vigilance` 与 `D. Corporate IT Services`）。

4.0.0 是一次结构性改版，不是增补：域从 7 个减为 5 个，且改用「能力项（Competencies）+ 表现指标（Performance Indicators）」的表述，并新增了考试蓝图配额。3.2.0 的域**无法**一一映射到 4.0.0。因此考点分类树以 4.0.0 为准，supplement README 只能作为「延伸阅读链接」的素材，且其章节锚点是按旧结构组织的。

## 分类树

两层结构：**域（Domain）→ 能力项（Competency）**。表现指标为第三层，本任务不建模。

`MIN`/`MAX` 为该项在一次考试中出题数的下限与上限（Exam Blueprint）。

### Domain I — The privacy technologist's role in the context of the organization（15–19 题）

> 域描述：addresses the general and technical responsibilities inherent to the role of the Privacy Technologist.

| 编码 | MIN | MAX | 能力项原文 |
|---|---|---|---|
| I.A | 5 | 7 | Identify and implement legal and procedural roles and responsibilities. |
| I.B | 5 | 7 | Identify and implement technical roles and responsibilities. |
| I.C | 1 | 3 | Demonstrate knowledge of privacy risk models and frameworks and their roles in legal requirements and guidance. |
| I.D | 2 | 4 | Understand the connection between data ethics and data privacy. |

### Domain II — Data collection, use, dissemination and destruction（19–23 题）

> 域描述：covers strategies and best practices to ensure responsible and secure processing of personal information, minimizing privacy risks during personal data collection, use, dissemination, retention and destruction.

| 编码 | MIN | MAX | 能力项原文 |
|---|---|---|---|
| II.A | 8 | 10 | Demonstrate how to minimize privacy risk during personal data collection. |
| II.B | 6 | 8 | Demonstrate how to minimize privacy risk during personal data use. |
| II.C | 4 | 6 | Demonstrate how to minimize privacy risk during personal data dissemination. |

### Domain III — Privacy risk management（17–21 题）

> 域描述：addresses the critical connection between data ethics and privacy … as well as addressing concerns on intrusion, decisional interference and software security.

| 编码 | MIN | MAX | 能力项原文 |
|---|---|---|---|
| III.A | 2 | 4 | Demonstrate how to minimize the threat of intrusion and decisional interference. |
| III.B | 3 | 5 | Identify privacy risks related to software security. |
| III.C | 4 | 6 | Understand the privacy risks and impact of techniques that enable tracking and surveillance. |
| III.D | 2 | 4 | Understand the privacy risks and impact involved when using workplace technologies. |
| III.E | 3 | 5 | Demonstrate how to monitor and manage privacy risk. |

### Domain IV — Privacy by design（7–9 题）

> 域描述：focuses on the strategic integration of principles to effectively manage privacy risks within user experiences, implement value sensitive design practices, and establish robust management and monitoring controls.

| 编码 | MIN | MAX | 能力项原文 |
|---|---|---|---|
| IV.A | 4 | 6 | Implement privacy by design principles. |
| IV.B | 2 | 4 | Evaluate privacy risks in user experiences. |

### Domain V — Privacy engineering and privacy governance（9–11 题）

> 域描述：explains how to integrate privacy into an organization's technology policies and procedures, including the privacy engineering's role within the organization, privacy engineering objectives, privacy design patterns and privacy risk management throughout the phases of the development life cycle.

| 编码 | MIN | MAX | 能力项原文 |
|---|---|---|---|
| V.A | 6 | 8 | Understand and implement privacy engineering objectives. |
| V.B | 2 | 4 | Manage and monitor privacy-related functions and controls. |

## 规模与校验

- 域：5 个；能力项：16 个
- 域配额合计：MIN 67 / MAX 83
- 能力项配额按域求和与域配额一致（例：II.A+II.B+II.C = 18–24，域 II 为 19–23，存在 ±1 的收口，属官方蓝图本身的取整，不作为数据校验规则）

## 表现指标（第三层，仅供 AI 打标 prompt 参考，不建模）

每个能力项下有 2–5 条 Performance Indicator，含大量 `e.g.` 举例（如 II.B 提到 anonymization / pseudonymization / differential privacy，III.C 提到 cookies / chatbots / biometrics / location tracking）。这些举例是把真题归到能力项的最强信号，应完整写进打标 prompt，但不作为可选考点暴露给用户。
