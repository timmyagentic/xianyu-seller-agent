import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "xianyu-service.sh"


def test_startup_script_exists_and_is_executable():
    mode = SCRIPT.stat().st_mode

    assert SCRIPT.exists()
    assert mode & stat.S_IXUSR


def test_startup_script_has_valid_bash_syntax():
    result = subprocess.run(["bash", "-n", str(SCRIPT)], cwd=ROOT, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


def test_startup_script_help_documents_service_commands():
    result = subprocess.run([str(SCRIPT), "--help"], cwd=ROOT, capture_output=True, text=True)

    assert result.returncode == 0
    assert "start" in result.stdout
    assert "stop" in result.stdout
    assert "restart" in result.stdout
    assert "status" in result.stdout
    assert "doctor" in result.stdout
    assert "qr-login" in result.stdout


def test_startup_script_is_repo_relative_not_worktree_hardcoded():
    content = SCRIPT.read_text(encoding="utf-8")

    assert "/Volumes/SamsungDisk/Code/.worktrees" not in content
    assert 'PROJECT_ROOT="${XIANYU_AGENT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd -P)}"' in content


def test_startup_script_status_is_secret_safe_with_overridden_root(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "main.py").write_text("print('placeholder')\n", encoding="utf-8")
    (root / ".env").write_text("COOKIES_STR=secret-cookie-value\n", encoding="utf-8")

    env = os.environ.copy()
    env["XIANYU_AGENT_ROOT"] = str(root)
    result = subprocess.run([str(SCRIPT), "status"], cwd=ROOT, env=env, capture_output=True, text=True)

    assert result.returncode == 0
    assert "secret-cookie-value" not in result.stdout
    assert ".env: present" in result.stdout


def test_startup_script_status_handles_screen_ls_nonzero_with_sessions(tmp_path):
    root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    root.mkdir()
    fake_bin.mkdir()
    (root / "main.py").write_text("print('placeholder')\n", encoding="utf-8")
    screen = fake_bin / "screen"
    screen.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"-ls\" ]]; then\n"
        "  printf 'There are screens on:\\n\\t123.xianyu-seller-agent-live\\t(Detached)\\n'\n"
        "  exit 1\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    screen.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["XIANYU_AGENT_ROOT"] = str(root)
    result = subprocess.run([str(SCRIPT), "status"], cwd=ROOT, env=env, capture_output=True, text=True)

    assert result.returncode == 0
    assert "live: running (xianyu-seller-agent-live)" in result.stdout


def test_startup_script_doctor_flags_processes_outside_project_root(tmp_path):
    root = tmp_path / "repo"
    stale_root = tmp_path / "deleted-worktree"
    fake_bin = tmp_path / "bin"
    root.mkdir()
    fake_bin.mkdir()
    (root / "main.py").write_text("print('placeholder')\n", encoding="utf-8")
    (fake_bin / "ps").write_text(
        "#!/usr/bin/env bash\n"
        "printf ' 123 python main.py\\n 456 python main.py web --host 127.0.0.1 --port 8765\\n'\n",
        encoding="utf-8",
    )
    (fake_bin / "lsof").write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        "  *'-p 123'*'-d cwd'*) printf 'p123\\nn%s\\n' \"$STALE_ROOT\" ;;\n"
        "  *'-p 456'*'-d cwd'*) printf 'p456\\nn%s\\n' \"$XIANYU_AGENT_ROOT\" ;;\n"
        "  *'-iTCP:8765'*) printf '456\\n' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    for fake in fake_bin.iterdir():
        fake.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["XIANYU_AGENT_ROOT"] = str(root)
    env["STALE_ROOT"] = str(stale_root)
    result = subprocess.run([str(SCRIPT), "doctor"], cwd=ROOT, env=env, capture_output=True, text=True)

    assert result.returncode == 0
    assert f"warning: pid 123 cwd is not stable PROJECT_ROOT: {stale_root}" in result.stdout
    assert f"pid 456 cwd: {root}" in result.stdout


def test_startup_script_doctor_flags_project_local_worktree_processes(tmp_path):
    root = tmp_path / "repo"
    worktree_root = root / ".worktrees" / "runtime-doctor"
    fake_bin = tmp_path / "bin"
    root.mkdir()
    fake_bin.mkdir()
    worktree_root.mkdir(parents=True)
    (root / "main.py").write_text("print('placeholder')\n", encoding="utf-8")
    (fake_bin / "ps").write_text(
        "#!/usr/bin/env bash\n"
        "printf ' 123 python main.py\\n'\n",
        encoding="utf-8",
    )
    (fake_bin / "lsof").write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        "  *'-p 123'*'-d cwd'*) printf 'p123\\nn%s\\n' \"$WORKTREE_ROOT\" ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    for fake in fake_bin.iterdir():
        fake.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["XIANYU_AGENT_ROOT"] = str(root)
    env["WORKTREE_ROOT"] = str(worktree_root)
    result = subprocess.run([str(SCRIPT), "doctor"], cwd=ROOT, env=env, capture_output=True, text=True)

    assert result.returncode == 0
    assert f"warning: pid 123 cwd is not stable PROJECT_ROOT: {worktree_root}" in result.stdout


def test_startup_script_doctor_continues_when_process_cwd_is_unavailable(tmp_path):
    root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    root.mkdir()
    fake_bin.mkdir()
    (root / "main.py").write_text("print('placeholder')\n", encoding="utf-8")
    (fake_bin / "ps").write_text(
        "#!/usr/bin/env bash\n"
        "printf ' 123 python main.py\\n'\n",
        encoding="utf-8",
    )
    (fake_bin / "lsof").write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        "  *'-d cwd'*) exit 1 ;;\n"
        "  *'-iTCP:8765'*) printf '456\\n' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    for fake in fake_bin.iterdir():
        fake.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["XIANYU_AGENT_ROOT"] = str(root)
    result = subprocess.run([str(SCRIPT), "doctor"], cwd=ROOT, env=env, capture_output=True, text=True)

    assert result.returncode == 0
    assert "pid 123 cwd: unknown" in result.stdout
    assert "web_port_8765: listening pid(s): 456" in result.stdout


def test_startup_script_doctor_uses_web_port_from_project_env_file(tmp_path):
    root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    root.mkdir()
    fake_bin.mkdir()
    (root / "main.py").write_text("print('placeholder')\n", encoding="utf-8")
    (root / ".env").write_text("WEB_PORT=9876\nCOOKIES_STR=secret-cookie-value\n", encoding="utf-8")
    (fake_bin / "ps").write_text(
        "#!/usr/bin/env bash\n",
        encoding="utf-8",
    )
    (fake_bin / "lsof").write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        "  *'-iTCP:9876'*) printf '789\\n' ;;\n"
        "  *'-iTCP:8765'*) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    for fake in fake_bin.iterdir():
        fake.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["XIANYU_AGENT_ROOT"] = str(root)
    result = subprocess.run([str(SCRIPT), "doctor"], cwd=ROOT, env=env, capture_output=True, text=True)

    assert result.returncode == 0
    assert "secret-cookie-value" not in result.stdout
    assert "web_port_9876: listening pid(s): 789" in result.stdout
    assert "web_port_8765" not in result.stdout


def test_startup_script_setup_installs_requirements_for_existing_venv(tmp_path):
    root = tmp_path / "repo"
    venv = root / ".venv"
    bin_dir = venv / "bin"
    log_path = tmp_path / "python-calls.log"
    root.mkdir()
    bin_dir.mkdir(parents=True)
    (root / "main.py").write_text("print('placeholder')\n", encoding="utf-8")
    (root / "requirements.txt").write_text("pytest>=8\n", encoding="utf-8")
    python_bin = bin_dir / "python"
    python_bin.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" >> \"$PYTHON_CALL_LOG\"\n",
        encoding="utf-8",
    )
    python_bin.chmod(0o755)

    env = os.environ.copy()
    env["PYTHON_CALL_LOG"] = str(log_path)
    env["XIANYU_AGENT_ROOT"] = str(root)
    env["XIANYU_AGENT_VENV"] = str(venv)
    result = subprocess.run([str(SCRIPT), "setup"], cwd=ROOT, env=env, capture_output=True, text=True)

    assert result.returncode == 0
    assert f"-m pip install -r {root / 'requirements.txt'}" in log_path.read_text(encoding="utf-8")


def test_stop_live_cleans_orphaned_project_live_processes(tmp_path):
    root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    root.mkdir()
    fake_bin.mkdir()
    (root / "main.py").write_text("print('placeholder')\n", encoding="utf-8")
    (fake_bin / "screen").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"-ls\" ]]; then\n"
        "  printf 'There is a screen on:\\n\\t123.xianyu-seller-agent-live\\t(Detached)\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (fake_bin / "ps").write_text(
        "#!/usr/bin/env bash\n"
        "printf ' 111 login -pflq timmy /bin/bash -lc cd %s && exec %s/.venv/bin/python main.py >> %s/logs/live.log 2>&1\\n' \"$XIANYU_AGENT_ROOT\" \"$XIANYU_AGENT_ROOT\" \"$XIANYU_AGENT_ROOT\"\n"
        "printf ' 222 /Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python main.py\\n'\n"
        "printf ' 333 /Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python main.py web\\n'\n",
        encoding="utf-8",
    )
    (fake_bin / "lsof").write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        "  *'-p 222'*'-d cwd'*) printf 'p222\\nn%s\\n' \"$XIANYU_AGENT_ROOT\" ;;\n"
        "  *'-p 333'*'-d cwd'*) printf 'p333\\nn%s\\n' \"$XIANYU_AGENT_ROOT\" ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    for fake in fake_bin.iterdir():
        fake.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["XIANYU_AGENT_ROOT"] = str(root)
    result = subprocess.run([str(SCRIPT), "stop-live"], cwd=ROOT, env=env, capture_output=True, text=True)

    assert result.returncode == 0
    assert "stopped xianyu-seller-agent-live" in result.stdout
    assert "terminated stale live process pid 111" in result.stdout
    assert "terminated stale live process pid 222" in result.stdout
    assert "pid 333" not in result.stdout


def test_stop_web_cleans_orphaned_project_web_processes(tmp_path):
    root = tmp_path / "repo"
    fake_bin = tmp_path / "bin"
    root.mkdir()
    fake_bin.mkdir()
    (root / "main.py").write_text("print('placeholder')\n", encoding="utf-8")
    (fake_bin / "screen").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"$1\" == \"-ls\" ]]; then\n"
        "  printf 'There is a screen on:\\n\\t456.xianyu-seller-agent-web\\t(Detached)\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    (fake_bin / "ps").write_text(
        "#!/usr/bin/env bash\n"
        "printf ' 111 /Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python main.py\\n'\n"
        "printf ' 222 login -pflq timmy /bin/bash -lc cd %s && LOG_LEVEL=INFO exec %s/.venv/bin/python main.py web >> %s/logs/web.log 2>&1\\n' \"$XIANYU_AGENT_ROOT\" \"$XIANYU_AGENT_ROOT\" \"$XIANYU_AGENT_ROOT\"\n"
        "printf ' 333 /Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python main.py web\\n'\n",
        encoding="utf-8",
    )
    (fake_bin / "lsof").write_text(
        "#!/usr/bin/env bash\n"
        "case \"$*\" in\n"
        "  *'-p 111'*'-d cwd'*) printf 'p111\\nn%s\\n' \"$XIANYU_AGENT_ROOT\" ;;\n"
        "  *'-p 333'*'-d cwd'*) printf 'p333\\nn%s\\n' \"$XIANYU_AGENT_ROOT\" ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    for fake in fake_bin.iterdir():
        fake.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["XIANYU_AGENT_ROOT"] = str(root)
    result = subprocess.run([str(SCRIPT), "stop-web"], cwd=ROOT, env=env, capture_output=True, text=True)

    assert result.returncode == 0
    assert "stopped xianyu-seller-agent-web" in result.stdout
    assert "terminated stale web process pid 222" in result.stdout
    assert "terminated stale web process pid 333" in result.stdout
    assert "pid 111" not in result.stdout
