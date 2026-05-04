#!/usr/bin/env python3
"""后台任务 Worker 启动脚本"""

import sys
from pathlib import Path

# 确保 backend/ 在 sys.path 中
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.workers.job_worker import main

if __name__ == "__main__":
    raise SystemExit(main())
