"""平台题库迁移：双后端、存量升级、约束与受控降级。

覆盖：
- 空库与存量库都能真实 Alembic 升级到 head（不用 create_all / stamp）
- 个人存量数据不被回填成平台数据，也不被自动公开
- 关键 CHECK/UNIQUE/FK 在两种后端都真实生效
- 无新平台数据时可降级到 base 再升级；有平台数据时降级必须显式拒绝

边界：
- 全部使用临时数据库与 -x url= 覆盖，不连接 backend/.env 的业务库。
- PostgreSQL 使用隔离实例；SQLite 使用绝对路径文件库。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from postgres_support import isolated_postgres  # noqa: E402


def _run_alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "DATABASE_URL": url,
        "AI_API_KEY": "",
        "JWT_SECRET_KEY": "platform-migration-test",
        "SECRET_KEY": "platform-migration-test",
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"url={url}", *args],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def _tables(database: Path) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }


PLATFORM_TABLES = {
    "platform_banks",
    "platform_draft_questions",
    "platform_bank_releases",
}


# ─── SQLite ──────────────────────────────────────────────────────


def test_empty_sqlite_upgrades_and_has_platform_tables(tmp_path):
    database = tmp_path / "empty.db"
    result = _run_alembic(_sqlite_url(database), "upgrade", "head")
    assert result.returncode == 0, result.stderr

    assert PLATFORM_TABLES <= _tables(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("015",)
        # 外键必须真实存在，而不是只在 ORM metadata 里。
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        fks = connection.execute(
            "SELECT \"table\", \"from\" FROM pragma_foreign_key_list('question_banks')"
        ).fetchall()
        assert ("platform_bank_releases", "source_platform_bank_id") in fks


def test_sqlite_round_trip_without_platform_data(tmp_path):
    database = tmp_path / "roundtrip.db"
    assert _run_alembic(_sqlite_url(database), "upgrade", "head").returncode == 0

    downgraded = _run_alembic(_sqlite_url(database), "downgrade", "base")
    assert downgraded.returncode == 0, downgraded.stderr
    assert _tables(database) == {"alembic_version"}

    assert _run_alembic(_sqlite_url(database), "upgrade", "head").returncode == 0


def test_existing_personal_rows_are_not_backfilled(tmp_path):
    database = tmp_path / "legacy.db"
    assert _run_alembic(_sqlite_url(database), "upgrade", "002").returncode == 0
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO users (id, username, email, password_hash, is_admin, created_at) "
            "VALUES (1, 'nianyu', 'n@example.invalid', 'x', 1, '2026-01-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO question_banks (id, name, question_count, created_at) "
            "VALUES (1, '老题库', 1, '2026-01-01 00:00:00')"
        )
        connection.commit()

    result = _run_alembic(_sqlite_url(database), "upgrade", "head")
    assert result.returncode == 0, result.stderr

    with sqlite3.connect(database) as connection:
        bank = connection.execute(
            "SELECT source_platform_bank_id, source_platform_release_id FROM question_banks WHERE id=1"
        ).fetchone()
        assert bank == (None, None)
        assert connection.execute("SELECT COUNT(*) FROM platform_banks").fetchone() == (0,)


def test_sqlite_constraints_are_enforced(tmp_path):
    database = tmp_path / "constraints.db"
    assert _run_alembic(_sqlite_url(database), "upgrade", "head").returncode == 0

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO users (id, username, email, password_hash, is_admin, created_at) "
            "VALUES (1, 'u', 'u@example.invalid', 'x', 1, '2026-01-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO exams (id, owner_id, slug, name, short_name, locale, sort_order, "
            "importer_profile, ai_profile, created_at) "
            "VALUES (1, 1, 'e', 'E', 'E', 'en-US', 0, 'examtopics-pdf', '{\"x\":1}', "
            "'2026-01-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO platform_banks (id, name, is_listed, created_at, updated_at) "
            "VALUES ('src-1', '平台库', 0, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO platform_bank_releases (id, platform_bank_id, version_number, name, "
            "question_count, schema_version, payload, created_at) "
            "VALUES ('rel-1', 'src-1', 1, '平台库', 1, 1, '[]', '2026-01-01 00:00:00')"
        )
        connection.commit()

        # 来源字段必须成对出现。
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO question_banks (id, name, question_count, created_at, exam_id, "
                "source_platform_bank_id) VALUES (10, '半套', 0, '2026-01-01 00:00:00', 1, 'src-1')"
            )
        connection.rollback()

        # 同一项目同一来源只能有一份副本。
        connection.execute(
            "INSERT INTO question_banks (id, name, question_count, created_at, exam_id, "
            "source_platform_bank_id, source_platform_release_id) "
            "VALUES (11, '副本', 0, '2026-01-01 00:00:00', 1, 'src-1', 'rel-1')"
        )
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO question_banks (id, name, question_count, created_at, exam_id, "
                "source_platform_bank_id, source_platform_release_id) "
                "VALUES (12, '副本2', 0, '2026-01-01 00:00:00', 1, 'src-1', 'rel-1')"
            )
        connection.rollback()

        # 来源与版本必须匹配：不能用别的来源的版本。
        connection.execute(
            "INSERT INTO platform_banks (id, name, is_listed, created_at, updated_at) "
            "VALUES ('src-2', '另一库', 0, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        connection.commit()
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO question_banks (id, name, question_count, created_at, exam_id, "
                "source_platform_bank_id, source_platform_release_id) "
                "VALUES (13, '拼凑', 0, '2026-01-01 00:00:00', 1, 'src-2', 'rel-1')"
            )
        connection.rollback()

        # 个人题库的空来源不受唯一约束限制。
        connection.execute(
            "INSERT INTO question_banks (id, name, question_count, created_at, exam_id) "
            "VALUES (14, '自建', 0, '2026-01-01 00:00:00', 1)"
        )
        connection.execute(
            "INSERT INTO question_banks (id, name, question_count, created_at, exam_id) "
            "VALUES (15, '自建2', 0, '2026-01-01 00:00:00', 1)"
        )
        connection.commit()


def test_import_job_xor_and_parsed_pointer_constraints(tmp_path):
    database = tmp_path / "import_targets.db"
    assert _run_alembic(_sqlite_url(database), "upgrade", "head").returncode == 0

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO users (id, username, email, password_hash, is_admin, created_at) "
            "VALUES (1, 'u', 'u@example.invalid', 'x', 1, '2026-01-01 00:00:00')"
        )
        connection.execute(
            "INSERT INTO platform_banks (id, name, is_listed, created_at, updated_at) "
            "VALUES ('src-1', '平台库', 0, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        connection.commit()

        base = (
            "INSERT INTO import_jobs (file_name, file_path, file_hash, file_type, status, "
            "total_pages, total_chunks, parsed_questions, imported_questions, review_questions, "
            "failed_chunks, created_at, updated_at%s) VALUES ('f','p','h','pdf','pending',"
            "0,0,0,0,0,0,'2026-01-01 00:00:00','2026-01-01 00:00:00'%s)"
        )
        # 两个目标都为空 → 拒绝。
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(base % ("", ""))
        connection.rollback()
        # 两个目标都有值 → 拒绝。
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(base % (", bank_id, platform_bank_id", ", 999, 'src-1'"))
        connection.rollback()
        # 恰好一个 → 接受。
        connection.execute(base % (", platform_bank_id", ", 'src-1'"))
        connection.commit()

        # 已解析题的两个指针不能同时有值。
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO import_parsed_questions (import_job_id, content, options_json, "
                "review_status, import_status, imported_question_id, "
                "imported_platform_question_id, inserted_new, created_at, updated_at) "
                "VALUES (1, 'x', '[]', 'pending', 'waiting', 5, 6, 0, "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')"
            )
        connection.rollback()


def test_background_job_author_constraint(tmp_path):
    database = tmp_path / "bg_author.db"
    assert _run_alembic(_sqlite_url(database), "upgrade", "head").returncode == 0

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute(
            "INSERT INTO platform_banks (id, name, is_listed, created_at, updated_at) "
            "VALUES ('src-1', '平台库', 0, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        connection.commit()

        insert = (
            "INSERT INTO background_jobs (job_type, scope_key, payload_json, status, "
            "attempt_count, max_attempts, progress_total, progress_done, success_count, "
            "skipped_count, created_at%s) VALUES ('question_import_llm','k','{}','queued',"
            "0,3,0,0,0,0,'2026-01-01 00:00:00'%s)"
        )
        # 个人任务没有作者 → 拒绝。
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(insert % ("", ""))
        connection.rollback()
        # 平台任务没有作者 → 接受。
        connection.execute(insert % (", platform_bank_id", ", 'src-1'"))
        connection.commit()


def test_downgrade_refuses_when_platform_data_exists(tmp_path):
    database = tmp_path / "has_data.db"
    assert _run_alembic(_sqlite_url(database), "upgrade", "head").returncode == 0

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO platform_banks (id, name, is_listed, created_at, updated_at) "
            "VALUES ('src-1', '平台库', 1, '2026-01-01 00:00:00', '2026-01-01 00:00:00')"
        )
        connection.commit()

    result = _run_alembic(_sqlite_url(database), "downgrade", "base")
    assert result.returncode != 0
    assert "禁止破坏性降级" in (result.stderr + result.stdout)

    # 数据必须原样保留。
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM platform_banks").fetchone() == (1,)


# ─── PostgreSQL ──────────────────────────────────────────────────


@pytest.fixture(scope="module")
def pg_url():
    with isolated_postgres() as engine:
        yield engine.url.render_as_string(hide_password=False)


def _pg_seed_owner(url: str) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, username, email, password_hash, is_admin, created_at) "
                "VALUES (1, 'nianyu', 'n@example.invalid', 'x', true, now())"
            )
        )
    engine.dispose()


def test_postgres_upgrade_round_trip(pg_url):
    assert _run_alembic(pg_url, "upgrade", "002").returncode == 0
    _pg_seed_owner(pg_url)
    upgraded = _run_alembic(pg_url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    from sqlalchemy import create_engine, text

    engine = create_engine(pg_url)
    with engine.connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema='public'"
                )
            )
        }
        assert PLATFORM_TABLES <= tables
        # 跨后端 JSONType 在 PostgreSQL 上必须是 JSONB。
        types = dict(
            connection.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name='platform_bank_releases' "
                    "AND column_name IN ('payload')"
                )
            ).all()
        )
        assert types == {"payload": "jsonb"}

        constraints = {
            row[0]
            for row in connection.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE conname IN ("
                    "'ck_question_banks_source_pair','uq_question_banks_exam_platform_source',"
                    "'fk_question_banks_platform_release','ck_import_jobs_single_target',"
                    "'ck_background_jobs_platform_author','ck_import_parsed_questions_single_pointer')"
                )
            )
        }
        assert len(constraints) == 6

    downgraded = _run_alembic(pg_url, "downgrade", "base")
    assert downgraded.returncode == 0, downgraded.stderr

    # 降级到 base 会删掉 users；003 的非空库校验仍要求 owner 存在，
    # 因此重新升级前必须重新种入管理员（这不是本任务引入的行为）。
    assert _run_alembic(pg_url, "upgrade", "002").returncode == 0
    _pg_seed_owner(pg_url)
    assert _run_alembic(pg_url, "upgrade", "head").returncode == 0
    engine.dispose()
