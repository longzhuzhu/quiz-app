"""Step 0 DB 诊断：从 PostgreSQL 抓取 ImportJob #7 (CIPT 283 题.pdf) 的细节。
仅读取，不调用 LLM。
"""
from __future__ import annotations

import json
import re
from collections import Counter

import psycopg

DSN = "postgresql://quiz:REDACTED_DB_PASSWORD@localhost:5433/quiz"
JOB_ID = 7  # 通过 file_name LIKE '%CIPT%283%' 锁定，见报告 C 节
EXPECTED = set(range(1, 284))


def main() -> None:
    out: dict = {}
    with psycopg.connect(DSN) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, bank_id, file_name, status, total_pages, total_chunks, "
            "parsed_questions, imported_questions, review_questions, failed_chunks "
            "FROM import_jobs WHERE id=%s",
            (JOB_ID,),
        )
        row = cur.fetchone()
        out["import_job"] = {
            "id": row[0], "bank_id": row[1], "file_name": row[2],
            "status": row[3], "total_pages": row[4], "total_chunks": row[5],
            "parsed_questions": row[6], "imported_questions": row[7],
            "review_questions": row[8], "failed_chunks": row[9],
        }

        cur.execute(
            "SELECT import_status, review_status, count(*) FROM import_parsed_questions "
            "WHERE import_job_id=%s GROUP BY 1,2 ORDER BY 3 DESC",
            (JOB_ID,),
        )
        out["parsed_q_buckets"] = [
            {"import_status": r[0], "review_status": r[1], "count": r[2]}
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT review_type, severity, status, count(*) FROM import_review_items "
            "WHERE import_job_id=%s GROUP BY 1,2,3 ORDER BY 4 DESC",
            (JOB_ID,),
        )
        out["review_items"] = [
            {"review_type": r[0], "severity": r[1], "status": r[2], "count": r[3]}
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT id, source_question_no, content FROM import_parsed_questions "
            "WHERE import_job_id=%s AND review_status='duplicate'",
            (JOB_ID,),
        )
        out["duplicate_rows"] = [
            {"id": r[0], "qno": r[1], "content_head": (r[2] or "")[:80]}
            for r in cur.fetchall()
        ]

        cur.execute(
            "SELECT chunk_no, status, length(chunk_text), llm_response_json "
            "FROM import_chunks WHERE import_job_id=%s ORDER BY chunk_no",
            (JOB_ID,),
        )
        chunks = cur.fetchall()
        qpat = re.compile(r"Question\s+#?(\d+)\s+Topic\s+\d+", re.IGNORECASE)
        # Need text again for qnum scanning
        cur.execute(
            "SELECT chunk_no, chunk_text FROM import_chunks WHERE import_job_id=%s ORDER BY chunk_no",
            (JOB_ID,),
        )
        chunk_texts = {r[0]: r[1] for r in cur.fetchall()}
        chunks_view = []
        seen_in_llm: set[int] = set()
        for chunk_no, status, _length, resp in chunks:
            text = chunk_texts.get(chunk_no, "")
            input_qnums = sorted(set(int(m.group(1)) for m in qpat.finditer(text or "")))
            output_qnums = []
            if resp and isinstance(resp, dict):
                for q in resp.get("questions", []) or []:
                    sno = q.get("source_question_no") if isinstance(q, dict) else None
                    if not sno:
                        continue
                    m = re.search(r"(\d+)", str(sno))
                    if m:
                        output_qnums.append(int(m.group(1)))
                        seen_in_llm.add(int(m.group(1)))
            chunks_view.append({
                "chunk_no": chunk_no,
                "status": status,
                "input_qnums_count": len(input_qnums),
                "input_qnums": input_qnums,
                "output_qnums_count": len(output_qnums),
                "output_qnums": sorted(set(output_qnums)),
                "drop_in_chunk": sorted(set(input_qnums) - set(output_qnums)),
            })
        out["chunks"] = chunks_view
        out["llm_seen_total"] = len(seen_in_llm)
        out["llm_missing_vs_1_283"] = sorted(EXPECTED - seen_in_llm)

        cur.execute(
            "SELECT source_question_no FROM import_parsed_questions WHERE import_job_id=%s",
            (JOB_ID,),
        )
        nums = []
        for (sno,) in cur.fetchall():
            if sno is None:
                continue
            m = re.search(r"(\d+)", str(sno))
            if m:
                nums.append(int(m.group(1)))
        ctr = Counter(nums)
        out["parsed_q_qnum_dupes"] = sorted([n for n, c in ctr.items() if c > 1])
        out["parsed_q_unique_qnums"] = len(set(nums))
        out["parsed_q_missing_vs_1_283"] = sorted(EXPECTED - set(nums))

        cur.execute("SELECT count(*) FROM llm_parse_cache")
        out["llm_parse_cache_rows"] = cur.fetchone()[0]

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
