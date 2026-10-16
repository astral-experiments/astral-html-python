# Building and checking a distribution

The distribution name is `astral-html-python` and the import name is
`astral_html`. Set the version in `Cargo.toml`. Maturin uses that version for
both Python distributions and uses `Cargo.lock` to resolve the Rust dependencies.

CI checks standard CPython 3.14 and 3.15 on Linux x86-64, including a build with
the minimum supported Rust version. On free-threaded CPython, importing the
extension currently enables the GIL. Publish wheels only for configurations
that have been tested.

From a clean checkout, use the same Python interpreter for each command:

```sh
uv sync --locked --no-install-project --group benchmark
candidate_dir=$(mktemp -d)
uv build --no-sources --out-dir "$candidate_dir" \
    --config-setting 'build-args=--compatibility pypi --auditwheel check'
uv pip install --python .venv/bin/python --no-deps --strict "$candidate_dir"/*.whl
uv run --no-sync python -I -m pytest --import-mode=importlib
```

`uv build` creates the source distribution first, then builds the wheel from that
archive. Maturin checks the wheel's platform compatibility and records the
result in its filename. The test suite and captured-page fixtures stay in the
checkout. Publishing the checked artifacts is a separate release-owner action.
