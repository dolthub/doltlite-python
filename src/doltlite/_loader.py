"""Cross-platform loader for libdoltlite.

The goal: make `import doltlite` enough for any subsequent `sqlite3` /
SQLAlchemy code to talk to doltlite. The challenge is that Python's
`sqlite3` module is a thin wrapper over libsqlite3; we have to make
libdoltlite's `sqlite3_*` symbols win over the system libsqlite3's.

Strategy by platform:

- **Linux** uses flat-namespace symbol resolution. If we `dlopen(lib,
  RTLD_GLOBAL)` *before* `_sqlite3` is loaded, libdoltlite's symbols
  end up in the global namespace and the later dynamic resolution from
  libsqlite3 picks them up. If `sqlite3` was already imported, we have
  to re-exec the interpreter with `LD_PRELOAD` set.

- **macOS** uses a two-level namespace: `_sqlite3.so` is linked with an
  absolute `LC_LOAD_DYLIB` reference to a specific `libsqlite3.dylib`
  (e.g. `/opt/homebrew/opt/sqlite/lib/libsqlite3.dylib`). Plain
  `ctypes.CDLL` does not redirect that lookup. The only mechanism that
  does is a `DYLD_INSERT_LIBRARIES` library whose own `install_name`
  (`LC_ID_DYLIB`) matches the path `_sqlite3.so` was linked against.
  We build that shim from libdoltlite via `install_name_tool -id`,
  then re-exec with `DYLD_INSERT_LIBRARIES` pointing at the shim.
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional


_BOOTSTRAP_MARKER = "_DOLTLITE_BOOTSTRAPPED"
_PKG_LIB_DIR = Path(__file__).resolve().parent / "_lib"


class DoltliteLoadError(RuntimeError):
    """Raised when libdoltlite cannot be located or loaded."""


def libdoltlite_path() -> str:
    """Return the absolute path of the libdoltlite that will be loaded.

    Resolution order:
    1. `DOLTLITE_LIB` environment variable (absolute path)
    2. Library bundled inside the installed `doltlite` package
       (`<pkg>/_lib/libdoltlite.{dylib,so}`)

    Raises `DoltliteLoadError` if neither is available.
    """
    env = os.environ.get("DOLTLITE_LIB")
    if env:
        if not os.path.exists(env):
            raise DoltliteLoadError(
                f"DOLTLITE_LIB points to a missing file: {env}"
            )
        return env

    name = "libdoltlite.dylib" if sys.platform == "darwin" else "libdoltlite.so"
    bundled = _PKG_LIB_DIR / name
    if bundled.is_file():
        return str(bundled)

    raise DoltliteLoadError(
        f"libdoltlite not found.\n"
        f"  Looked for bundled: {bundled}\n"
        f"  DOLTLITE_LIB env var: <unset>\n"
        f"Either install a wheel that bundles libdoltlite, or set "
        f"DOLTLITE_LIB to the absolute path of {name}."
    )


def _is_bootstrapped() -> bool:
    return os.environ.get(_BOOTSTRAP_MARKER) == "1"


def _sqlite3_already_imported() -> bool:
    return "sqlite3" in sys.modules or "_sqlite3" in sys.modules


def bootstrap() -> None:
    """Make libdoltlite the active SQLite engine for this interpreter.

    Idempotent: subsequent calls (and re-entrant calls after a re-exec)
    are no-ops. Raises `DoltliteLoadError` if the library can't be found
    or if a re-exec is needed but `sys.argv` does not name a script we
    can replay (interactive shell, `python -c …`, REPL, notebook).
    """
    if _is_bootstrapped():
        return

    lib = libdoltlite_path()

    if sys.platform != "darwin" and not _sqlite3_already_imported():
        ctypes.CDLL(lib, mode=ctypes.RTLD_GLOBAL)
        os.environ[_BOOTSTRAP_MARKER] = "1"
        return

    _require_replayable_argv()

    env = dict(os.environ)
    env[_BOOTSTRAP_MARKER] = "1"

    if sys.platform == "darwin":
        env["DYLD_INSERT_LIBRARIES"] = _build_macos_shim(lib)
    else:
        existing = env.get("LD_PRELOAD", "").strip()
        env["LD_PRELOAD"] = f"{lib} {existing}".strip()

    os.execvpe(sys.executable, [sys.executable, *sys.argv], env)


def _require_replayable_argv() -> None:
    """Bail out clearly if we can't safely re-exec the current process.

    `python -c "..."` and an interactive REPL have no script path in
    `sys.argv` that we can re-exec — the user's code is consumed before
    `sys.argv` is built. Jupyter / IPython kernels are similar.
    """
    arg0 = sys.argv[0] if sys.argv else ""
    if arg0 and arg0 != "-c" and os.path.exists(arg0):
        return

    if sys.platform == "darwin":
        envvar, name = "DYLD_INSERT_LIBRARIES", "libdoltlite.dylib"
        shim_hint = (
            "  (On macOS the inserted library must be named libsqlite3.dylib "
            "with its install_name set to the path your Python's _sqlite3 "
            "was linked against. See doltlite._loader for the recipe.)"
        )
    else:
        envvar, name = "LD_PRELOAD", "libdoltlite.so"
        shim_hint = ""

    raise DoltliteLoadError(
        "doltlite bootstrap requires re-execing the interpreter, but the "
        f"current invocation (sys.argv[0]={arg0!r}) does not name a "
        "script that can be replayed (interactive shell, `python -c …`, "
        "Jupyter, etc.).\n"
        f"Workaround: set {envvar} yourself before starting Python so "
        f"{name} is loaded at process start.\n"
        + shim_hint
    )


def _detect_sqlite3_install_name() -> str:
    """On macOS, return the libsqlite3 path that the active interpreter's
    `_sqlite3` extension was linked against."""
    import _sqlite3

    try:
        out = subprocess.run(
            ["otool", "-L", _sqlite3.__file__],
            check=True, capture_output=True, text=True,
        ).stdout
    except FileNotFoundError as e:
        raise DoltliteLoadError(
            "otool is required on macOS to detect the active "
            "libsqlite3 path. Install Xcode Command Line Tools."
        ) from e

    for line in out.splitlines():
        token = line.strip().split(" ", 1)[0]
        if "/libsqlite3" in token and token.endswith(".dylib"):
            return token

    raise DoltliteLoadError(
        "Could not find a libsqlite3 dependency in "
        f"{_sqlite3.__file__}. Output of otool -L:\n{out}"
    )


def _build_macos_shim(lib: str) -> str:
    """Produce a libsqlite3.dylib shim whose install_name matches the path
    `_sqlite3.so` was linked against. The shim is cached under $TMPDIR
    keyed by (lib path, mtime, target install_name)."""
    install_name = _detect_sqlite3_install_name()
    src_stat = os.stat(lib)
    key = f"{abs(hash((lib, src_stat.st_mtime_ns, install_name))):016x}"
    cache_dir = Path(tempfile.gettempdir()) / f"doltlite-shim-{key}"
    shim = cache_dir / "libsqlite3.dylib"

    if shim.exists():
        return str(shim)

    cache_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(lib, shim)
    try:
        subprocess.run(
            ["install_name_tool", "-id", install_name, str(shim)],
            check=True, capture_output=True, text=True,
        )
    except FileNotFoundError as e:
        raise DoltliteLoadError(
            "install_name_tool is required on macOS. Install Xcode "
            "Command Line Tools (`xcode-select --install`)."
        ) from e
    except subprocess.CalledProcessError as e:
        raise DoltliteLoadError(
            f"install_name_tool failed for {shim}: {e.stderr}"
        ) from e

    return str(shim)
