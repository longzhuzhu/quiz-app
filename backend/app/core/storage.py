"""文件存储配置"""

import os
import hashlib
import uuid

from app.core.config import settings

# 允许导入的文件扩展名；物理文件名只由服务端生成，不使用用户提交的名称。
ALLOWED_IMPORT_EXTENSIONS = frozenset({"pdf", "xlsx", "docx"})


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


def _is_within(root: str, candidate: str) -> bool:
    """判断 candidate 的真实路径是否仍在 root 内（含符号链接解析）"""
    root_real = os.path.realpath(root)
    candidate_real = os.path.realpath(candidate)
    try:
        return os.path.commonpath([root_real, candidate_real]) == root_real
    except ValueError:
        return False


def get_frontend_dist_dir() -> str:
    """前端构建产物目录的绝对路径（不保证存在）"""
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "dist")
    )


def normalize_upload_ext(filename: str | None) -> str | None:
    """从上传文件名提取受控扩展名；不合法时返回 None

    用户提交的文件名只用于取扩展名，不参与磁盘路径构造。
    """
    if not filename:
        return None
    if "\x00" in filename:
        return None
    # 同时处理后缀分隔符：只取最后一段，避免 "a.pdf/../../x" 之类跨目录
    tail = filename.replace("\\", "/").rsplit("/", 1)[-1]
    _, dot, extension = tail.rpartition(".")
    if not dot:
        return None
    extension = extension.lower()
    if extension not in ALLOWED_IMPORT_EXTENSIONS:
        return None
    return extension


def save_upload_file(
    file_bytes: bytes, filename: str, *, category: str = "imports"
) -> tuple[str, str]:
    """保存上传文件到本地存储

    物理文件名由服务端生成（文件哈希 + 随机后缀），用户提供的 filename 不进入路径。

    返回 (file_path, file_hash)；存储根目录落在前端产物目录内时抛 ValueError。
    """
    extension = normalize_upload_ext(filename)
    if extension is None:
        raise ValueError(f"不支持的文件格式: {filename}")

    import_dir = os.path.join(settings.STORAGE_ROOT, category)
    dist_dir = get_frontend_dist_dir()
    # 私有存储根目录不得落在会被 SPA 静态托管的 frontend/dist 内
    if os.path.isdir(dist_dir) and _is_within(dist_dir, import_dir):
        raise ValueError("存储目录不能位于前端静态资源目录内")

    os.makedirs(import_dir, exist_ok=True)

    file_hash = compute_file_hash(file_bytes)

    # 使用哈希前缀作为子目录，避免单目录文件过多
    sub_dir = os.path.join(import_dir, file_hash[:2])
    os.makedirs(sub_dir, exist_ok=True)

    safe_name = f"{file_hash[:16]}_{uuid.uuid4().hex[:16]}.{extension}"
    file_path = os.path.join(sub_dir, safe_name)

    if not _is_within(import_dir, file_path):
        raise ValueError("非法的文件存储路径")

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    return file_path, file_hash
