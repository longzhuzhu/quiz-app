"""专用临时 PostgreSQL；不连接或清理业务数据库，也不以 skip 隐藏缺失能力。"""

from contextlib import contextmanager
import ctypes
import json
from pathlib import Path
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

from sqlalchemy import create_engine


_COMMAND_TIMEOUT = 30.0
_STOP_TIMEOUT = 10.0
_WAIT_TIMEOUT = 3.0
_POLL_INTERVAL = 0.05
_PR_SET_PDEATHSIG = 1
_PR_GET_PDEATHSIG = 2


def _raise_system_exit(_signum, _frame):
    """让 Python finally 先于进程默认 SIGTERM 退出路径执行。"""
    raise SystemExit


@contextmanager
def _sigterm_cleanup():
    """在主线程临时把 SIGTERM 变成可清理的 Python 异常。

    Uvicorn 会在自己的 handler 结束后重新 raise 捕获到的 SIGTERM；它恢复
    到这里的 handler 后，SystemExit 会继续展开外层 context manager 的 finally。
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    previous = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _raise_system_exit)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def _prctl():
    if sys.platform != "linux":
        return None
    libc = ctypes.CDLL(None, use_errno=True)
    function = libc.prctl
    function.restype = ctypes.c_int
    return function


def _get_parent_death_signal() -> int:
    """返回当前 Linux PR_SET_PDEATHSIG，非 Linux 返回 0。"""
    function = _prctl()
    if function is None:
        return 0
    value = ctypes.c_int()
    if function(_PR_GET_PDEATHSIG, ctypes.byref(value), 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return int(value.value)


def _set_parent_death_signal(value: int) -> None:
    function = _prctl()
    if function is None:
        return
    if function(_PR_SET_PDEATHSIG, int(value), 0, 0, 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))


@contextmanager
def _parent_death_guard(expected_parent_pid: int | None = None):
    """让测试子进程在指定父进程死亡时走可清理的 SIGTERM 路径。

    PR_SET_PDEATHSIG 在 Linux 上是进程级的；只在主线程、Linux、且调用方
    明确提供父 PID 时启用。先安装 Python handler，再设置 pdeathsig，并立即
    验证 PPID，覆盖父进程在启动窗口内退出的竞态。离开时恢复原设置。
    """
    if (
        sys.platform != "linux"
        or expected_parent_pid is None
        or threading.current_thread() is not threading.main_thread()
    ):
        yield
        return

    previous_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _raise_system_exit)
    previous_pdeathsig: int | None = None
    try:
        previous_pdeathsig = _get_parent_death_signal()
        _set_parent_death_signal(signal.SIGTERM)
        if os.getppid() != expected_parent_pid:
            # pdeathsig 已安装；handler 让外层 finally 有机会清理。
            os.kill(os.getpid(), signal.SIGTERM)
        yield
    finally:
        try:
            if previous_pdeathsig is not None:
                _set_parent_death_signal(previous_pdeathsig)
        finally:
            signal.signal(signal.SIGTERM, previous_handler)


def _expected_parent_pid() -> int | None:
    raw = os.environ.get("QUIZ_TEST_PARENT_PID")
    if not raw:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return pid if pid > 1 else None


def _process_stat(pid: int) -> tuple[str, int] | None:
    if sys.platform != "linux":
        return None
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        # comm 位于括号中，可以含空格和右括号，不能直接对整行 split。
        fields = text[text.rfind(")") + 2:].split()
        return fields[0], int(fields[19])
    except (OSError, IndexError, ValueError):
        return None


def _process_start_ticks(pid: int) -> int | None:
    observed = _process_stat(pid)
    return observed[1] if observed is not None else None


def _pid_alive(pid: int) -> bool:
    observed = _process_stat(pid)
    if sys.platform == "linux" and (observed is None or observed[0] == "Z"):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _postmaster_pid(data: Path) -> int | None:
    try:
        return int((data / "postmaster.pid").read_text(encoding="ascii").splitlines()[0])
    except (FileNotFoundError, IndexError, ValueError):
        return None


def _postmaster_is_ours(data: Path) -> bool:
    pid = _postmaster_pid(data)
    if pid is None or not _pid_alive(pid):
        return False
    try:
        arguments = [
            value.decode(errors="replace")
            for value in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            if value
        ]
        actual_data = arguments[arguments.index("-D") + 1]
    except (OSError, ValueError, IndexError):
        return False
    data_paths = {str(data), str(data.resolve())}
    return Path(arguments[0]).name == "postgres" and actual_data in data_paths


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _cluster_stopped(data: Path, port: int) -> bool:
    return not _postmaster_is_ours(data) and not _port_open(port)


def _wait_for_cluster_stopped(data: Path, port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _cluster_stopped(data, port):
            return True
        time.sleep(_POLL_INTERVAL)
    return _cluster_stopped(data, port)


def _owner_marker_matches(root: Path) -> bool:
    """只允许当前测试进程的 marker 触发最后的精确 PID 兜底。"""
    try:
        marker = json.loads((root / ".quiz-test-owner.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return False
    if marker.get("owner_pid") != os.getpid():
        return False
    expected_ticks = marker.get("owner_start_ticks")
    return expected_ticks is None or expected_ticks == _process_start_ticks(os.getpid())


def _force_stop_owned_cluster(root: Path, data: Path, port: int) -> bool:
    if not _owner_marker_matches(root) or not _postmaster_is_ours(data):
        return _cluster_stopped(data, port)
    pid = _postmaster_pid(data)
    if pid is None:
        return _cluster_stopped(data, port)
    # Linux pidfd 固定目标进程，避免复核后 PID 复用时误伤别的进程。
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return _cluster_stopped(data, port)
    start_ticks = _process_start_ticks(pid)
    try:
        descriptor = os.pidfd_open(pid)
    except ProcessLookupError:
        return _cluster_stopped(data, port)
    try:
        if (
            start_ticks is None
            or _process_start_ticks(pid) != start_ticks
            or _postmaster_pid(data) != pid
            or not _postmaster_is_ours(data)
        ):
            return _cluster_stopped(data, port)
        try:
            signal.pidfd_send_signal(descriptor, signal.SIGTERM)
            if _wait_for_cluster_stopped(data, port, _WAIT_TIMEOUT):
                return True
            signal.pidfd_send_signal(descriptor, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return _wait_for_cluster_stopped(data, port, _WAIT_TIMEOUT)
    finally:
        os.close(descriptor)


def _run(command: list[str], *, timeout: float | None = _COMMAND_TIMEOUT):
    if timeout is None:
        return subprocess.run(command, check=True, capture_output=True)
    return subprocess.run(command, check=True, capture_output=True, timeout=timeout)


def _stop_cluster(pg_ctl: str, root: Path, data: Path, port: int) -> BaseException | None:
    stop_error: BaseException | None = None
    if data.exists():
        try:
            _run(
                [pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop"],
                timeout=_STOP_TIMEOUT,
            )
        except BaseException as error:
            stop_error = error

    stopped = _wait_for_cluster_stopped(data, port, _WAIT_TIMEOUT)
    if not stopped:
        stopped = _force_stop_owned_cluster(root, data, port)
    if not stopped:
        return stop_error or RuntimeError(
            f"temporary PostgreSQL still alive; preserving {data}"
        )
    try:
        shutil.rmtree(root)
    except FileNotFoundError:
        pass
    except BaseException as error:
        return error
    return None


def _ignore_sigterm_during_cleanup():
    if threading.current_thread() is not threading.main_thread():
        return _null_context()
    return _signal_context(signal.SIGTERM, signal.SIG_IGN)


@contextmanager
def _null_context():
    yield


@contextmanager
def _signal_context(signum, handler):
    previous = signal.getsignal(signum)
    signal.signal(signum, handler)
    try:
        yield
    finally:
        signal.signal(signum, previous)


@contextmanager
def isolated_postgres():
    bindir = Path(os.environ.get("PG_BINDIR", "/usr/lib/postgresql/16/bin"))
    initdb = shutil.which("initdb") or str(bindir / "initdb")
    pg_ctl = shutil.which("pg_ctl") or str(bindir / "pg_ctl")
    root = Path(tempfile.mkdtemp(prefix="vocab-pg-", dir=Path.home()))
    data = root / "data"
    port = 0
    engine = None
    active_exception: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    parent_pid = _expected_parent_pid()

    try:
        (root / ".quiz-test-owner.json").write_text(
            json.dumps(
                {
                    "owner_pid": os.getpid(),
                    "owner_start_ticks": _process_start_ticks(os.getpid()),
                    "parent_pid": parent_pid,
                }
            ),
            encoding="utf-8",
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        with _sigterm_cleanup():
            try:
                with _parent_death_guard(parent_pid):
                    try:
                        _run(
                            [
                                initdb,
                                "-D",
                                str(data),
                                "--auth=trust",
                                "--no-locale",
                                "--encoding=UTF8",
                            ]
                        )
                        # 所有测试客户端都走 TCP；空的 -k 必须带 shell quote，
                        # 否则长临时路径会再次触发 Unix socket 108 字节限制。
                        _run(
                            [
                                pg_ctl,
                                "-D",
                                str(data),
                                "-l",
                                str(root / "postgres.log"),
                                "-w",
                                "start",
                                "-o",
                                f"-h 127.0.0.1 -p {port} -k ''",
                            ]
                        )
                        engine = create_engine(
                            f"postgresql+psycopg://{os.environ.get('USER', 'ubuntu')}@127.0.0.1:{port}/postgres",
                            pool_size=12,
                            max_overflow=0,
                        )
                        yield engine
                    except BaseException as error:
                        active_exception = error
                        raise
            finally:
                with _ignore_sigterm_during_cleanup():
                    if engine is not None:
                        try:
                            engine.dispose()
                        except BaseException as error:
                            cleanup_errors.append(error)
                    error = _stop_cluster(pg_ctl, root, data, port)
                    if error is not None:
                        cleanup_errors.append(error)
    finally:
        # 若初始化在 signal/guard 进入前就失败，也不遗留未启动的 data 目录。
        if root.exists() and not data.exists():
            try:
                shutil.rmtree(root)
            except BaseException as error:
                cleanup_errors.append(error)

    if cleanup_errors and active_exception is None:
        raise cleanup_errors[0]
