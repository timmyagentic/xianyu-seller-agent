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
