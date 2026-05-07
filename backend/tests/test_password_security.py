from pathlib import Path
import sys

import bcrypt
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from services.password_security import get_password_hash, verify_password


def test_passlib_hash_verifies_correct_password_only():
    hashed = get_password_hash("secret-password")

    assert verify_password("secret-password", hashed) is True
    assert verify_password("wrong-password", hashed) is False


@pytest.mark.parametrize(
    "plain_password,hashed_password",
    [
        (
            "werkzeug-password",
            "pbkdf2:sha256:1000$testsalt$eb234a32a38e7b76a2b0a1ed2401ec490628af22d6ebbdb5e11df987f6fc7064",
        ),
        (
            "bcrypt-password",
            bcrypt.hashpw("bcrypt-password".encode(), bcrypt.gensalt()).decode(),
        ),
    ],
)
def test_legacy_hash_formats_verify_correct_password_only(plain_password, hashed_password):
    assert verify_password(plain_password, hashed_password) is True
    assert verify_password("wrong-password", hashed_password) is False


@pytest.mark.parametrize(
    "plain_password,hashed_password",
    [
        ("password", ""),
        ("password", "not-a-supported-hash"),
        ("password", "$pbkdf2-sha256$malformed"),
        ("", get_password_hash("password")),
        (None, get_password_hash("password")),
        ("password", None),
    ],
)
def test_invalid_inputs_return_false_without_exception(plain_password, hashed_password):
    assert verify_password(plain_password, hashed_password) is False


def test_fastapi_security_reexports_shared_password_helpers():
    from app.core.security import get_password_hash as fastapi_hash
    from app.core.security import verify_password as fastapi_verify

    hashed = fastapi_hash("shared-password")

    assert fastapi_verify("shared-password", hashed) is True
    assert fastapi_verify("wrong-password", hashed) is False
