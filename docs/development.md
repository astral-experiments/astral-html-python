# Development

## Local checks

Run these commands from the repository root with Rust 1.97 or newer. The
project supports CPython 3.14 and 3.15. This example selects 3.14.

```sh
uv sync --locked --python 3.14
uv run --locked pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked --group benchmark ty check
uv run --locked --only-group zizmor --no-build zizmor --strict-collection --collect=workflows,actions .
cargo fmt --check
uv run --locked cargo clippy --locked --all-targets -- -D warnings
```

Set `GH_TOKEN` to a read-only GitHub token to include the same online audits as CI.

## Testing wheels

CI builds one source distribution and uses it for every wheel. CPython 3.14
and 3.15 each test their own native wheel and the same `cp314-abi3` wheel
built on 3.14. The tests use GIL-enabled CPython. To build the native wheel
on Linux, follow the
[benchmark build instructions](../benchmarks/README.md#reproduce).

To test the stable ABI on both versions, run from the repository root.

```sh
dist=$(mktemp -d)
uv build --sdist --no-sources --out-dir "$dist" --python 3.14
uv build "$dist"/*.tar.gz --wheel --no-sources --out-dir "$dist" --python 3.14 \
    --config-setting 'build-args=--compatibility pypi --auditwheel check --features abi3'
for py in 3.14 3.15; do
    uv sync --locked --no-install-project --python "$py"
    uv pip install --python .venv/bin/python --no-deps --strict --reinstall "$dist"/*-cp314-abi3-*.whl
    .venv/bin/python -I -m pytest --import-mode=importlib
done
```

The `-I` flag prevents Python from adding the checkout to the import path.

For a release, update the version in `pyproject.toml` and `Cargo.toml`, refresh
both lockfiles, and add a matching entry to [CHANGELOG.md](../CHANGELOG.md).
After merging, run **Start release** on `main`. It publishes the version from
the commit selected at dispatch, even if another change merges during CI.
