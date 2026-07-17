#!/usr/bin/env bash
# Build libdoltlite from source and stage it into the package's _lib dir.
#
# Invoked by cibuildwheel as `before-build` (see pyproject.toml). When run
# locally, set DOLTLITE_SRC to a checkout of the doltlite source tree;
# otherwise the script clones the upstream repo at the pinned ref.
#
# Output:
#   src/doltlite/_lib/libdoltlite.dylib  (macOS)
#   src/doltlite/_lib/libdoltlite.so     (Linux)
set -euo pipefail

# Adjust this when releasing — pin to the doltlite commit/tag the wheel
# targets. SKETCH: hardcoded to a placeholder; Tim should update.
DOLTLITE_REPO="${DOLTLITE_REPO:-https://github.com/dolthub/doltlite}"
# Pinned to the libdoltlite release that this doltlite-python version
# bundles. Bump in lockstep with the package version in pyproject.toml.
DOLTLITE_REF="${DOLTLITE_REF:-v0.11.33}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIB_OUT_DIR="$REPO_ROOT/src/doltlite/_lib"

case "$(uname -s)" in
  Darwin) LIB_NAME="libdoltlite.dylib" ;;
  Linux)  LIB_NAME="libdoltlite.so" ;;
  *) echo "Unsupported platform: $(uname -s)" >&2; exit 1 ;;
esac

if [[ -z "${DOLTLITE_SRC:-}" ]]; then
  DOLTLITE_SRC="$(mktemp -d)/doltlite"
  echo "Cloning $DOLTLITE_REPO@$DOLTLITE_REF -> $DOLTLITE_SRC"
  git clone --depth=1 --branch "$DOLTLITE_REF" "$DOLTLITE_REPO" "$DOLTLITE_SRC"
fi

echo "Building $LIB_NAME from $DOLTLITE_SRC"
mkdir -p "$DOLTLITE_SRC/build"
(
  cd "$DOLTLITE_SRC/build"
  if [[ ! -f Makefile ]]; then
    ../configure
  fi
  # Use parallel build; -j$(nproc) on Linux, sysctl on macOS.
  if command -v nproc >/dev/null; then
    JOBS="$(nproc)"
  else
    JOBS="$(sysctl -n hw.ncpu 2>/dev/null || echo 2)"
  fi
  make -j"$JOBS" "$LIB_NAME"
)

mkdir -p "$LIB_OUT_DIR"
cp "$DOLTLITE_SRC/build/$LIB_NAME" "$LIB_OUT_DIR/$LIB_NAME"
echo "Staged $LIB_OUT_DIR/$LIB_NAME"
