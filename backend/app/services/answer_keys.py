"""正确答案 / 模型认定答案的选项 key 规范化。"""

from __future__ import annotations

import json
import re

_WRAP_RE = re.compile(r'^[\s「」『』“”"\'《》]+|[\s「」『』“”"\'《》]+$')


def normalize_option_key(raw) -> str:
    """Strip wrapping quotes/space and a trailing dot from a single option key."""
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return ""
    if isinstance(raw, (int, float)):
        text = str(raw)
    else:
        text = str(raw)
    text = text.strip()
    while True:
        stripped = _WRAP_RE.sub("", text).strip()
        if stripped.endswith("."):
            stripped = stripped[:-1].strip()
        if stripped == text:
            return stripped
        text = stripped


def parse_answer_keys(raw) -> list[str]:
    """Split a stored or model answer into option keys; drop empties; keep first-seen order."""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        tokens = list(raw)
    else:
        tokens = str(raw).split(",")
    keys: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        key = normalize_option_key(token)
        if not key:
            continue
        folded = key.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        keys.append(key)
    return keys


def format_answer_keys(keys: list[str]) -> str:
    """Join keys in case-insensitive sort order, matching 现网 `A,C` style."""
    return ",".join(sorted(keys, key=lambda key: key.casefold()))


def answers_equivalent(left, right) -> bool:
    """Compare two answer strings after split / strip / casefold / sort."""
    left_keys = sorted(key.casefold() for key in parse_answer_keys(left))
    right_keys = sorted(key.casefold() for key in parse_answer_keys(right))
    return left_keys == right_keys


def option_keys_from(question) -> list[str]:
    options = getattr(question, "options", None)
    if isinstance(options, str):
        options = json.loads(options)
    keys: list[str] = []
    for option in options or []:
        if not isinstance(option, dict):
            continue
        key = normalize_option_key(option.get("key"))
        if key:
            keys.append(key)
    return keys


def resolve_answer_keys(raw, option_keys: list[str]) -> tuple[list[str], list[str]]:
    """Map parsed keys onto the question's option keys (case-insensitive).

    Returns (resolved_keys, unknown_keys). Unknown keys are not in resolved.
    """
    lookup = {key.casefold(): key for key in option_keys}
    resolved: list[str] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for key in parse_answer_keys(raw):
        canonical = lookup.get(key.casefold())
        if canonical is None:
            unknown.append(key)
            continue
        folded = canonical.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        resolved.append(canonical)
    return resolved, unknown
