"""Side-effect import: bootstraps libdoltlite so that the standard
`sqlite3` module (and anything that uses it, including SQLAlchemy) sees
Dolt's version control functions and virtual tables.

Usage:

    import doltlite          # one-time bootstrap
    import sqlite3
    conn = sqlite3.connect("repo.db")
    conn.execute("SELECT dolt_commit('-A', '-m', 'init')")

On macOS, and on Linux when `sqlite3` was already imported, the
interpreter re-execs itself once with the right loader environment
(`DYLD_INSERT_LIBRARIES` / `LD_PRELOAD`). On a clean Linux process the
preload happens in-process via `ctypes.CDLL(..., RTLD_GLOBAL)` and no
re-exec occurs.
"""
from ._loader import bootstrap, libdoltlite_path

bootstrap()

__all__ = ["bootstrap", "libdoltlite_path"]
__version__ = "0.11.13"
