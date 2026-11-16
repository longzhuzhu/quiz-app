"""``validate_ai_base_url`` 的回环放行契约。

开关 ``AI_ALLOW_LOOPBACK_BASE_URL`` 关闭时必须与放开前逐字一致，开启时只多放行
「全部解析结果为回环地址」这一格，私网、链路本地、保留地址继续拒绝。
"""

from __future__ import annotations

import ipaddress
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services import settings_service  # noqa: E402

LOOPBACK_URLS = [
    "http://127.0.0.1:5020/v1",
    "https://127.0.0.1:5020/v1",
    "http://[::1]:5020/v1",
    "http://[::ffff:127.0.0.1]:5020/v1",
]

REJECTED_URLS = [
    ("http://192.168.1.10:5020/v1", "AI Base URL 仅允许公网 HTTPS 地址"),
    ("https://192.168.1.10:5020/v1", "AI Base URL 仅允许公网地址"),
    ("http://10.0.0.5/v1", "AI Base URL 仅允许公网 HTTPS 地址"),
    ("http://169.254.1.1/v1", "AI Base URL 仅允许公网 HTTPS 地址"),
    ("http://0.0.0.0:5020/v1", "AI Base URL 仅允许公网 HTTPS 地址"),
    ("http://8.8.8.8/v1", "AI Base URL 仅允许公网 HTTPS 地址"),
    ("ftp://127.0.0.1/v1", "AI Base URL 仅允许公网 HTTPS 地址"),
]


@pytest.fixture
def allow_loopback(monkeypatch):
    monkeypatch.setattr(settings, "AI_ALLOW_LOOPBACK_BASE_URL", True)


@pytest.fixture
def deny_loopback(monkeypatch):
    monkeypatch.setattr(settings, "AI_ALLOW_LOOPBACK_BASE_URL", False)


def _set_resolved(monkeypatch, *addresses: str) -> None:
    """固定 DNS 解析结果，避免测试依赖真实域名。"""
    monkeypatch.setattr(
        settings_service,
        "_resolve_host_addresses",
        lambda host: [ipaddress.ip_address(item) for item in addresses],
    )


class TestSwitchOff:
    """开关关闭时行为必须与放开前一致。"""

    @pytest.mark.parametrize("url", LOOPBACK_URLS)
    def test_loopback_rejected(self, deny_loopback, url):
        with pytest.raises(ValueError):
            settings_service.validate_ai_base_url(url)

    def test_http_loopback_keeps_original_message(self, deny_loopback):
        with pytest.raises(ValueError, match="仅允许公网 HTTPS 地址"):
            settings_service.validate_ai_base_url("http://127.0.0.1:5020/v1")

    def test_https_loopback_keeps_original_message(self, deny_loopback):
        with pytest.raises(ValueError, match="仅允许公网地址"):
            settings_service.validate_ai_base_url("https://127.0.0.1:5020/v1")

    def test_localhost_keeps_original_message(self, deny_loopback):
        with pytest.raises(ValueError, match="不允许使用本机地址$"):
            settings_service.validate_ai_base_url("https://localhost:5020/v1")

    def test_public_https_still_accepted(self, deny_loopback, monkeypatch):
        _set_resolved(monkeypatch, "8.8.8.8")
        assert (
            settings_service.validate_ai_base_url("https://api.example.com/v1")
            == "https://api.example.com/v1"
        )


class TestSwitchOn:
    @pytest.mark.parametrize("url", LOOPBACK_URLS)
    def test_loopback_accepted(self, allow_loopback, url):
        assert settings_service.validate_ai_base_url(url) == url

    @pytest.mark.parametrize("url,message", REJECTED_URLS)
    def test_non_loopback_still_rejected(self, allow_loopback, url, message):
        with pytest.raises(ValueError, match=message):
            settings_service.validate_ai_base_url(url)

    def test_credential_in_url_rejected(self, allow_loopback):
        with pytest.raises(ValueError, match="不允许包含认证信息"):
            settings_service.validate_ai_base_url("http://user:pass@127.0.0.1:5020/v1")

    def test_localhost_rejected_with_hint(self, allow_loopback):
        with pytest.raises(ValueError, match="127.0.0.1 或 ::1"):
            settings_service.validate_ai_base_url("http://localhost:5020/v1")

    def test_empty_rejected(self, allow_loopback):
        with pytest.raises(ValueError, match="未配置"):
            settings_service.validate_ai_base_url("")

    def test_public_https_still_accepted(self, allow_loopback, monkeypatch):
        _set_resolved(monkeypatch, "8.8.8.8")
        url = "https://api.example.com/v1"
        assert settings_service.validate_ai_base_url(url) == url


class TestMixedResolution:
    """一个主机名同时解析出回环与非回环地址时，不得因为含回环而放行。"""

    def test_mixed_addresses_rejected(self, allow_loopback, monkeypatch):
        _set_resolved(monkeypatch, "127.0.0.1", "8.8.8.8")
        with pytest.raises(ValueError, match="仅允许公网地址"):
            settings_service.validate_ai_base_url("https://dual.example.com/v1")

    def test_all_loopback_accepted(self, allow_loopback, monkeypatch):
        _set_resolved(monkeypatch, "127.0.0.1", "::1")
        url = "http://dual.example.com/v1"
        assert settings_service.validate_ai_base_url(url) == url

    def test_unresolvable_host_rejected(self, allow_loopback, monkeypatch):
        monkeypatch.setattr(settings_service, "_resolve_host_addresses", lambda host: [])
        with pytest.raises(ValueError, match="主机无法解析"):
            settings_service.validate_ai_base_url("http://127.0.0.1:5020/v1")


class TestLoopbackAddressHelper:
    @pytest.mark.parametrize("address", ["127.0.0.1", "::1", "127.1.2.3", "::ffff:127.0.0.1"])
    def test_loopback_detected(self, address):
        assert settings_service._is_loopback_ai_address(ipaddress.ip_address(address))

    @pytest.mark.parametrize("address", ["192.168.1.10", "10.0.0.5", "8.8.8.8", "0.0.0.0"])
    def test_non_loopback_detected(self, address):
        assert not settings_service._is_loopback_ai_address(ipaddress.ip_address(address))
