# Releasing doltlite-python

## Version policy

`doltlite-python` tracks the bundled `libdoltlite` release. The package
version equals the libdoltlite version. Loader-only fixes between
libdoltlite releases use PEP 440 post-releases (`0.11.2.post1`,
`0.11.2.post2`, …).

Three places to bump in lockstep:

| File                            | Field             |
|---------------------------------|-------------------|
| `pyproject.toml`                | `version`         |
| `src/doltlite/__init__.py`      | `__version__`     |
| `scripts/build-libdoltlite.sh`  | `DOLTLITE_REF`    |

## One-time PyPI setup

This only happens once, on first release. After that the trusted
publisher is wired up forever (modulo PyPI policy changes).

1. **Create the project on PyPI** — easiest path: configure a "pending"
   trusted publisher before the project exists.

   - Go to <https://pypi.org/manage/account/publishing/>
   - Under "Add a new pending publisher", fill in:
     - PyPI Project Name: `doltlite`
     - Owner: `dolthub`
     - Repository name: `doltlite-python`
     - Workflow name: `wheels.yml`
     - Environment name: `pypi`
   - Save. PyPI now trusts the matching workflow to publish on first run.

   (Alternative: build a wheel locally and `twine upload` it once to
   create the project, then add the trusted publisher as a normal
   non-pending entry. Either works.)

2. **(Optional) TestPyPI dry run** — repeat the above at
   <https://test.pypi.org/manage/account/publishing/> with project name
   `doltlite` and use a duplicate of the publish job pointed at TestPyPI
   to validate the pipeline before going to production PyPI.

## Cutting a release

1. Make sure libdoltlite v0.11.x has been released at
   <https://github.com/dolthub/doltlite/releases>.

2. Bump the three version fields above (see "Version policy"). Commit:

   ```bash
   git commit -am "Release 0.11.x"
   git push origin main
   ```

3. Wait for `wheels.yml` to go green on `main`. This validates that the
   build still works against the pinned libdoltlite ref before publishing.

4. Tag and push:

   ```bash
   git tag v0.11.x
   git push origin v0.11.x
   ```

   The tag push triggers `wheels.yml` again with the `publish` job
   enabled. After all four wheel artifacts upload, the `publish` job
   downloads them and pushes to PyPI via the trusted publisher.

5. Verify on PyPI: <https://pypi.org/project/doltlite/> should show the
   new version with wheels for `macosx_*_arm64`, `macosx_*_x86_64`,
   `manylinux_*_x86_64`, and `manylinux_*_aarch64`.

## Troubleshooting

- **`build_wheels` fails inside the manylinux container with missing
  build deps**: extend `CIBW_BEFORE_ALL_LINUX` in `wheels.yml`. The
  manylinux base image is AlmaLinux 8 (`manylinux_2_28`); package
  manager is `yum` / `dnf`.

- **macOS wheel build fails because libdoltlite's `install_name`
  conflicts with delocate**: we explicitly skip wheel repair
  (`CIBW_REPAIR_WHEEL_COMMAND=""`), so delocate shouldn't run. If you
  re-enable repair, you'll likely need to add the libdoltlite
  install_name to delocate's allowlist.

- **PyPI upload fails with "no permission"**: the trusted publisher
  config on PyPI may not match the workflow exactly. The workflow file
  name (`wheels.yml`), the environment name (`pypi`), the owner
  (`dolthub`), and the repo name (`doltlite-python`) all have to match
  what's registered at <https://pypi.org/manage/account/publishing/>.
