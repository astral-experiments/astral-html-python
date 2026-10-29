#!/usr/bin/env bash
set -euo pipefail
revision=${1:?pass the full parser source commit}
helper_dir=$(cd "$(dirname "$0")" && pwd)
out=${2:?pass an empty output directory}
mkdir -p "$out"
out=$(cd "$out" && pwd)
root=$(mktemp -d)
mkdir -p "$root/wheels" "$root/corpus"
# Build from the requested parser tree, keeping the checkout with the driver untouched.
git archive "$revision" | tar -x -C "$root"
cd "$root"
if [[ -n "${PYTHON_314:-}" && -n "${PYTHON_315:-}" ]]; then
    py314="$PYTHON_314"
    py315="$PYTHON_315"
else
    uv python install 3.14 3.15
    py314=$(uv python find --managed-python 3.14)
    py315=$(uv python find --managed-python 3.15)
fi
uv venv "$root/build-env" --python "$py314"
uv pip install --python "$root/build-env/bin/python" 'maturin>=1.9.4,<2'
maturin="$root/build-env/bin/maturin"
for spec in native314 native315 abi3; do
    args=()
    py="$py314"
    if [[ "$spec" == native315 ]]; then py="$py315"; fi
    if [[ "$spec" == abi3 ]]; then args=(--features pyo3/abi3-py314); fi
    CARGO_TARGET_DIR="$root/target-$spec" "$maturin" build --release --locked --compatibility linux \
        --interpreter "$py" --out "$root/wheels" "${args[@]}"
done
native314=("$root"/wheels/*-cp314-cp314-*.whl)
native315=("$root"/wheels/*-cp315-cp315-*.whl)
abi3=("$root"/wheels/*-cp314-abi3-*.whl)
for wheel in "${native314[@]}" "${native315[@]}" "${abi3[@]}"; do test -f "$wheel"; done
[[ ${#native314[@]} == 1 && ${#native315[@]} == 1 && ${#abi3[@]} == 1 ]]
lexbor=$("$py314" -c 'import tomllib; print(next(p["version"] for p in tomllib.load(open("uv.lock","rb"))["package"] if p["name"] == "selectolax"))')
for runtime in 314 315; do
    py="$py314"
    native="${native314[0]}"
    if [[ "$runtime" == 315 ]]; then py="$py315"; native="${native315[0]}"; fi
    for flavor in native abi3; do
        envdir="$root/env-$runtime-$flavor"
        wheel="$native"
        if [[ "$flavor" == abi3 ]]; then wheel="${abi3[0]}"; fi
        uv venv "$envdir" --python "$py"
        uv pip install --python "$envdir/bin/python" "selectolax==$lexbor" "$wheel"
    done
done
{
    echo "Parser commit: $revision"
    echo "Harness commit: ${GITHUB_SHA:-local}"
    echo "Runner: ${ImageOS:-unknown} ${ImageVersion:-unknown}"
    uv --version
    "$maturin" --version
    "$py314" --version
    "$py315" --version
    rustc -Vv
    cargo --version
    uname -a
    lscpu
    (cd "$root/wheels" && sha256sum ./*.whl)
} > "$out/provenance.txt"
if [[ -n "${WCXB_ARCHIVE:-}" ]]; then archive="$WCXB_ARCHIVE"; else
    archive="$root/wcxb.tar.gz"
    curl --fail --location --retry 3 -o "$archive" \
        "https://codeload.github.com/Murrough-Foley/web-content-extraction-benchmark/tar.gz/c039d5ee9f5a3a984a0e167e63aacd04e76e78a9"
fi
tar -xzf "$archive" --strip-components=1 -C "$root/corpus" --wildcards '*/test/ground-truth/*' '*/test/html/*'
"$py314" -I "$helper_dir/measure.py" prepare "$root/corpus" "$root/sample"
for runtime in 314 315; do
    native="$root/env-$runtime-native/bin/python"
    "$native" -I "$helper_dir/measure.py" compare "$root/sample" "$native" \
        "$root/env-$runtime-abi3/bin/python" --pairs 20 --revision "$revision" --output "$out/cp$runtime"
done
"$py314" - "$out" <<'PY'
import json
import sys
from pathlib import Path
out = Path(sys.argv[1])
a, b = [json.loads((out / folder / "validation.json").read_text()) for folder in ("cp314", "cp315")]
if a["native"]["digest"] != b["native"]["digest"]:
    raise ValueError("Different output between CPython versions")
if a["abi3"]["extension_sha256"] != b["abi3"]["extension_sha256"]:
    raise ValueError("Unexpected ABI3 binary difference between CPython versions")
PY
cp "$helper_dir/measure.py" "$helper_dir/run.sh" "$out/"
cat "$out/cp314/report.md" "$out/cp315/report.md"
