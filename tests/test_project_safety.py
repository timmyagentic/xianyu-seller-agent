from pathlib import Path
import os
import subprocess
import sys


def test_gitignore_protects_runtime_and_secret_files():
    text = Path(".gitignore").read_text(encoding="utf-8")
    for pattern in [".env", "data/", "relist/*.json", "docs/listings/", ".worktrees/", "*.db", "*.sqlite", "__pycache__/"]:
        assert pattern in text


def test_expected_project_files_are_declared():
    assert Path("requirements.txt").exists()
    assert Path(".env.example").exists()
    assert Path("pytest.ini").exists()


def test_top_level_cli_help_does_not_prompt_for_credentials():
    env = os.environ.copy()
    env.pop("COOKIES_STR", None)

    result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )

    assert result.returncode == 0
    assert "usage: python main.py" in result.stdout
    assert "COOKIES_STR" not in result.stdout
