"""专用临时 PostgreSQL；不连接或清理业务数据库，也不以 skip 隐藏缺失能力。"""

from contextlib import contextmanager
from pathlib import Path
import os
import shutil
import socket
import subprocess
import tempfile

from sqlalchemy import create_engine


@contextmanager
def isolated_postgres():
    bindir = Path(os.environ.get("PG_BINDIR", "/usr/lib/postgresql/16/bin"))
    initdb = shutil.which("initdb") or str(bindir / "initdb")
    pg_ctl = shutil.which("pg_ctl") or str(bindir / "pg_ctl")
    with tempfile.TemporaryDirectory(prefix="vocab-pg-", dir=Path.home()) as root:
        data = str(Path(root) / "data")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        subprocess.run([initdb, "-D", data, "--auth=trust", "--no-locale", "--encoding=UTF8"], check=True, capture_output=True)
        subprocess.run([pg_ctl, "-D", data, "-l", str(Path(root) / "postgres.log"), "-w", "start", "-o", f"-h 127.0.0.1 -p {port} -k {root}"], check=True, capture_output=True)
        engine = create_engine(f"postgresql+psycopg://{os.environ.get('USER', 'ubuntu')}@127.0.0.1:{port}/postgres", pool_size=12, max_overflow=0)
        try:
            yield engine
        finally:
            engine.dispose()
            subprocess.run([pg_ctl, "-D", data, "-m", "immediate", "-w", "stop"], check=True, capture_output=True)
