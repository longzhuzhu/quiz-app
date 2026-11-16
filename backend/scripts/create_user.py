"""账号运维脚本：创建用户、重置密码、启停用、升降级。

账号由管理员创建，系统不再提供自助注册；全新部署的第一个管理员也由本脚本创建。

用法：
    python3 backend/scripts/create_user.py create --username admin --email a@example.com --admin
    python3 backend/scripts/create_user.py reset-password --username alice
    python3 backend/scripts/create_user.py disable --username alice
    python3 backend/scripts/create_user.py enable --username alice
    python3 backend/scripts/create_user.py promote --username alice
    python3 backend/scripts/create_user.py demote --username alice

除 create 外，密码均可用 --password 传入；省略时交互式输入，避免密码留在 shell 历史里。
"""

import argparse
import getpass
import os
import sys

# 将 backend 目录加入 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models.user import User

MIN_PASSWORD_LENGTH = 6


def _read_password(args) -> str:
    password = args.password
    if password is None:
        password = getpass.getpass("密码：")
        if getpass.getpass("再次输入密码：") != password:
            raise SystemExit("两次输入的密码不一致")
    if not password or not password.strip():
        raise SystemExit("密码不能为空")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise SystemExit(f"密码至少 {MIN_PASSWORD_LENGTH} 位")
    return password


def _get_user_or_exit(db, username: str) -> User:
    user = db.query(User).filter_by(username=username).first()
    if user is None:
        raise SystemExit(f"用户 {username} 不存在")
    return user


def _usable_admin_count(db) -> int:
    return db.query(User).filter(User.is_admin.is_(True), User.is_active.is_(True)).count()


def _ensure_another_usable_admin(db, user: User) -> None:
    """降级或停用后必须仍有可用管理员能登录，否则系统只能再靠本脚本救回。"""
    if not (user.is_admin and user.is_active):
        return
    if _usable_admin_count(db) <= 1:
        raise SystemExit("系统必须保留至少一个可用管理员，已取消操作")


def cmd_create(db, args) -> None:
    username = args.username.strip()
    email = args.email.strip()
    if not username:
        raise SystemExit("用户名不能为空")
    if not email:
        raise SystemExit("邮箱不能为空")
    if db.query(User).filter_by(username=username).first():
        raise SystemExit(f"用户名 {username} 已存在")
    if db.query(User).filter_by(email=email).first():
        raise SystemExit(f"邮箱 {email} 已存在")

    password = _read_password(args)
    user = User(
        username=username,
        email=email,
        password_hash=get_password_hash(password),
        is_admin=args.admin,
        is_active=True,
    )
    db.add(user)
    db.commit()
    role = "管理员" if user.is_admin else "普通用户"
    print(f"已创建{role} {username}（id={user.id}）")


def cmd_reset_password(db, args) -> None:
    user = _get_user_or_exit(db, args.username)
    user.password_hash = get_password_hash(_read_password(args))
    db.commit()
    print(f"已重置 {user.username} 的密码。已签发的登录状态不会立即失效。")


def cmd_disable(db, args) -> None:
    user = _get_user_or_exit(db, args.username)
    _ensure_another_usable_admin(db, user)
    user.is_active = False
    db.commit()
    print(f"已停用 {user.username}。已签发的登录状态不会立即失效。")


def cmd_enable(db, args) -> None:
    user = _get_user_or_exit(db, args.username)
    user.is_active = True
    db.commit()
    print(f"已启用 {user.username}")


def cmd_promote(db, args) -> None:
    user = _get_user_or_exit(db, args.username)
    user.is_admin = True
    db.commit()
    print(f"已把 {user.username} 设为管理员")


def cmd_demote(db, args) -> None:
    user = _get_user_or_exit(db, args.username)
    _ensure_another_usable_admin(db, user)
    user.is_admin = False
    db.commit()
    print(f"已取消 {user.username} 的管理员权限")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="账号运维：创建用户、重置密码、启停用、升降级")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create", help="创建用户")
    create.add_argument("--username", required=True)
    create.add_argument("--email", required=True)
    create.add_argument("--password", help="省略时交互式输入")
    create.add_argument("--admin", action="store_true", help="创建为管理员")
    create.set_defaults(func=cmd_create)

    reset = sub.add_parser("reset-password", help="重置密码")
    reset.add_argument("--username", required=True)
    reset.add_argument("--password", help="省略时交互式输入")
    reset.set_defaults(func=cmd_reset_password)

    disable = sub.add_parser("disable", help="停用账号（阻止新登录）")
    disable.add_argument("--username", required=True)
    disable.set_defaults(func=cmd_disable)

    enable = sub.add_parser("enable", help="启用账号")
    enable.add_argument("--username", required=True)
    enable.set_defaults(func=cmd_enable)

    promote = sub.add_parser("promote", help="设为管理员")
    promote.add_argument("--username", required=True)
    promote.set_defaults(func=cmd_promote)

    demote = sub.add_parser("demote", help="取消管理员权限")
    demote.add_argument("--username", required=True)
    demote.set_defaults(func=cmd_demote)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    db = SessionLocal()
    try:
        args.func(db, args)
    except SystemExit:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise SystemExit(f"操作失败：{exc}") from exc
    finally:
        db.close()


if __name__ == "__main__":
    main()
