import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


LOADER_PATH = Path(__file__).resolve().parents[1] / "src/doltlite/_loader.py"
SPEC = importlib.util.spec_from_file_location("doltlite_loader_test", LOADER_PATH)
loader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(loader)
INSTALL_NAME = "/test/libsqlite3.dylib"
WORKER = """
import importlib.util
import json
from pathlib import Path
import sys
import time

spec = importlib.util.spec_from_file_location('loader', sys.argv[1])
loader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(loader)
loader._detect_sqlite3_install_name = lambda: sys.argv[4]
loader.tempfile.gettempdir = lambda: sys.argv[3]
def install(command, **kwargs):
    if len(sys.argv) > 5:
        Path(sys.argv[5]).write_text('ready')
        deadline = time.monotonic() + 15
        while not Path(sys.argv[6]).exists():
            if time.monotonic() > deadline:
                raise RuntimeError('installer was not released')
            time.sleep(0.01)
    path = Path(command[-1])
    path.write_bytes(path.read_bytes() + b':patched')
    with (Path(sys.argv[3]) / 'installs').open('a') as log:
        log.write('installed\\n')
loader.subprocess.run = install
shim = loader._build_macos_shim(sys.argv[2])
print(json.dumps([shim, Path(shim).read_text()]))
"""


class MacosShimTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.lib = self.root / "libdoltlite.dylib"
        self.lib.write_bytes(b"library")
        self.cache = self.root / "cache"
        self.cache.mkdir()

    def command(self, lib=None, install_name=INSTALL_NAME):
        return [sys.executable, "-c", WORKER, str(LOADER_PATH),
                str(lib or self.lib), str(self.cache), install_name]

    def worker(self, seed="1", lib=None, install_name=INSTALL_NAME, cwd=None):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        result = subprocess.run(self.command(lib, install_name), env=env,
                                cwd=cwd, check=True, capture_output=True,
                                text=True, timeout=20)
        return json.loads(result.stdout)

    def test_reuses_shim_across_hash_seeds(self):
        results = [self.worker(seed) for seed in ("1", "2", "random")]
        self.assertEqual(results, [results[0]] * 3)
        self.assertEqual(results[0][1], "library:patched")
        self.assertEqual((self.cache / "installs").read_text(), "installed\n")

    def test_source_mtime_invalidates_shim(self):
        first = self.worker()
        stat = self.lib.stat()
        os.utime(self.lib, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        self.assertNotEqual(first[0], self.worker()[0])

    def test_install_name_invalidates_shim(self):
        first = self.worker()
        self.assertNotEqual(first[0], self.worker(install_name="/other/libsqlite3.dylib")[0])

    def test_relative_source_uses_same_cache(self):
        first = self.worker()
        self.assertEqual(first, self.worker(lib=self.lib.name, cwd=self.lib.parent))

    def test_different_sources_do_not_share_cache(self):
        other = self.root / "other" / self.lib.name
        other.parent.mkdir()
        other.write_bytes(b"other library")
        stat = self.lib.stat()
        os.utime(other, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        first = self.worker(lib=self.lib.name, cwd=self.lib.parent)
        second = self.worker(lib=other.name, cwd=other.parent)
        self.assertNotEqual(first[0], second[0])
        self.assertEqual(second[1], "other library:patched")

    def test_failure_does_not_publish_shim(self):
        for error in (FileNotFoundError("missing tool"),
                      subprocess.CalledProcessError(1, "install_name_tool", stderr="bad library")):
            with self.subTest(error=error), \
                    mock.patch.object(loader, "_detect_sqlite3_install_name", return_value=INSTALL_NAME), \
                    mock.patch.object(loader.tempfile, "gettempdir", return_value=str(self.cache)), \
                    mock.patch.object(loader.subprocess, "run", side_effect=error):
                with self.assertRaisesRegex(loader.DoltliteLoadError, "install_name_tool"):
                    loader._build_macos_shim(str(self.lib))
            self.assertEqual(list(self.cache.rglob("libsqlite3.dylib")), [])
        self.assertEqual(self.worker()[1], "library:patched")

    def test_failed_copy_does_not_publish_shim(self):
        def fail_copy(source, destination):
            Path(destination).write_bytes(b"partial")
            raise OSError("copy failed")

        with mock.patch.object(loader, "_detect_sqlite3_install_name", return_value=INSTALL_NAME), \
                mock.patch.object(loader.tempfile, "gettempdir", return_value=str(self.cache)), \
                mock.patch.object(loader.shutil, "copyfile", side_effect=fail_copy):
            with self.assertRaisesRegex(OSError, "copy failed"):
                loader._build_macos_shim(str(self.lib))
        self.assertEqual(list(self.cache.rglob("libsqlite3.dylib")), [])
        self.assertEqual(self.worker()[1], "library:patched")

    def test_concurrent_start_cannot_reuse_unfinished_shim(self):
        ready = self.root / "ready"
        release = self.root / "release"
        command = self.command() + [str(ready), str(release)]
        first = subprocess.Popen(command, env=dict(os.environ, PYTHONHASHSEED="1"),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists():
                if first.poll() is not None or time.monotonic() > deadline:
                    self.fail("first installer did not start")
                time.sleep(0.01)
            second = self.worker()
            self.assertEqual(second[1], "library:patched")
        finally:
            release.write_text("release")
            stdout, stderr = first.communicate(timeout=20)
        self.assertEqual(first.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout), second)
        self.assertEqual(len(list(self.cache.glob("doltlite-shim-*"))), 1)
        self.assertEqual(len(list(self.cache.rglob("libsqlite3.dylib"))), 1)


if __name__ == "__main__":
    unittest.main()
