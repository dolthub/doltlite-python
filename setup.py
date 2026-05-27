"""Shim that produces a `py3-none-<platform>` wheel.

The package is pure Python by file count but ships a precompiled
libdoltlite shared library — so its wheel must be tagged for a specific
OS + arch, yet libdoltlite is the same .dylib/.so for every CPython
version. So we want `py3-none-macosx_15_0_arm64` rather than either
`py3-none-any` (wrong: not portable across OS/arch) or
`cp314-cp314-macosx_15_0_arm64` (wrong: one wheel per Python version).

All other metadata lives in pyproject.toml.
"""
from setuptools import setup
from setuptools.dist import Distribution
from wheel.bdist_wheel import bdist_wheel


class BinaryDistribution(Distribution):
    def has_ext_modules(self):
        return True


class PlatformWheel(bdist_wheel):
    def get_tag(self):
        _impl, _abi, plat = super().get_tag()
        return "py3", "none", plat


setup(distclass=BinaryDistribution, cmdclass={"bdist_wheel": PlatformWheel})
