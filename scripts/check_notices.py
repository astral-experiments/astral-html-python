"""Refresh notices with --write, or verify them and any named wheels / source archives."""

import argparse
import json
import re
import subprocess
import tarfile
import zipfile
from collections import defaultdict
from pathlib import Path

NOTICE = "THIRD-PARTY-NOTICES.txt"
INTRO = """Third-party Rust dependencies

These are the locked crate sources used to build the extension, including
platform-specific and build-time dependencies. The links provide the exact
unmodified sources, including the Source Code Form of the MPL-2.0 components.
The following sections reproduce the licenses and additional notices.
"""


def source_notices(crate):
    # Some crates embed separately licensed code or data in Rust sources.
    # For example, astral-html includes the WHATWG entity table under BSD-3-Clause.
    for path in sorted(crate.rglob("*.rs")):
        if {"benches", "examples", "tests"}.intersection(path.relative_to(crate).parts):
            continue
        for block in re.findall(
            r"(?m)^(?://[^\n]*\n)+", path.read_text(encoding="utf-8")
        ):
            if re.search(r"(?im)^// copyright [©(\d]", block):
                lines = (
                    line.removeprefix("//").removeprefix(" ")
                    for line in block.splitlines()
                )
                yield "\n".join(lines).strip()


def generate():
    metadata = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--locked", "--format-version", "1"]
        )
    )
    crates = sorted(
        (p for p in metadata["packages"] if p["source"]),
        key=lambda p: (p["name"], p["version"]),
    )
    # selectors omits the standalone MPL text, but ships the MPL notice in its sources.
    mpl = next(
        Path(p["manifest_path"]).parent / "LICENSE"
        for p in crates
        if p["name"] == "cssparser"
    )
    output = [INTRO]
    sections = defaultdict(list)
    for package in crates:
        name, version = package["name"], package["version"]
        if package["source"] != "registry+https://github.com/rust-lang/crates.io-index":
            raise ValueError(f"Check source availability for {name} {version}")
        label = f"{name} {version}"
        url = f"https://static.crates.io/crates/{name}/{name}-{version}.crate"
        output.append(f"{label} ({package['license']})  {url}")
        crate = Path(package["manifest_path"]).parent
        files = sorted(
            path
            for path in crate.iterdir()
            if path.is_file()
            and path.name.lower().startswith(
                ("license", "licence", "copying", "notice", "copyright")
            )
        )
        if not files and package["license"] == "MPL-2.0":
            files = [mpl]
        if not files:
            raise ValueError(f"Check license files for {label}")
        texts = [path.read_text(encoding="utf-8").strip() for path in files]
        for body in dict.fromkeys([*texts, *source_notices(crate)]):
            sections[body].append(label)

    for body, labels in sections.items():
        output.extend(("", "=" * 72, ", ".join(labels), "", body))
    return "\n".join(line.rstrip() for line in "\n".join(output).splitlines()) + "\n"


def check_archive(path, expected):
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as wheel:
            (name,) = [
                n
                for n in wheel.namelist()
                if n.endswith(f".dist-info/licenses/{NOTICE}")
            ]
            actual = wheel.read(name)
    else:
        with tarfile.open(path, "r:gz") as sdist:
            (member,) = [
                m for m in sdist.getmembers() if m.name.split("/")[1:] == [NOTICE]
            ]
            stream = sdist.extractfile(member)
            if stream is None:
                raise ValueError(f"No notice file in {path}")
            actual = stream.read()
    if actual != expected:
        raise ValueError(f"Incorrect {NOTICE} in {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("archives", nargs="*", type=Path)
    args = parser.parse_args()
    expected = generate().encode()
    if args.write:
        Path(NOTICE).write_bytes(expected)
    elif Path(NOTICE).read_bytes() != expected:
        raise SystemExit(
            f"Refresh {NOTICE} with python scripts/check_notices.py --write"
        )
    for path in args.archives:
        check_archive(path, expected)


if __name__ == "__main__":
    main()
