"""Step 0 静态诊断：PDF 抽取层 + Chunking + Answer-Key。
仅读取，不调用 LLM。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

PDF_PATH = "/home/ubuntu/github/quiz-app/reference/CIPT 283题.pdf"
PROJECT_ROOT = Path("/home/ubuntu/github/quiz-app")
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import pdfplumber  # noqa: E402
from app.services.import_service import _clean_text  # noqa: E402
from app.services.smart_import_service import (  # noqa: E402
    ANSWER_ENTRY_PATTERN,
    ANSWER_KEY_PATTERN,
    CHUNK_MAX_CHARS,
    QUESTION_SPLIT_PATTERNS,
    _extract_answer_key,
    _normalize_text,
    _split_into_chunks,
)


def main() -> None:
    out: dict = {}
    raw_pages: list[tuple[int, str]] = []
    cleaned_pages: list[tuple[int, str]] = []
    with pdfplumber.open(PDF_PATH) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            t = page.extract_text() or ""
            raw_pages.append((i, t))
            cleaned_pages.append((i, _clean_text(t) if t else ""))

    out["total_pages"] = len(raw_pages)
    out["total_chars_raw"] = sum(len(t) for _, t in raw_pages)
    out["total_chars_cleaned"] = sum(len(t) for _, t in cleaned_pages)

    # 病态页（< 300 字符）
    pathological = [(p, len(t)) for p, t in cleaned_pages if len(t) < 300]
    out["pathological_pages_lt300"] = pathological
    # 字符分布
    lens = [len(t) for _, t in cleaned_pages]
    out["page_chars_min"] = min(lens) if lens else 0
    out["page_chars_max"] = max(lens) if lens else 0
    out["page_chars_avg"] = round(sum(lens) / len(lens), 1) if lens else 0

    # 全文（清洗后）
    full_clean = "\n".join(t for _, t in cleaned_pages)
    full_raw = "\n".join(t for _, t in raw_pages)

    # 题号正则命中
    pat_q = re.compile(r"Question\s+#(\d+)\s+Topic\s+\d+", re.IGNORECASE)
    pat_a = re.compile(r"Correct\s+Answer:\s*[A-E]", re.IGNORECASE)
    out["regex_question_topic_hits_clean"] = len(pat_q.findall(full_clean))
    out["regex_correct_answer_hits_clean"] = len(pat_a.findall(full_clean))
    out["regex_question_topic_hits_raw"] = len(pat_q.findall(full_raw))
    out["regex_correct_answer_hits_raw"] = len(pat_a.findall(full_raw))

    # ligature 残留
    out["nul_in_raw"] = full_raw.count("\x00")
    out["nul_in_cleaned"] = full_clean.count("\x00")
    # Unicode ligature 字符（U+FB00..U+FB04）
    lig_chars = "ﬀﬁﬂﬃﬄ"
    out["unicode_ligature_in_raw"] = sum(full_raw.count(c) for c in lig_chars)
    out["unicode_ligature_in_cleaned"] = sum(full_clean.count(c) for c in lig_chars)
    # 样例
    nul_samples = []
    for m in re.finditer(r".{0,15}\x00.{0,15}", full_raw):
        nul_samples.append(m.group(0).replace("\x00", "<NUL>"))
        if len(nul_samples) >= 5:
            break
    out["nul_samples_raw"] = nul_samples
    lig_samples = []
    for m in re.finditer(r".{0,15}[ﬀ-ﬄ].{0,15}", full_raw):
        lig_samples.append(m.group(0))
        if len(lig_samples) >= 5:
            break
    out["unicode_ligature_samples_raw"] = lig_samples

    # 残留的奇特控制字符在 cleaned 中
    weird = Counter()
    for ch in full_clean:
        o = ord(ch)
        if o < 0x20 and ch not in "\n\t\r":
            weird[hex(o)] += 1
    out["control_chars_in_cleaned"] = dict(weird)

    # ─── Chunking ───
    pages_for_split = [{"page_no": p, "text": t} for p, t in cleaned_pages]
    normalized = _normalize_text(full_clean)
    out["normalized_len"] = len(normalized)

    answer_key = _extract_answer_key(normalized)
    out["answer_key_triggered"] = bool(answer_key)
    if answer_key:
        items = sorted(answer_key.items())[:5]
        out["answer_key_sample_first5"] = items
        out["answer_key_total_entries"] = len(answer_key)

    # 按 smart_import_service 实际行为：若有 answer_key，先剔除 answer_key 段后再切
    norm_for_chunk = normalized
    answer_key_text = ""
    if answer_key:
        norm_for_chunk = ANSWER_KEY_PATTERN.sub("", normalized).strip()
        # （此处不需要构造 answer_key_text，函数签名只用作存储）

    chunks = _split_into_chunks(pages_for_split, norm_for_chunk, answer_key_text)
    out["chunk_count"] = len(chunks)
    out["chunk_max_chars_const"] = CHUNK_MAX_CHARS

    qpat = re.compile(r"Question\s+#(\d+)\s+Topic\s+\d+", re.IGNORECASE)
    chunk_summary = []
    seen_in_any_chunk: set[int] = set()
    counts_per_chunk: list[int] = []
    over_limit = []
    for c in chunks:
        text = c["chunk_text"]
        nums = sorted(set(int(m.group(1)) for m in qpat.finditer(text)))
        chunk_summary.append({
            "chunk_no": c["chunk_no"],
            "chars": len(text),
            "q_count": len(nums),
            "qnums": nums,
        })
        seen_in_any_chunk.update(nums)
        counts_per_chunk.append(len(nums))
        if len(text) > CHUNK_MAX_CHARS:
            over_limit.append((c["chunk_no"], len(text)))
    out["chunks"] = chunk_summary
    out["chunks_q_count_max"] = max(counts_per_chunk) if counts_per_chunk else 0
    out["chunks_q_count_avg"] = round(sum(counts_per_chunk) / len(counts_per_chunk), 2) if counts_per_chunk else 0
    out["chunks_over_max_chars"] = over_limit

    # crossover：题号同时出现在多个 chunk
    qnum_chunk_set: dict[int, set[int]] = {}
    for c in chunk_summary:
        for n in c["qnums"]:
            qnum_chunk_set.setdefault(n, set()).add(c["chunk_no"])
    crossover = {n: sorted(s) for n, s in qnum_chunk_set.items() if len(s) > 1}
    out["chunk_crossover_qnums"] = crossover

    # 1..283 vs chunks 并集 diff
    expected = set(range(1, 284))
    out["expected_count"] = 283
    out["seen_in_chunks_count"] = len(seen_in_any_chunk)
    out["missing_after_split"] = sorted(expected - seen_in_any_chunk)

    # 也直接查全量 normalized 中题号
    nums_in_full = sorted(set(int(m.group(1)) for m in qpat.finditer(normalized)))
    out["qnums_in_full_normalized"] = {
        "count": len(nums_in_full),
        "missing_vs_1_283": sorted(expected - set(nums_in_full)),
    }

    # 切分模式选择
    pat_hits = []
    for p in QUESTION_SPLIT_PATTERNS:
        pat_hits.append({"pattern": p.pattern, "hits": len(p.findall(norm_for_chunk))})
    out["split_pattern_hits"] = pat_hits

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
