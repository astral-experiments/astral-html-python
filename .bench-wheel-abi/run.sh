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
    uv python install 3.14.9 3.15.1
    py314=$(uv python find --managed-python 3.14.9)
    py315=$(uv python find --managed-python 3.15.1)
fi
uv venv "$root/build-env" --python "$py314"
uv pip install --python "$root/build-env/bin/python" 'maturin==1.15.0'
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
tar -xzf "$archive" --strip-components=1 -C "$root/corpus" --wildcards '*/metadata.json' '*/test/html/*'
"$py314" -I "$helper_dir/measure.py" prepare "$root/corpus" "$root/sample"
for runtime in 314 315; do
    native="$root/env-$runtime-native/bin/python"
    "$native" -I "$helper_dir/measure.py" compare "$root/sample" "$native" \
        "$root/env-$runtime-abi3/bin/python" --pairs 20 --revision "$revision" --output "$out/cp$runtime"
done
cp "$helper_dir/measure.py" "$helper_dir/run.sh" "$out/"
"$py314" - "$out" "$revision" <<'PY'
import hashlib
import json
import os
import re
import sys
from pathlib import Path
out = Path(sys.argv[1])
revision = sys.argv[2]
runtimes = ("cp314", "cp315")
a, b = [json.loads((out / folder / "validation.json").read_text()) for folder in runtimes]
if a["native"]["digest"] != b["native"]["digest"]:
    raise ValueError("Different output between CPython versions")
if a["abi3"]["extension_sha256"] != b["abi3"]["extension_sha256"]:
    raise ValueError("Unexpected ABI3 binary difference between CPython versions")
if (out / "cp314/sample.json").read_bytes() != (out / "cp315/sample.json").read_bytes():
    raise ValueError("Different corpus selections between CPython versions")
info = a["native"]
provenance = (out / "provenance.txt").read_text()
cpu = next(line.split(":", 1)[1].strip() for line in provenance.splitlines() if line.startswith("Model name:"))
versions = [v["native"]["python"].split()[0] for v in (a, b)]
data_sha = hashlib.sha256((out / "cp314/sample.json").read_bytes()).hexdigest()
helper = os.environ.get("GITHUB_SHA", "local")
lines = [
    "# Native and stable-ABI wheel performance", "",
    f"This run compares native CPython wheels with one `cp314-abi3` wheel across seven HTML workloads. "
    f"All three wheels use parser commit `{revision}`. The same ABI3 binary was loaded under CPython "
    f"{versions[0]} and {versions[1]}.", "",
    "## Corpus and output checks", "",
    "The sample uses the test split of [WCXB at c039d5e](https://github.com/Murrough-Foley/"
    "web-content-extraction-benchmark/tree/c039d5ee9f5a3a984a0e167e63aacd04e76e78a9). For each "
    "of the seven page types, sort records by uncompressed byte length and page ID. Select 20 at "
    "the midpoint ranks of 20 equally sized bins. The timed input is a UTF-8 response body already in memory.",
    "",
    f"Across {info['pages']} pages, both wheels on both interpreters returned identical outputs "
    f"(SHA-256 `{info['digest']}`). Full parsing, retained anchor subtrees and cached tree selection "
    f"produced the same ordered href/text pairs. The parser returned {info['links']:,} links and "
    f"matched Lexbor {info['selectolax']} exactly on {info['lexbor_exact']} pages. Lexbor returned "
    f"{info['lexbor_links']:,} links. The artifact contains the differing page IDs, per-page output "
    f"digests and selected body hashes. The sample manifest SHA-256 is `{data_sha}`.", "",
    "## Paired timings", "",
    "One pair runs each wheel in a fresh process on the same CPU with the same seeded page and "
    "workload order. The first wheel alternates across 20 pairs per interpreter. Each job warms "
    "the full corpus, collects garbage, then times one full pass. Parse jobs include UTF-8 decoding. "
    "Existing-tree jobs use documents parsed before timing. The partial parse retains anchor subtrees "
    "with `parse(..., retain_subtrees=\"a\")`. The histogram iterates over `doc.select(\"*\")`.", "",
    "The native column gives mean elapsed microseconds per page and standard error. The ABI3 change "
    "is the geometric mean of the paired ABI3/native ratios, minus one. Positive values mean the "
    "ABI3 wheel took longer. The 95% percentile interval uses 10,000 paired bootstrap draws, "
    "stratified by which wheel ran first, with seed 42.", "",
]
for runtime, version in zip(runtimes, versions, strict=True):
    table = (out / runtime / "report.md").read_text().split("| Workload |", 1)[1]
    lines.extend([f"### CPython {version}", "", "| Workload |" + table.rstrip(), ""])
wheel_hashes = [line for line in provenance.splitlines() if re.match(r"^[0-9a-f]{64} ", line)]
lines.extend([
    "## Build provenance", "", f"The runner used an {cpu} and pinned each worker to the first allowed "
    f"CPU. All wheels used Rust 1.97.0, maturin 1.15.0, uv 0.12.23 and the parser's locked "
    "release build. The native wheels used each interpreter's full C API. The stable wheel used "
    "CPython 3.14 and Cargo feature `pyo3/abi3-py314`. Full build and host details are in "
    "[provenance.txt](provenance.txt).", "", "| Wheel | SHA-256 |", "| --- | --- |",
])
for line in wheel_hashes:
    sha, path = line.split()
    lines.append(f"| `{Path(path).name}` | `{sha}` |")
lines.extend([
    "", f"The parser commit was `{revision}` and the measurement harness commit was `{helper}`.", "",
    "## Reproduce", "", "Download the report bundle or use this results directory. From an "
    "astral-html-python checkout containing the parser commit, run the script below. It creates "
    "temporary build directories and isolated environments, builds the three wheels, and measures "
    "all 20 pairs for each interpreter. The default interpreter versions are CPython 3.14.9 and "
    "3.15.1. To provide your own interpreter executables, set `PYTHON_314` and `PYTHON_315`.",
    "", "```sh", "export RUSTUP_TOOLCHAIN=1.97.0",
    f'bash /path/to/results/run.sh {revision} /tmp/wheel-abi-rerun', "```", "",
    "The script fetches the pinned corpus by default. To reuse a copy, set `WCXB_ARCHIVE` to "
    "the absolute path of that revision's tar.gz archive. It needs Rust 1.97.0 and uv 0.12.23 "
    "installed. [Driver](run.sh) · [Measurement code](measure.py)", "",
    "[CPython 3.14 pairs](cp314/paired_ns.json) · [CPython 3.15 pairs](cp315/paired_ns.json) · "
    "[3.14 output checks](cp314/validation.json) · [3.15 output checks](cp315/validation.json) · "
    "[Sample manifest](cp314/sample.json)", "",
])
report = "\n".join(lines)
(out / "wheel-abi.md").write_text(report)
print(report)
# Preserve exact downloadable outputs on the separate results branch using the job's read-only logs.
if os.environ.get("GITHUB_ACTIONS"):
    import base64
    for path in sorted(out.rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            relative = str(path.relative_to(out))
            print(f"OUTPUTFILE {relative} {len(data)} {hashlib.sha256(data).hexdigest()}")
            for i in range(0, len(data), 1536):
                print(f"OUTPUTCHUNK {relative} {i} {base64.b64encode(data[i:i + 1536]).decode()}")
PY
