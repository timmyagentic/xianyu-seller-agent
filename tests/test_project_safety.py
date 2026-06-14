from pathlib import Path


def test_gitignore_protects_runtime_and_secret_files():
    text = Path(".gitignore").read_text(encoding="utf-8")
    for pattern in [".env", "data/", "relist/*.json", "*.db", "*.sqlite", "__pycache__/"]:
        assert pattern in text


def test_expected_project_files_are_declared():
    assert Path("requirements.txt").exists()
    assert Path(".env.example").exists()
    assert Path("pytest.ini").exists()
