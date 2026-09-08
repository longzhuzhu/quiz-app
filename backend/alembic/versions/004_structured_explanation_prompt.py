"""structured explanation prompt

Revision ID: 004
Revises: 003
Create Date: 2026-09-01 00:00:00.000000

migration 003 把当时的解析 prompt 硬编码写进了 `exams.ai_profile`，而
`_exam_ai_profile()` 的取值是 `ai_profile.get(...) or DEFAULT_...`，
存量行里该键非空，因此只改 Python 常量对存量考试项目完全无效。

本迁移只升级从未被用户改动过的行：存储值与旧默认 prompt 逐字节相等时才替换。
自定义过的 prompt 保持原样。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_PERSONA = "你是专业考试辅导专家。"
_CIPT_PERSONA = "你是一位 CIPT（认证信息隐私技术师）考试辅导专家。"

_OLD_EXPLANATION_BODY = (
    "请解析以下题目，说明正确答案的原因以及其他选项为什么不正确。"
    '返回 JSON 格式：{"explanation": "英文解析", "explanation_zh": "中文解析"}'
    "只返回 JSON，不要其他内容。"
)

_NEW_EXPLANATION_BODY = (
    "考生母语为中文、正在备考全英文考试，除知识点之外还需要读题训练。请完成三件事："
    "一是拆解题干结构，让考生看清题目到底在问什么；"
    "二是解析正确答案的原理；"
    "三是逐个说明错误选项属于哪一类干扰、为什么错。"
    "stem_breakdown 字段要求："
    "qualifier 只填题干中实际出现的限定词（MOST/BEST/LEAST/EXCEPT/NOT/PRIMARY/FIRST 等），没有则填空字符串；"
    "role 填题干的主体或视角；scenario 用一句话概括发生了什么；"
    "constraint 填题干给出的限定条件（法规、技术、数据生命周期阶段等），没有则填空字符串；"
    "asked 用一句中文说清到底问什么，并点明限定词的含义。"
    "distractors 只包含错误选项，不包含正确答案；"
    "type 必须从以下枚举中选一个：术语混淆、范围过窄、范围过宽、时机错误、层级错位、看似正确但非最优、与题干约束冲突、无关干扰。"
    "explanation_zh 只写正确答案的原理和相关知识点，不要重复题干拆解和干扰项分析的内容。"
    '返回 JSON 格式：{"stem_breakdown": {"qualifier": "题干限定词", "role": "主体或视角", '
    '"scenario": "场景概括", "constraint": "限定条件", "asked": "到底问什么"}, '
    '"explanation": "英文解析", "explanation_zh": "中文知识点解析", '
    '"distractors": [{"key": "A", "type": "干扰项类型", "reason": "为什么错"}]}'
    "只返回 JSON，不要其他内容。"
)

OLD_DEFAULT_EXPLANATION_PROMPT = _DEFAULT_PERSONA + _OLD_EXPLANATION_BODY
OLD_CIPT_EXPLANATION_PROMPT = _CIPT_PERSONA + _OLD_EXPLANATION_BODY
NEW_DEFAULT_EXPLANATION_PROMPT = _DEFAULT_PERSONA + _NEW_EXPLANATION_BODY
NEW_CIPT_EXPLANATION_PROMPT = _CIPT_PERSONA + _NEW_EXPLANATION_BODY

_SWAP_SQL = sa.text(
    """
    UPDATE exams
    SET ai_profile = jsonb_set(
        ai_profile,
        '{explanation_system_prompt}',
        to_jsonb(CAST(:new_prompt AS text)),
        true
    )
    WHERE ai_profile->>'explanation_system_prompt' = :old_prompt
    """
)


def _swap_prompts(pairs: Sequence[tuple[str, str]]) -> None:
    bind = op.get_bind()
    for old_prompt, new_prompt in pairs:
        bind.execute(_SWAP_SQL, {"old_prompt": old_prompt, "new_prompt": new_prompt})


def upgrade() -> None:
    _swap_prompts(
        [
            (OLD_CIPT_EXPLANATION_PROMPT, NEW_CIPT_EXPLANATION_PROMPT),
            (OLD_DEFAULT_EXPLANATION_PROMPT, NEW_DEFAULT_EXPLANATION_PROMPT),
        ]
    )


def downgrade() -> None:
    _swap_prompts(
        [
            (NEW_CIPT_EXPLANATION_PROMPT, OLD_CIPT_EXPLANATION_PROMPT),
            (NEW_DEFAULT_EXPLANATION_PROMPT, OLD_DEFAULT_EXPLANATION_PROMPT),
        ]
    )
