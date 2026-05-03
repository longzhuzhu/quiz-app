"""文件存储配置"""

import os
import hashlib

from app.core.config import settings


def ensure_storage_root() -> None:
    """确保存储根目录存在"""
    os.makedirs(settings.STORAGE_ROOT, exist_ok=True)


def get_import_storage_path() -> str:
    """获取导入文件存储目录"""
    path = os.path.join(settings.STORAGE_ROOT, "imports")
    os.makedirs(path, exist_ok=True)
    return path


def compute_file_hash(file_bytes: bytes) -> str:
    """计算文件的 SHA-256 哈希值"""
    return hashlib.sha256(file_bytes).hexdigest()


def save_upload_file(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """保存上传文件到本地存储

    返回 (file_path, file_hash)
    """
    import_dir = get_import_storage_path()
    file_hash = compute_file_hash(file_bytes)

    # 使用哈希前缀作为子目录，避免单目录文件过多
    sub_dir = os.path.join(import_dir, file_hash[:2])
    os.makedirs(sub_dir, exist_ok=True)

    # 文件名使用 哈希_原始文件名 格式
    safe_name = f"{file_hash[:16]}_{filename}"
    file_path = os.path.join(sub_dir, safe_name)

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    return file_path, file_hash
