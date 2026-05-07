"""兼容旧 Flask 应用入口。"""

from importlib import util
from pathlib import Path

_LEGACY_APP_PATH = Path(__file__).resolve().parent.parent / 'app.py'
_LEGACY_MODULE_NAME = '_legacy_flask_app'

_spec = util.spec_from_file_location(_LEGACY_MODULE_NAME, _LEGACY_APP_PATH)
if _spec is None or _spec.loader is None:
    raise ImportError(f'无法加载旧 Flask 应用入口: {_LEGACY_APP_PATH}')

_legacy_app = util.module_from_spec(_spec)
_spec.loader.exec_module(_legacy_app)

create_app = _legacy_app.create_app

__all__ = ['create_app']
