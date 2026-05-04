#!/usr/bin/env python3
"""FastAPI 启动脚本 - uvicorn 运行"""

import sys
from pathlib import Path

# 确保 backend/ 在 sys.path 中
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import uvicorn

from app.core.config import settings


def main():
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host="0.0.0.0",
        port=5003,
        reload=True,
    )


if __name__ == "__main__":
    main()
