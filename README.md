# doltlite (Python)

A Python loader for [doltlite](https://github.com/dolthub/doltlite) —
Dolt's version control through SQLite's drop-in API.

```python
import doltlite          # one-time bootstrap
import sqlite3

conn = sqlite3.connect("repo.db")
conn.execute("CREATE TABLE t(x INT)")
conn.execute("INSERT INTO t VALUES (1)")
conn.execute("SELECT dolt_commit('-A', '-m', 'init')")
```

`import doltlite` makes libdoltlite the active SQLite engine for the
current interpreter, so anything that uses the standard `sqlite3` module
— **including SQLAlchemy with `sqlite:///...` URLs** — transparently
gains `dolt_commit`, `dolt_branch`, `dolt_merge`, `dolt_log`,
`dolt_diff_<table>`, and the other Dolt SQL functions and virtual tables.

## Install

```bash
pip install doltlite
```

Wheels bundle a precompiled `libdoltlite` for macOS (arm64) and Linux
(x86_64, aarch64). No system-level setup required.

Intel Mac wheels aren't shipped in v0.11.x — GitHub's free-tier
macos-13 runners queue for hours and block releases. Intel Mac users
should build libdoltlite locally and use the `DOLTLITE_LIB` path below.

For development against a local checkout of doltlite, point
`DOLTLITE_LIB` at your built library instead:

```bash
DOLTLITE_LIB=/path/to/libdoltlite.dylib python3 your_script.py
```

## Requirements

The package piggybacks on Python's stdlib `sqlite3`, which must load
SQLite as a shared extension at runtime. The following Pythons work:

- Distro / system Python (Linux)
- Homebrew Python (macOS, Linux)
- pyenv-built Python
- Conda Python

These do **not** work because their `_sqlite3` is statically linked into
the interpreter:

- **python-build-standalone** interpreters — the default for `uv python
  install`, `mise`, and Rye

If you use `uv`, target one of the supported Pythons explicitly:

```bash
uv venv --python /opt/homebrew/bin/python3   # or /usr/bin/python3
```

## How the bootstrap works

Doltlite is a SQLite drop-in: it implements the same `sqlite3_*` C API
and adds Dolt-specific functions and virtual tables on top. To use it
from Python, libdoltlite has to be loaded ahead of the system libsqlite3
so its symbols win during the dynamic-link symbol-resolution pass that
Python's `_sqlite3` module triggers when it's first imported.

The mechanics differ by platform:

### Linux

ELF flat-namespace symbol resolution: if libdoltlite is loaded into the
process with `RTLD_GLOBAL` **before** `_sqlite3` is loaded, its
`sqlite3_*` symbols enter the global namespace and the later
`libsqlite3.so` lookup finds them first.

`import doltlite` does `ctypes.CDLL(libdoltlite_path,
mode=ctypes.RTLD_GLOBAL)` in this case — no re-exec required.

If `sqlite3` was already imported before `doltlite`, that boat has
sailed: we fall back to re-execing the interpreter with `LD_PRELOAD`
set, so libdoltlite is loaded at process start.

### macOS

macOS uses a two-level namespace: `_sqlite3.so` has an `LC_LOAD_DYLIB`
command bound to a specific `libsqlite3.dylib` path (e.g.
`/opt/homebrew/opt/sqlite/lib/libsqlite3.dylib`). Plain `dlopen` /
`ctypes.CDLL` does **not** redirect that resolution, and
`DYLD_INSERT_LIBRARIES` alone doesn't either — the inserted library has
to have an `install_name` (`LC_ID_DYLIB`) that matches the path
`_sqlite3.so` was linked against.

`import doltlite` does:

1. Detect that path via `otool -L $(python3 -c 'import _sqlite3;
   print(_sqlite3.__file__)')`.
2. Copy libdoltlite to `$TMPDIR/.../libsqlite3.dylib` (cached per
   (lib, mtime, install_name)).
3. Rewrite the shim's install_name with `install_name_tool -id <path>`.
4. Re-exec the interpreter with `DYLD_INSERT_LIBRARIES=<shim>`.

The two-level lookup then accepts the shim because the install_name
matches.

This requires `otool` and `install_name_tool` — install Xcode Command
Line Tools (`xcode-select --install`) if missing.

## Re-exec caveats

When a re-exec is required (macOS, or Linux-after-sqlite3-loaded), the
bootstrap calls `os.execvpe` with `sys.argv`. That means the
invocation must name a script file we can replay:

- ✅ `python3 my_script.py`
- ✅ `python3 -m my_package`
- ❌ `python3 -c "import doltlite; ..."` — code string isn't in argv
- ❌ Interactive REPL / Jupyter — there's no script to re-exec

In the unsupported cases the bootstrap raises `DoltliteLoadError` with
a clear workaround: set `DYLD_INSERT_LIBRARIES` (macOS) or `LD_PRELOAD`
(Linux) yourself before starting Python.

## API

```python
import doltlite

# Side-effect import does the bootstrap automatically. Subsequent
# imports are no-ops thanks to a process-env marker.

# If you want to bootstrap explicitly (e.g. inside a function):
doltlite.bootstrap()

# Find where the loaded libdoltlite came from:
doltlite.libdoltlite_path()  # absolute path
```

## See also

- [doltlite](https://github.com/dolthub/doltlite) — the underlying
  SQLite + Dolt engine
- [doltlite-sqlalchemy-getting-started](https://github.com/timsehn/doltlite-sqlalchemy-getting-started)
  — end-to-end SQLAlchemy demo (commits, branches, schema change, merge)

## License

Apache License 2.0. See [LICENSE](LICENSE).
