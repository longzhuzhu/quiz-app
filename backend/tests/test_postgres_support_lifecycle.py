"""isolated_postgres 的真实生命周期回归测试。

这些测试只创建自己的 PostgreSQL 集群和子进程。子进程把精确的集群句柄写到
测试专用 HOME 下的报告文件，父测试在断言失败时也只清理这些句柄。
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from types import SimpleNamespace
from typing import Any, Iterator

import pytest

import postgres_support


BACKEND_DIR = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
PG_CTL = Path(os.environ.get("PG_BINDIR", "/usr/lib/postgresql/16/bin")) / "pg_ctl"


_CHILD_SOURCE = textwrap.dedent(
    r'''
    import json
    import os
    from pathlib import Path
    import signal
    import socket
    import sys
    import time

    import postgres_support


    def _start_ticks(pid):
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().split()
            return int(fields[21])
        except (FileNotFoundError, IndexError, ValueError):
            return None


    def _find_cluster(engine):
        candidates = sorted(Path.home().glob("vocab-pg-*/data"))
        if len(candidates) != 1:
            raise RuntimeError(f"expected one test cluster, found {candidates!r}")
        data = candidates[0]
        pid = int((data / "postmaster.pid").read_text().splitlines()[0])
        report = {
            "backend_pid": os.getpid(),
            "backend_start_ticks": _start_ticks(os.getpid()),
            "cluster_root": str(data.parent),
            "data_directory": str(data),
            "port": int(engine.url.port),
            "postmaster_pid": pid,
            "postmaster_start_ticks": _start_ticks(pid),
        }
        return report


    def _write_report(path, report):
        path = Path(path)
        path.write_text(json.dumps(report), encoding="utf-8")
        print(json.dumps(report), flush=True)


    async def _app(scope, receive, send):
        if scope["type"] != "http":
            return
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


    mode = sys.argv[1]
    report_path = sys.argv[2]
    server_port = int(sys.argv[3]) if len(sys.argv) > 3 else None

    with postgres_support.isolated_postgres() as engine:
        if mode == "no-report":
            while True:
                time.sleep(0.1)
        _write_report(report_path, _find_cluster(engine))
        if mode == "normal":
            pass
        elif mode == "body-exception":
            raise RuntimeError("intentional body failure")
        elif mode == "direct-sigterm":
            os.kill(os.getpid(), signal.SIGTERM)
        elif mode == "uvicorn-sigterm":
            import uvicorn

            uvicorn.run(_app, host="127.0.0.1", port=server_port, log_level="warning")
        elif mode == "hold":
            while True:
                time.sleep(0.1)
        else:
            raise RuntimeError(f"unknown mode: {mode}")
    '''
).strip()


def _test_environment(home: Path, *, parent_pid: int | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("DATABASE_URL", None)
    env.pop("PGHOST", None)
    env.pop("PGPORT", None)
    env.pop("PGSERVICE", None)
    env.pop("PGDATABASE", None)
    env["HOME"] = str(home)
    env["TMPDIR"] = os.environ.get("TMPDIR", str(home))
    env["PG_BINDIR"] = str(PG_CTL.parent)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(BACKEND_DIR / "tests"), str(BACKEND_DIR), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    if parent_pid is not None:
        env["QUIZ_TEST_PARENT_PID"] = str(parent_pid)
    else:
        env.pop("QUIZ_TEST_PARENT_PID", None)
    return env


def _short_home(tmp_path: Path, label: str) -> tuple[Path, Path]:
    """用短 symlink HOME 避免旧实现的 Unix socket 路径超过 Linux 限制。"""
    target = tmp_path / f"home-{label}"
    target.mkdir()
    alias = Path("/home/ubuntu") / f".qpg-{os.getpid()}-{time.monotonic_ns()}"
    alias.symlink_to(target, target_is_directory=True)
    return alias, target


def _remove_short_home(alias: Path, target: Path) -> bool:
    # 没有报告不是“没有数据库”。未知集群必须连同 alias 一起保留。
    if target.exists() and any(target.glob("vocab-pg-*")):
        return False
    homes = {str(alias), str(target)}
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            environment = (process / "environ").read_bytes().split(b"\0")
            if any(f"HOME={home}".encode() in environment for home in homes):
                return False
        except (OSError, ValueError):
            continue
    if alias.is_symlink():
        alias.unlink()
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    return not alias.exists() and not target.exists()


def _wait_for_report(process: subprocess.Popen[str], path: Path, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                f"child exited before report (rc={process.returncode})\n"
                f"stdout:\n{stdout}\nstderr:\n{stderr}"
            )
        time.sleep(0.05)
    # 让外层 finally 先尝试可清理的 SIGTERM；不能先 SIGKILL 再盲删 HOME。
    raise AssertionError("timed out waiting for child report; owned cleanup required")


def _pid_start_ticks(pid: int) -> int | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        fields = text[text.rfind(")") + 2:].split()
        return int(fields[19])
    except (OSError, IndexError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    if sys.platform == "linux":
        try:
            text = Path(f"/proc/{pid}/stat").read_text()
            if text[text.rfind(")") + 2:].split()[0] == "Z":
                return False
        except (OSError, IndexError, ValueError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _port_open(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _owned_pid(report: dict[str, Any], key: str, ticks_key: str) -> bool:
    pid = int(report[key])
    expected_ticks = report.get(ticks_key)
    if not _pid_alive(pid):
        return False
    if expected_ticks is not None and _pid_start_ticks(pid) != expected_ticks:
        return False
    return True


def _postmaster_owned(report: dict[str, Any]) -> bool:
    pid = int(report["postmaster_pid"])
    if not _owned_pid(report, "postmaster_pid", "postmaster_start_ticks"):
        return False
    try:
        argv = [value.decode(errors="replace") for value in Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0") if value]
        actual_data = argv[argv.index("-D") + 1]
    except (OSError, ValueError, IndexError):
        return False
    data = Path(report["data_directory"])
    return Path(argv[0]).name == "postgres" and actual_data in {str(data), str(data.resolve())}


def _backend_owned(report: dict[str, Any]) -> bool:
    pid = int(report["backend_pid"])
    if not _owned_pid(report, "backend_pid", "backend_start_ticks"):
        return False
    try:
        environ = Path(f"/proc/{pid}/environ").read_bytes()
    except FileNotFoundError:
        return False
    return f"HOME={Path(report['cluster_root']).parent}".encode() in environ.split(b"\0")


def _cluster_state(report: dict[str, Any]) -> dict[str, bool]:
    return {
        "backend_alive": _backend_owned(report),
        "postmaster_alive": _postmaster_owned(report),
        "port_open": _port_open(int(report["port"])),
        "root_exists": Path(report["cluster_root"]).exists(),
    }


def _wait_for_cluster_gone(report: dict[str, Any], timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = _cluster_state(report)
        if not any(state.values()):
            return True
        time.sleep(0.05)
    return not any(_cluster_state(report).values())


@contextmanager
def _owned_pidfd(report: dict[str, Any], *, backend: bool):
    predicate = _backend_owned if backend else _postmaster_owned
    key = "backend_pid" if backend else "postmaster_pid"
    ticks_key = "backend_start_ticks" if backend else "postmaster_start_ticks"
    if not hasattr(os, "pidfd_open") or report.get(ticks_key) is None or not predicate(report):
        yield None
        return
    try:
        descriptor = os.pidfd_open(int(report[key]))
    except ProcessLookupError:
        yield None
        return
    try:
        yield descriptor if predicate(report) else None
    finally:
        os.close(descriptor)


def _send_fd_signal(descriptor: int, signum: int) -> None:
    try:
        signal.pidfd_send_signal(descriptor, signum)
    except ProcessLookupError:
        pass


def _kill_owned_backend(report: dict[str, Any]) -> None:
    with _owned_pidfd(report, backend=True) as descriptor:
        if descriptor is None:
            return
        _send_fd_signal(descriptor, signal.SIGTERM)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _backend_owned(report):
            time.sleep(0.05)
        if _backend_owned(report):
            _send_fd_signal(descriptor, signal.SIGKILL)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and _backend_owned(report):
                time.sleep(0.05)


def _live_postmaster_references(data: Path) -> bool:
    paths = {str(data), str(data.resolve())}
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            argv = [value.decode(errors="replace") for value in (process / "cmdline").read_bytes().split(b"\0") if value]
            if argv and Path(argv[0]).name == "postgres" and "-D" in argv:
                if argv[argv.index("-D") + 1] in paths and _pid_alive(int(process.name)):
                    return True
        except (OSError, ValueError, IndexError):
            continue
    return False


def _cleanup_reported_cluster(report: dict[str, Any]) -> bool:
    """清理报告中唯一的自有集群；不按端口或全局进程名盲杀。"""
    data = Path(report["data_directory"])
    root = Path(report["cluster_root"])
    if data != root / "data" or not root.name.startswith("vocab-pg-"):
        return False
    with _owned_pidfd(report, backend=False) as descriptor:
        if descriptor is not None:
            try:
                subprocess.run(
                    [str(PG_CTL), "-D", str(data), "-m", "immediate", "-w", "stop"],
                    check=False, capture_output=True, timeout=8,
                )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline and _postmaster_owned(report):
                time.sleep(0.05)
            if _postmaster_owned(report):
                _send_fd_signal(descriptor, signal.SIGKILL)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not _postmaster_owned(report) and not _port_open(int(report["port"])) and not _live_postmaster_references(data):
            if root.exists():
                shutil.rmtree(root)
            return not root.exists()
        time.sleep(0.05)
    return False  # 无法证明进程和端口都关闭时，保留数据目录。


def _discover_unreported_clusters(
    home: Path, *, backend_pid: int | None = None, backend_ticks: int | None = None,
    parent_pid: int | None = None,
) -> list[dict[str, Any]]:
    reports = []
    for root in home.glob("vocab-pg-*"):
        try:
            owner = json.loads((root / ".quiz-test-owner.json").read_text())
            direct = backend_pid is not None and owner.get("owner_pid") == backend_pid and owner.get("owner_start_ticks") == backend_ticks
            supervised = parent_pid is not None and owner.get("parent_pid") == parent_pid
            if not (direct or supervised) or root.is_symlink():
                continue
            pidfile = (root / "data" / "postmaster.pid").read_text().splitlines()
            report = {
                "backend_pid": owner["owner_pid"], "backend_start_ticks": owner["owner_start_ticks"],
                "cluster_root": str(root), "data_directory": str(root / "data"),
                "postmaster_pid": int(pidfile[0]), "postmaster_start_ticks": _pid_start_ticks(int(pidfile[0])),
                "port": int(pidfile[3]),
            }
            if report["postmaster_start_ticks"] is not None and _postmaster_owned(report):
                reports.append(report)
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            continue
    return reports


@contextmanager
def _managed_child(
    tmp_path: Path,
    mode: str,
    *,
    server_port: int | None = None,
) -> Iterator[tuple[subprocess.Popen[str], dict[str, Any]]]:
    home, home_target = _short_home(tmp_path, mode)
    report_path = tmp_path / f"{mode}.json"
    args = [str(PYTHON), "-c", _CHILD_SOURCE, mode, str(report_path)]
    if server_port is not None:
        args.append(str(server_port))
    process = subprocess.Popen(
        args,
        cwd=BACKEND_DIR,
        env=_test_environment(home, parent_pid=os.getpid()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    report: dict[str, Any] | None = None
    backend_ticks = _pid_start_ticks(process.pid)
    try:
        report = _wait_for_report(process, report_path)
        yield process, report
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        process.communicate(timeout=5)
        if report is not None:
            _kill_owned_backend(report)
            _cleanup_reported_cluster(report)
        else:
            for discovered in _discover_unreported_clusters(home, backend_pid=process.pid, backend_ticks=backend_ticks):
                _kill_owned_backend(discovered)
                _cleanup_reported_cluster(discovered)
        _remove_short_home(home, home_target)  # 内部拒绝删除未知集群/活进程 HOME。


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, expected: bool, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(port) == expected:
            return True
        time.sleep(0.05)
    return _port_open(port) == expected


def test_normal_exit_cleans_real_postgres(tmp_path: Path) -> None:
    with _managed_child(tmp_path, "normal") as (process, report):
        assert process.wait(timeout=30) == 0
        assert _wait_for_cluster_gone(report)
        assert _cluster_state(report) == {
            "backend_alive": False,
            "postmaster_alive": False,
            "port_open": False,
            "root_exists": False,
        }


def test_body_exception_cleans_real_postgres(tmp_path: Path) -> None:
    with _managed_child(tmp_path, "body-exception") as (process, report):
        assert process.wait(timeout=30) != 0
        assert _wait_for_cluster_gone(report)
        assert _cluster_state(report) == {
            "backend_alive": False,
            "postmaster_alive": False,
            "port_open": False,
            "root_exists": False,
        }


def test_direct_sigterm_runs_database_finally(tmp_path: Path) -> None:
    with _managed_child(tmp_path, "direct-sigterm") as (process, report):
        assert process.wait(timeout=30) == 0
        assert _wait_for_cluster_gone(report)
        assert _cluster_state(report) == {
            "backend_alive": False,
            "postmaster_alive": False,
            "port_open": False,
            "root_exists": False,
        }


def test_uvicorn_sigterm_runs_database_finally(tmp_path: Path) -> None:
    server_port = _free_port()
    with _managed_child(tmp_path, "uvicorn-sigterm", server_port=server_port) as (process, report):
        assert _wait_for_port(server_port, True)
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=30) == 0
        assert _wait_for_port(server_port, False)
        assert _wait_for_cluster_gone(report)
        assert _cluster_state(report) == {
            "backend_alive": False,
            "postmaster_alive": False,
            "port_open": False,
            "root_exists": False,
        }


def test_parent_sigkill_reclaims_backend_and_postgres(tmp_path: Path) -> None:
    """监督父进程被 SIGKILL 后，子后端仍靠 PDEATHSIG 清理自己的 PG。"""
    home, home_target = _short_home(tmp_path, "parent-death")
    report_path = tmp_path / "parent-death.json"
    supervisor_source = textwrap.dedent(
        f"""
        import os
        import subprocess
        from pathlib import Path

        backend_source = { _CHILD_SOURCE!r }
        env = os.environ.copy()
        env["QUIZ_TEST_PARENT_PID"] = str(os.getpid())
        child = subprocess.Popen(
            [{str(PYTHON)!r}, "-c", backend_source, "hold", {str(report_path)!r}],
            env=env,
        )
        Path({str(tmp_path / "backend.pid")!r}).write_text(str(child.pid))
        child.wait()
        """
    ).strip()
    supervisor = subprocess.Popen(
        [str(PYTHON), "-c", supervisor_source],
        cwd=BACKEND_DIR,
        env=_test_environment(home),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    report: dict[str, Any] | None = None
    try:
        report = _wait_for_report(supervisor, report_path)
        assert _backend_owned(report)
        os.kill(supervisor.pid, signal.SIGKILL)
        assert supervisor.wait(timeout=10) == -signal.SIGKILL
        assert _wait_for_cluster_gone(report, timeout=20)
        assert _cluster_state(report) == {
            "backend_alive": False,
            "postmaster_alive": False,
            "port_open": False,
            "root_exists": False,
        }
    finally:
        if supervisor.poll() is None:
            supervisor.kill()
            supervisor.wait(timeout=10)
        supervisor.communicate(timeout=5)
        if report is not None:
            _kill_owned_backend(report)
            _cleanup_reported_cluster(report)
        if report is None:
            for discovered in _discover_unreported_clusters(home, parent_pid=supervisor.pid):
                _kill_owned_backend(discovered)
                _cleanup_reported_cluster(discovered)
        _remove_short_home(home, home_target)


@pytest.fixture
def fake_postgres(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """给启动/引擎/销毁故障注入使用的全隔离 pg_ctl 记录器。"""
    monkeypatch.setattr(
        postgres_support.Path,
        "home",
        classmethod(lambda cls: tmp_path),
    )
    calls: list[tuple[list[str], dict[str, Any]]] = []
    engine = SimpleNamespace(url=SimpleNamespace(port=54321), dispose=lambda: None)

    def fake_run(command, *args, **kwargs):
        command = [str(item) for item in command]
        calls.append((command, dict(kwargs)))
        if Path(command[0]).name == "initdb":
            data = Path(command[command.index("-D") + 1])
            data.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(postgres_support.subprocess, "run", fake_run)
    monkeypatch.setattr(postgres_support, "create_engine", lambda *args, **kwargs: engine)
    return calls, engine


def _stop_calls(calls: list[tuple[list[str], dict[str, Any]]]) -> list[tuple[list[str], dict[str, Any]]]:
    return [entry for entry in calls if "stop" in entry[0]]


def test_startup_failure_attempts_bounded_exact_stop(
    fake_postgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, _ = fake_postgres

    def fail_start(command, *args, **kwargs):
        command = [str(item) for item in command]
        calls.append((command, dict(kwargs)))
        if "start" in command:
            raise subprocess.CalledProcessError(1, command)
        if Path(command[0]).name == "initdb":
            data = Path(command[command.index("-D") + 1])
            data.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(postgres_support.subprocess, "run", fail_start)
    with pytest.raises(subprocess.CalledProcessError):
        with postgres_support.isolated_postgres():
            pytest.fail("startup should have failed")
    stops = _stop_calls(calls)
    assert stops, "startup failure must still attempt exact-cluster stop"
    assert all(entry[1].get("timeout") for entry in stops)


def test_create_engine_failure_attempts_bounded_exact_stop(
    fake_postgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, _ = fake_postgres
    monkeypatch.setattr(
        postgres_support,
        "create_engine",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("engine failed")),
    )
    with pytest.raises(RuntimeError, match="engine failed"):
        with postgres_support.isolated_postgres():
            pytest.fail("engine creation should have failed")
    stops = _stop_calls(calls)
    assert stops, "engine failure must still attempt exact-cluster stop"
    assert all(entry[1].get("timeout") for entry in stops)


def test_dispose_failure_still_attempts_bounded_exact_stop(
    fake_postgres, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls, engine = fake_postgres

    def fail_dispose():
        raise RuntimeError("dispose failed")

    engine.dispose = fail_dispose
    with pytest.raises(RuntimeError, match="dispose failed"):
        with postgres_support.isolated_postgres():
            pass
    stops = _stop_calls(calls)
    assert stops, "dispose failure must not skip exact-cluster stop"
    assert all(entry[1].get("timeout") for entry in stops)


def test_parent_death_guard_restores_linux_setting() -> None:
    guard = getattr(postgres_support, "_parent_death_guard", None)
    get_signal = getattr(postgres_support, "_get_parent_death_signal", None)
    if guard is None or get_signal is None:
        pytest.fail("parent-death guard is missing")
    if sys.platform != "linux":
        pytest.skip("PR_SET_PDEATHSIG is Linux-specific")
    before = get_signal()
    with guard(os.getppid()):
        assert get_signal() == signal.SIGTERM
    assert get_signal() == before


def test_proc_stat_handles_spaces_and_parentheses_in_process_name(monkeypatch) -> None:
    fields = ["S", "1", *(["0"] * 17), "123456789"]
    stat = "4321 (test runner ) with spaces) " + " ".join(fields)
    monkeypatch.setattr(postgres_support.Path, "read_text", lambda *args, **kwargs: stat)
    assert postgres_support._process_start_ticks(4321) == 123456789


@pytest.mark.parametrize("program, suffix, has_data_flag, expected", [
    ("postgres", "", True, True),
    ("postgres", "-neighbor", True, False),
    ("postgres-wrapper", "", True, False),
    ("postgres", "", False, False),
])
def test_postmaster_identity_requires_exact_program_and_data_argument(
    tmp_path, monkeypatch, program, suffix, has_data_flag, expected,
) -> None:
    data = tmp_path / "data"
    arguments = [f"/usr/lib/postgresql/16/bin/{program}"]
    arguments += ["-D", str(data) + suffix] if has_data_flag else ["-c", str(data)]
    command = b"\0".join(value.encode() for value in arguments) + b"\0"
    monkeypatch.setattr(postgres_support, "_postmaster_pid", lambda path: 12345)
    monkeypatch.setattr(postgres_support, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(postgres_support.Path, "read_bytes", lambda path: command)
    assert postgres_support._postmaster_is_ours(data) is expected


@pytest.mark.parametrize("identity_changes", [False, True])
def test_fallback_signal_is_bound_to_verified_pidfd(tmp_path, monkeypatch, identity_changes) -> None:
    root, data = tmp_path, tmp_path / "data"
    monkeypatch.setattr(postgres_support, "_owner_marker_matches", lambda path: True)
    monkeypatch.setattr(postgres_support, "_postmaster_is_ours", lambda path: True)
    monkeypatch.setattr(postgres_support, "_postmaster_pid", lambda path: 12345)
    ticks = iter([100, 200 if identity_changes else 100])
    monkeypatch.setattr(postgres_support, "_process_start_ticks", lambda pid: next(ticks))
    monkeypatch.setattr(postgres_support, "_cluster_stopped", lambda *args: False)
    monkeypatch.setattr(postgres_support, "_wait_for_cluster_stopped", lambda *args: True)
    monkeypatch.setattr(postgres_support.os, "pidfd_open", lambda pid: 99999)
    sent, closed = [], []
    monkeypatch.setattr(postgres_support.signal, "pidfd_send_signal", lambda fd, sig: sent.append((fd, sig)))
    original_close = postgres_support.os.close

    def close(fd):
        if fd == 99999:
            closed.append(fd)
        else:
            original_close(fd)

    monkeypatch.setattr(postgres_support.os, "close", close)
    result = postgres_support._force_stop_owned_cluster(root, data, 54321)
    assert closed == [99999]
    if identity_changes:
        assert result is False
        assert sent == [], "PID identity change must not send any fallback signal"
    else:
        assert result is True
        assert sent == [(99999, signal.SIGTERM)]


def test_unknown_cluster_prevents_home_and_alias_deletion(tmp_path) -> None:
    alias, target = _short_home(tmp_path, "unknown-cluster")
    root = target / "vocab-pg-unreported"
    (root / "data").mkdir(parents=True)
    try:
        assert _remove_short_home(alias, target) is False
        assert alias.is_symlink()
        assert root.is_dir()
    finally:
        # 这里只是本测试创建的空目录，没有启动数据库。
        shutil.rmtree(root)
        assert _remove_short_home(alias, target)


def test_reported_cleanup_preserves_directory_if_port_still_open(tmp_path, monkeypatch) -> None:
    root = tmp_path / "vocab-pg-open-port"
    (root / "data").mkdir(parents=True)
    report = {
        "cluster_root": str(root), "data_directory": str(root / "data"),
        "postmaster_pid": 12345, "postmaster_start_ticks": None, "port": 54321,
    }
    monkeypatch.setattr(sys.modules[__name__], "_postmaster_owned", lambda value: False)
    monkeypatch.setattr(sys.modules[__name__], "_port_open", lambda port: True)
    assert _cleanup_reported_cluster(report) is False
    assert (root / "data").is_dir()


def test_missing_report_after_backend_sigkill_reclaims_only_owned_cluster(tmp_path, monkeypatch) -> None:
    captured = []

    def no_report(process, path, timeout=30):
        environment = Path(f"/proc/{process.pid}/environ").read_bytes().split(b"\0")
        home = Path(next(item[5:].decode() for item in environment if item.startswith(b"HOME=")))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reports = _discover_unreported_clusters(
                home, backend_pid=process.pid, backend_ticks=_pid_start_ticks(process.pid),
            )
            if reports and _port_open(reports[0]["port"]):
                captured.extend(reports)
                # 强杀的仅是此测试新建且尚未被 wait 回收的 Popen 子进程。
                process.kill()
                process.wait(timeout=5)
                raise AssertionError("intentional missing report after own backend SIGKILL")
            time.sleep(0.05)
        raise AssertionError("test cluster did not start")

    monkeypatch.setattr(sys.modules[__name__], "_wait_for_report", no_report)
    try:
        with pytest.raises(AssertionError, match="intentional missing report"):
            with _managed_child(tmp_path, "no-report"):
                pytest.fail("no-report child must not reach the context body")
        assert len(captured) == 1
        assert _cluster_state(captured[0]) == {
            "backend_alive": False, "postmaster_alive": False,
            "port_open": False, "root_exists": False,
        }
        assert not Path(captured[0]["cluster_root"]).parent.exists()
    finally:
        for report in captured:
            _kill_owned_backend(report)
            _cleanup_reported_cluster(report)
            home = Path(report["cluster_root"]).parent
            _remove_short_home(home, home.resolve())
