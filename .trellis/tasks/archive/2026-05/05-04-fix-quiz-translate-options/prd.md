# fix: 答题翻译选项缺失 + 收藏单词无自动翻译

## Goal

修复答题页面两个体验问题：1）点击翻译后选项不翻译；2）收藏单词需要手动输入，无自动翻译。

## Requirements

* Bug1: `has_question_translation()` 只检查 `content_zh`，当 content_zh 存在但选项缺少 `text_zh` 时返回缓存（空 options_zh），前端不再请求 AI 翻译
* Bug1 fix: `has_question_translation()` 需同时验证所有选项都有 `text_zh`
* Bug1 fix: 前端 `has-translation` prop 也需同步检查选项翻译完整性
* Bug2: `AddVocabButton` 组件无 props，与当前题目完全脱钩
* Bug2 fix: `AddVocabButton` 接受 `initialTerm` prop，预填当前题目的英文内容
* Bug2 fix: 用户可一键收藏当前题目的核心术语，自动触发后端 `auto_translate`

## Acceptance Criteria

* [ ] 点击翻译 → 题干和选项都显示中文翻译（包括之前只翻译了题干的旧题）
* [ ] `has_question_translation()` 返回 True 当且仅当 content_zh 和所有选项 text_zh 都存在
* [ ] 前端 has-translation 判断同步更新
* [ ] 答题页面点击"收藏单词"→ 输入框预填当前题目的英文题干
* [ ] 点击保存 → 后端 auto_translate 正常工作，返回中文翻译

## Out of Scope

* 批量提取题目中的多个术语（MVP 只支持预填题干）
* 选项级别的单独收藏

## Technical Notes

- 后端 `ai_service.py:26-27` — `has_question_translation` 需改为检查选项
- 前端 `QuestionCard.vue:53` — `has-translation` prop 需改为计算函数
- 前端 `AddVocabButton.vue` — 新增 `initialTerm` prop，打开时预填
- 前端 `QuestionCard.vue:63` — 传 `:initial-term="question.content"` 给 AddVocabButton
