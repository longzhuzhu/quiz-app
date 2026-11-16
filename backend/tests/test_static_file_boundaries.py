"""前后端静态文件与上传存储的路径边界。

覆盖：
- SPA fallback 不得经编码路径、双编码、绝对路径或越界符号链接读取 dist 之外的文件
- GET 与 HEAD 的拒绝语义一致，越界请求不能退化成 SPA 页面
- 合法 dist 静态资源、SPA 客户端路由、HEAD 空正文与 /api 404 保持原行为
- 上传文件物理名由服务端生成，用户文件名只提供受控扩展名
- 存储根目录落在前端产物目录内时拒绝保存

边界：
- 只用临时目录与无敏感 fixture，不读取真实配置、密钥或用户上传文件。
- 不连接数据库：建应用只为取得静态路由，测试不触发任何业务查询。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# 单独执行本文件时也不落到业务配置：run_isolated_suite 已先设置同名变量，此处不覆盖。
_ISOLATION_ROOT = Path(tempfile.mkdtemp(prefix="quiz-static-boundary-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_ISOLATION_ROOT / 'static.db'}")
os.environ.setdefault("STORAGE_ROOT", str(_ISOLATION_ROOT / "storage"))
os.environ.setdefault("JWT_SECRET_KEY", "static-boundary-test")
os.environ.setdefault("SECRET_KEY", "static-boundary-test")
os.environ.setdefault("AI_API_KEY", "")

from app import main as app_main  # noqa: E402
from app.core import storage  # noqa: E402
from app.core.config import settings  # noqa: E402

SECRET_MARKER = "dist-outside-secret-must-not-leak"


@pytest.fixture
def dist_tree(tmp_path):
    """构造临时 dist 与 dist 之外的敏感文件"""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>spa-index</title>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('asset');", encoding="utf-8")
    (dist / "robots.txt").write_text("User-agent: *", encoding="utf-8")

    secret = tmp_path / "secret.txt"
    secret.write_text(SECRET_MARKER, encoding="utf-8")
    return dist, secret


@pytest.fixture
def client(dist_tree, monkeypatch):
    dist, _ = dist_tree
    monkeypatch.setattr(app_main, "get_frontend_dist_dir", lambda: str(dist))
    with TestClient(app_main.create_app()) as test_client:
        yield test_client

def _assert_not_leaked(response, secret_marker: str = SECRET_MARKER) -> None:
    assert secret_marker not in response.text


def test_legit_static_assets_and_spa_routes_still_work(client):
    index = client.get("/index.html")
    assert index.status_code == 200
    assert "spa-index" in index.text

    root = client.get("/")
    assert root.status_code == 200
    assert "spa-index" in root.text

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "console.log" in asset.text

    direct = client.get("/robots.txt")
    assert direct.status_code == 200
    assert "User-agent" in direct.text

    spa_route = client.get("/exams/demo/banks")
    assert spa_route.status_code == 200
    assert "spa-index" in spa_route.text


def test_head_requests_keep_no_body_semantics(client):
    assert client.head("/").status_code == 200
    assert client.head("/").content == b""
    assert client.head("/exams/demo/banks").status_code == 200
    assert client.head("/exams/demo/banks").content == b""


def test_unknown_api_route_stays_404(client):
    response = client.get("/api/definitely-not-a-route")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/secret.txt",
        "/%2e%2e/%2e%2e/secret.txt",
        "/..%2fsecret.txt",
        "/..%2F..%2Fsecret.txt",
        "/%2e%2e%2f%2e%2e%2fsecret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
    ],
)
def test_encoded_traversal_cannot_read_outside_dist(client, path):
    response = client.get(path)
    assert response.status_code == 404
    _assert_not_leaked(response)


@pytest.mark.parametrize(
    "path",
    [
        "/%2e%2e/secret.txt",
        "/..%2fsecret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
    ],
)
def test_head_traversal_is_rejected_like_get(client, path):
    response = client.head(path)
    assert response.status_code == 404
    assert response.content == b""


def test_double_encoded_traversal_is_not_a_static_file(client):
    # 双编码不会二次解码，因此只是 dist 内不存在的普通路由；关键是不能泄漏正文
    response = client.get("/%252e%252e/secret.txt")
    _assert_not_leaked(response)


def test_symlink_escaping_dist_is_rejected(client, dist_tree):
    dist, secret = dist_tree
    link = dist / "escape.txt"
    link.symlink_to(secret)

    response = client.get("/escape.txt")
    assert response.status_code == 404
    _assert_not_leaked(response)

    head_response = client.head("/escape.txt")
    assert head_response.status_code == 404
    assert head_response.content == b""


def test_absolute_path_cannot_leak_dist_outside_content(client, dist_tree):
    _, secret = dist_tree
    # 请求路径本身不含前导斜杠，因此是 dist 内不存在的普通路由；
    # 关键是不能被当成磁盘绝对路径读取到 dist 之外的正文。
    response = client.get(f"/{secret}")
    _assert_not_leaked(response)


# ─── 上传存储 ───────────────────────────────────────────────────────

PDF_BYTES = b"%PDF-1.4 fake pdf payload for path boundary tests"


def test_upload_filename_cannot_control_disk_path(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    monkeypatch.setattr(settings, "STORAGE_ROOT", str(root))

    name = "../../../../tmp/evil.pdf"
    file_path, file_hash = storage.save_upload_file(PDF_BYTES, name)

    path = Path(file_path)
    assert path.is_file()
    assert path.read_bytes() == PDF_BYTES
    assert storage._is_within(str(root), str(path))
    assert "evil" not in path.name
    assert path.name.startswith(file_hash[:16])
    assert path.suffix == ".pdf"


def test_upload_rejects_untrusted_names(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_ROOT", str(tmp_path / "storage"))

    for bad_name in ["evil.exe", "payload.pdf.exe", "no-extension", "", "a.pdf/../../b", "bad\x00.pdf"]:
        with pytest.raises(ValueError):
            storage.save_upload_file(PDF_BYTES, bad_name)


def test_upload_rejects_storage_root_inside_frontend_dist(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    monkeypatch.setattr(storage, "get_frontend_dist_dir", lambda: str(dist))
    monkeypatch.setattr(settings, "STORAGE_ROOT", str(dist / "private"))

    with pytest.raises(ValueError):
        storage.save_upload_file(PDF_BYTES, "questions.pdf")


def test_normalize_upload_ext_handles_both_separators():
    assert storage.normalize_upload_ext("dir\\file.PDF") == "pdf"
    assert storage.normalize_upload_ext("dir/file.docx") == "docx"
    assert storage.normalize_upload_ext("question.xlsx") == "xlsx"
    assert storage.normalize_upload_ext("question.txt") is None
    assert storage.normalize_upload_ext(None) is None
