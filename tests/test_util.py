import os

from sonar.util import exe_basename, human_bytes, project_from_cwd, short_command


def test_exe_basename():
    assert exe_basename("/Users/x/.venv/bin/python3 train.py --c a") == "python3"
    assert exe_basename("node server.js") == "node"
    assert exe_basename("") == ""


def test_short_command_strips_interpreter_path():
    s = short_command("/Users/x/code/monorepo/.venv/bin/python3 train.py --config c.yaml")
    assert s == "python3 train.py --config c.yaml"


def test_short_command_caps_length():
    s = short_command("python3 " + "x" * 500, cap=40)
    assert len(s) == 40 and s.endswith("…")


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
