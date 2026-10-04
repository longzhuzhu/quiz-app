"""AI 请求按场景设置推理强度的契约测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes import settings as settings_routes  # noqa: E402
from app.schemas.settings import AITestRequest  # noqa: E402
from app.services import ai_service  # noqa: E402


class FakeHttpxResponse:
    def __init__(self, payload: dict, status_code: int = 200, text: str = ""):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.reason_phrase = "OK" if status_code == 200 else "Error"

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self) -> dict:
        return self._payload


def _ok_payload(content: str = "ok") -> dict:
    return {"choices": [{"message": {"content": content}}]}


@pytest.fixture
def patched_settings(monkeypatch):
    def fake_get_effective_ai_settings(db, *, scene="default", **kwargs):
        return {
            "base_url": "http://fake.local/v1",
            "api_key": "sk-fake",
            "model": "fake-model",
        }

    monkeypatch.setattr(
        ai_service,
        "get_effective_ai_settings",
        fake_get_effective_ai_settings,
    )


def test_payload_defaults_to_xhigh_and_keeps_temperature():
    payload = ai_service.build_chat_completion_payload(
        "fake-model",
        [{"role": "user", "content": "hi"}],
    )

    assert payload["reasoning_effort"] == "xhigh"
    assert payload["temperature"] == 0.3


def test_payload_none_omits_reasoning_effort_and_keeps_temperature():
    payload = ai_service.build_chat_completion_payload(
        "fake-model",
        [{"role": "user", "content": "hi"}],
        None,
    )

    assert "reasoning_effort" not in payload
    assert payload["temperature"] == 0.3


def test_payload_passes_explicit_reasoning_effort_through():
    payload = ai_service.build_chat_completion_payload(
        "fake-model",
        [{"role": "user", "content": "hi"}],
        "provider-specific",
    )

    assert payload["reasoning_effort"] == "provider-specific"


def test_call_ai_api_defaults_to_xhigh(monkeypatch, patched_settings):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return FakeHttpxResponse(_ok_payload())

    monkeypatch.setattr(ai_service.httpx, "post", fake_post)

    assert ai_service.call_ai_api([], MagicMock()) == "ok"
    assert captured["json"]["reasoning_effort"] == "xhigh"
    assert captured["json"]["temperature"] == 0.3


def test_call_ai_api_translate_scene_omits_reasoning_effort(
    monkeypatch,
    patched_settings,
):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return FakeHttpxResponse(_ok_payload())

    monkeypatch.setattr(ai_service.httpx, "post", fake_post)

    assert ai_service.call_ai_api([], MagicMock(), scene="translate") == "ok"
    assert "reasoning_effort" not in captured["json"]
    assert captured["json"]["temperature"] == 0.3


def test_call_ai_api_does_not_retry_unsupported_reasoning_effort(
    monkeypatch,
    patched_settings,
):
    calls = 0

    def fake_post(url, **kwargs):
        nonlocal calls
        calls += 1
        return FakeHttpxResponse({}, status_code=400, text="unsupported reasoning_effort")

    monkeypatch.setattr(ai_service.httpx, "post", fake_post)

    with pytest.raises(ValueError, match="unsupported reasoning_effort"):
        ai_service.call_ai_api([], MagicMock())

    assert calls == 1


@pytest.mark.parametrize("reasoning_effort", [None, "low"])
def test_question_translation_controls_reasoning_effort(
    monkeypatch,
    reasoning_effort,
):
    captured = {}

    def fake_call_ai_api(
        messages,
        db,
        scene="default",
        timeout=60.0,
        reasoning_effort="xhigh",
    ):
        captured["scene"] = scene
        captured["reasoning_effort"] = reasoning_effort
        return json.dumps(
            {
                "content_zh": "中文题干",
                "options_zh": [
                    {"key": "A", "text_zh": "选项甲"},
                    {"key": "B", "text_zh": "选项乙"},
                ],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(ai_service, "call_ai_api", fake_call_ai_api)
    question = MagicMock()
    question.content = "Question"
    question.options = [
        {"key": "A", "text": "Option A"},
        {"key": "B", "text": "Option B"},
    ]
    question.bank = None

    ai_service.translate_question(
        MagicMock(),
        question,
        reasoning_effort=reasoning_effort,
    )

    assert captured == {
        "scene": "translate",
        "reasoning_effort": reasoning_effort,
    }


def test_batch_translation_omits_reasoning_effort(monkeypatch):
    captured = {}

    def fake_call_ai_api(
        messages,
        db,
        scene="default",
        timeout=60.0,
        reasoning_effort="xhigh",
    ):
        captured["scene"] = scene
        captured["reasoning_effort"] = reasoning_effort
        return "[]"

    monkeypatch.setattr(ai_service, "call_ai_api", fake_call_ai_api)

    assert ai_service.batch_translate_terms([], MagicMock()) == []
    assert captured == {"scene": "translate", "reasoning_effort": None}


def test_term_translation_omits_reasoning_effort(monkeypatch, patched_settings):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return FakeHttpxResponse(
            _ok_payload('{"term_zh": "隐私", "definition_zh": "个人信息保护"}')
        )

    monkeypatch.setattr(ai_service.httpx, "post", fake_post)

    result = ai_service.translate_term("privacy", MagicMock())

    assert result["term_zh"] == "隐私"
    assert "reasoning_effort" not in captured["json"]
    assert captured["json"]["temperature"] == 0.3


def test_connection_test_uses_default_xhigh(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        settings_routes,
        "get_effective_ai_settings",
        lambda *args, **kwargs: {
            "base_url": "http://fake.local/v1",
            "api_key": "sk-fake",
            "model": "fake-model",
        },
    )

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return FakeHttpxResponse(_ok_payload("连接正常"))

    monkeypatch.setattr(httpx, "post", fake_post)

    result = settings_routes.test_ai_connection(
        AITestRequest(),
        MagicMock(),
        MagicMock(),
    )

    assert result["success"] is True
    assert captured["json"]["reasoning_effort"] == "xhigh"
    assert captured["json"]["temperature"] == 0.3
