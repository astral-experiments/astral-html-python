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
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
```

## Testing the wheel

CI builds a source distribution, builds a wheel from that archive, and tests
the installed wheel on both Python versions. To run the same package test on
Linux, follow the [wheel build and installation steps](../benchmarks/README.md#reproduce),
then run the test suite using the wheel's environment.

```sh
.venv/bin/python -I -m pytest --import-mode=importlib
```

The package version comes from [Cargo.toml](../Cargo.toml). The
[CI workflow](../.github/workflows/ci.yml) also checks the benchmark outputs
and runs a short timing sample.
