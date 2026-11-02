import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


PROGRAM = """
import doltlite
import json
import os
import sqlite3

conn = sqlite3.connect(':memory:')
conn.execute('SELECT count(*) FROM dolt_branches').fetchone()
print(json.dumps(os.environ['DYLD_INSERT_LIBRARIES']))
"""


def main():
    if sys.platform != "darwin":
        raise RuntimeError("this smoke test requires macOS")
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        script = root / "query.py"
        script.write_text(PROGRAM)

        def run(seed, cache):
            env = dict(os.environ, PYTHONHASHSEED=str(seed), TMPDIR=str(cache))
            env.pop("_DOLTLITE_BOOTSTRAPPED", None)
            env.pop("DYLD_INSERT_LIBRARIES", None)
            env.pop("DOLTLITE_LIB", None)
            result = subprocess.run([sys.executable, str(script)], env=env,
                                    check=True, capture_output=True, text=True,
                                    timeout=30)
            return Path(json.loads(result.stdout))

        sequential = root / "sequential"
        sequential.mkdir()
        first = run(1, sequential)
        stat = first.stat()
        second = run(2, sequential)
        assert first == second, (first, second)
        assert (stat.st_ino, stat.st_mtime_ns) == (second.stat().st_ino, second.stat().st_mtime_ns)
        assert len(list(sequential.glob("doltlite-shim-*"))) == 1

        concurrent_cache = root / "concurrent"
        concurrent_cache.mkdir()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            paths = list(pool.map(lambda seed: run(seed, concurrent_cache), range(4)))
        assert len(set(paths)) == 1, paths
        assert len(list(concurrent_cache.glob("doltlite-shim-*"))) == 1
        assert len(list(concurrent_cache.rglob("libsqlite3.dylib"))) == 1
    print("macOS shim reuse and concurrent imports: OK")


if __name__ == "__main__":
    main()
