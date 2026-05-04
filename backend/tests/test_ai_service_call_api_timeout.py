"""PR-1 单元测试：call_ai_api 的 timeout 参数化与异常透传契约。

覆盖路径：
    TC-1  默认 timeout = 60.0 透传给 httpx.post（向后兼容）。
    TC-2  显式 timeout=120.0 透传给 httpx.post。
    TC-3  httpx.TimeoutException 不被 wrap，直接冒泡（保护 PR-2 caller 精准捕获）。
    TC-4  smart_import_service 调用 call_ai_api 时显式带 timeout=120.0
          （静态断言源代码出现 timeout=120 至少 1 处）。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

# 把 backend/ 加入 sys.path，使 `from app.services.ai_service import ...` 可用
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services import ai_service  # noqa: E402  (sys.path 注入后才能 import)


# ─── Fixtures / 工具 ────────────────────────────────────────────────


class FakeHttpxResponse:
    """实现 httpx.Response 在 call_ai_api 中实际被读取的 4 个属性。"""

    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""
        self.reason_phrase = "OK" if status_code == 200 else "Error"

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        return self._payload


def _ok_payload() -> dict:
    return {"choices": [{"message": {"content": "ok"}}]}


@pytest.fixture
def fake_db():
    """call_ai_api 仅把 db 透传给 get_effective_ai_settings；用 MagicMock 即可。"""
    return MagicMock(name="fake_db")


@pytest.fixture
def patched_settings(monkeypatch):
    """用最小 dict 替换 get_effective_ai_settings 返回值，避开真实 DB / Fernet。"""

    def _fake_get_effective_ai_settings(db, *, scene="default", **kwargs):
        return {
            "base_url": "http://fake.local/v1",
            "api_key": "sk-fake",
            "model": "fake-model",
        }

    monkeypatch.setattr(
        ai_service,
        "get_effective_ai_settings",
        _fake_get_effective_ai_settings,
    )


# ─── TC-1 ────────────────────────────────────────────────────────────


def test_call_ai_api_default_timeout_is_60s(monkeypatch, fake_db, patched_settings):
    """不传 timeout 时，httpx.post 收到 timeout=60.0（向后兼容契约）。"""
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeHttpxResponse(_ok_payload())

    monkeypatch.setattr(ai_service.httpx, "post", fake_post)

    result = ai_service.call_ai_api([{"role": "user", "content": "hi"}], fake_db)

    assert result == "ok"
    assert captured["timeout"] == 60.0


# ─── TC-2 ────────────────────────────────────────────────────────────


def test_call_ai_api_explicit_timeout_is_passed_to_httpx(
    monkeypatch, fake_db, patched_settings
):
    """显式传 timeout=120.0 时，httpx.post 收到 timeout=120.0。"""
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return FakeHttpxResponse(_ok_payload())

    monkeypatch.setattr(ai_service.httpx, "post", fake_post)

    ai_service.call_ai_api(
        [{"role": "user", "content": "hi"}],
        fake_db,
        scene="smart_import",
        timeout=120.0,
    )

    assert captured["timeout"] == 120.0


# ─── TC-3 ────────────────────────────────────────────────────────────


def test_call_ai_api_propagates_timeout_exception(
    monkeypatch, fake_db, patched_settings
):
    """httpx.TimeoutException 不被 wrap 成 ValueError；caller 必须能精准捕获原生异常。"""

    def fake_post(url, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(ai_service.httpx, "post", fake_post)

    with pytest.raises(httpx.TimeoutException):
        ai_service.call_ai_api(
            [{"role": "user", "content": "hi"}],
            fake_db,
            scene="smart_import",
            timeout=120.0,
        )

    # 显式断言：异常**不会**被转成 ValueError（这是 ai_service 层的契约）
    def fake_post_again(url, **kwargs):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(ai_service.httpx, "post", fake_post_again)
    try:
        ai_service.call_ai_api(
            [{"role": "user", "content": "hi"}],
            fake_db,
            scene="smart_import",
            timeout=120.0,
        )
    except ValueError:  # pragma: no cover — 反向防御断言
        pytest.fail("httpx.TimeoutException 不应被 wrap 成 ValueError")
    except httpx.TimeoutException:
        pass


# ─── TC-4 ────────────────────────────────────────────────────────────


def test_smart_import_chunk_calls_ai_api_with_120s_timeout():
    """smart_import_service 在调用 LLM 时必须显式传 timeout=120.0。

    采用静态正则断言：避开真正运行 _process_chunk 的高重链路（DB / chunking /
    LLM 全栈），同时锁定 PR-1 的字面契约。命中点至少 1 处。

    PR-2 重构后，timeout=120.0 字面值同时出现在两处任一即可：
      (a) call_ai_api(..., timeout=120.0)  —— PR-1 实现
      (b) _call_llm_with_l1_retry(..., timeout=120.0)  —— PR-2 重构后入口
    两者语义等价（前者由后者透传），TC 同时接受两种形式的字面证据。
    """
    src = (
        BACKEND_ROOT / "app" / "services" / "smart_import_service.py"
    ).read_text(encoding="utf-8")

    matches = re.findall(
        r"(?:call_ai_api|_call_llm_with_l1_retry)\([^)]*timeout=120(?:\.0)?[^)]*\)",
        src,
    )
    assert len(matches) >= 1, (
        "smart_import_service.py 中未找到 call_ai_api(..., timeout=120[.0]) "
        "或 _call_llm_with_l1_retry(..., timeout=120[.0]) 的调用；"
        "smart_import 路径必须显式将 LLM 调用 timeout 设为 120.0"
    )
