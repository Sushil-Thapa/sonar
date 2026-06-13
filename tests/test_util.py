import os

from sonar.util import human_bytes, project_from_cwd


def test_human_bytes():
    assert human_bytes(None) == "-"
    assert human_bytes(512) == "512B"
    assert human_bytes(1536).endswith("K")
    assert human_bytes(2 * 1024**3).endswith("G")


def test_project_from_cwd_under_code(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path) if p == "~" else p)
    cwd = os.path.join(str(tmp_path), "code", "monorepo", "alpha")
    assert project_from_cwd(cwd) == "monorepo/alpha"


def test_project_from_cwd_git_monorepo_keeps_subproject(tmp_path):
    repo = tmp_path / "monorepo"
    (repo / ".git").mkdir(parents=True)
    sub = repo / "alpha" / "src"
    sub.mkdir(parents=True)
    assert project_from_cwd(str(sub)) == "monorepo/alpha"


def test_project_from_cwd_git_root_itself(tmp_path):
    repo = tmp_path / "myrepo"
    (repo / ".git").mkdir(parents=True)
    assert project_from_cwd(str(repo)) == "myrepo"


def test_project_from_cwd_none():
    assert project_from_cwd(None) is None
