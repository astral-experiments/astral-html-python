# Development

## Local checks

Run these commands from the repository root with Rust 1.97 or newer. The
project supports CPython 3.14 and 3.15. This example selects 3.14.

```sh
uv sync --locked --python 3.14
uv run --locked --group benchmark pytest
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked --group benchmark ty check
cargo fmt --check
uv run --locked cargo clippy --locked --all-targets -- -D warnings
```

## Testing the wheel

CI builds and tests a separate wheel for CPython 3.14 and 3.15. Each job
builds its wheel from the source distribution. To repeat the package test
on Linux, first build and install the wheel for your interpreter.
[Wheel build and installation commands](../benchmarks/README.md#reproduce)

Run pytest with the environment's Python to test the installed wheel. The
`-I` flag prevents Python from adding the current directory to the import path.

```sh
.venv/bin/python -I -m pytest --import-mode=importlib
```

The package version comes from the Cargo manifest. CI also checks the
benchmark outputs and runs a short timing sample.
[Cargo.toml](../Cargo.toml) · [CI workflow](../.github/workflows/ci.yml)
