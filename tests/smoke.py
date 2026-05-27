"""Smoke test: after `import doltlite`, the stdlib sqlite3 module must
expose libdoltlite's SQL functions and virtual tables."""
import doltlite
import sqlite3
import sys


def main() -> int:
    conn = sqlite3.connect(":memory:")

    version = conn.execute("SELECT dolt_version()").fetchone()
    print(f"dolt_version: {version}")
    assert version and version[0].startswith("v"), f"unexpected dolt_version: {version}"

    conn.execute("CREATE TABLE t(x INT)")
    conn.execute("INSERT INTO t VALUES (1), (2), (3)")
    conn.execute("SELECT dolt_commit('-A', '-m', 'smoke')")

    log = list(conn.execute("SELECT commit_hash, message FROM dolt_log"))
    assert any(msg == "smoke" for _, msg in log), f"smoke commit missing from log: {log}"
    print(f"dolt_log entries: {len(log)}")

    print(f"libdoltlite path: {doltlite.libdoltlite_path()}")
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
