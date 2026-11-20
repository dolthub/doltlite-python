"""Exercise the installed package through stdlib sqlite3 in fresh processes."""
from contextlib import closing
from importlib.metadata import version
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SCRIPT = Path(__file__).resolve()
ROWS = [(1, "café", b"\x00\xff", None), (2, "second", b"\x01", 2**63 - 1)]
MESSAGE = "file-backed smoke"


def child(*args, env=None, cwd=None):
    subprocess.run([sys.executable, str(SCRIPT), "--worker", *args],
                   env=env, cwd=cwd, check=True, timeout=30)


def consumer(mode, order, filename=None, commit=None):
    if order == "sqlite3-first":
        import sqlite3

    try:
        import doltlite
    except RuntimeError as error:
        if mode != "unsupported":
            raise
        assert type(error).__name__ == "DoltliteLoadError", repr(error)
        assert "dynamically links libsqlite3" in str(error), str(error)
        assert "uv venv --python" in str(error), str(error)
        return

    if mode == "unsupported":
        raise AssertionError(f"{order}: standalone Python unexpectedly accepted DoltLite")

    import sqlite3

    package_version = version("doltlite")
    expected_engine_version = "v" + package_version.split(".post", 1)[0]
    assert doltlite.__version__ == package_version
    if override := os.environ.get("DOLTLITE_LIB"):
        assert Path(doltlite.libdoltlite_path()).resolve() == Path(override).resolve()

    if mode == "reopen":
        assert Path(filename).is_file(), filename
    with closing(sqlite3.connect(filename)) as db:
        assert db.execute("SELECT doltlite_engine(), dolt_version()").fetchone() == (
            "prolly", expected_engine_version)
        if mode == "write":
            db.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, label TEXT, blob BLOB, value INTEGER)")
            db.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", ROWS)
            db.commit()
            db.execute("BEGIN")
            db.execute("UPDATE t SET label = 'rolled back'")
            db.rollback()
            (commit,) = db.execute("SELECT dolt_commit('-A', '-m', ?)", (MESSAGE,)).fetchone()
            assert isinstance(commit, str) and commit, commit

        assert db.execute("SELECT * FROM t ORDER BY id").fetchall() == ROWS
        assert db.execute("SELECT commit_hash FROM dolt_log WHERE message = ?",
                          (MESSAGE,)).fetchall() == [(commit,)]

    if mode == "write":
        child("reopen", order, filename, commit)


def main(unsupported=False):
    env = dict(os.environ)
    for name in ("_DOLTLITE_BOOTSTRAPPED", "LD_PRELOAD", "DYLD_INSERT_LIBRARIES", "PYTHONPATH"):
        env.pop(name, None)
    with tempfile.TemporaryDirectory() as directory:
        for order in ("doltlite-first", "sqlite3-first"):
            if unsupported:
                child("unsupported", order, env=env, cwd=directory)
            else:
                filename = str(Path(directory, f"{order}.db"))
                child("write", order, filename, env=env, cwd=directory)
            print(f"{order}: {'unsupported interpreter rejected' if unsupported else 'rows and history survived a child process'}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--worker"]:
        consumer(*sys.argv[2:])
    else:
        assert sys.argv[1:] in ([], ["--reject-standalone"])
        main(unsupported=bool(sys.argv[1:]))
