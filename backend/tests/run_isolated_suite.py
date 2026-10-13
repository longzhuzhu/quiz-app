"""全量回归始终使用临时 PostgreSQL，不连接配置文件中的业务数据库。"""
import argparse
import os
from pathlib import Path
import sys
import tempfile

from postgres_support import isolated_postgres


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=Path(__file__).resolve().parents[2])
    args, pytest_args = parser.parse_known_args()
    root = args.source_root.resolve()
    if not (root / "backend/tests").is_dir():
        parser.error("source-root 必须包含 backend/tests")
    with isolated_postgres() as engine, tempfile.TemporaryDirectory(prefix="quiz-suite-storage-") as storage:
        os.environ.update(
            DATABASE_URL=engine.url.render_as_string(hide_password=False),
            AI_API_KEY="", JWT_SECRET_KEY="isolated-full-suite-jwt",
            SECRET_KEY="isolated-full-suite-encryption", STORAGE_ROOT=storage,
        )
        sys.path.insert(0, str(root / "backend"))
        from app.core.database import Base
        import app.models  # 注册所有实际模型。
        Base.metadata.create_all(engine)
        import pytest
        return pytest.main(["-q", str(root / "backend/tests"), *pytest_args])


if __name__ == "__main__":
    raise SystemExit(main())
