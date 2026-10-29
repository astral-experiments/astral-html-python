"""Compare release wheels on the WCXB corpus. See wheel-abi.md to reproduce."""

import argparse
import gc
import gzip
import hashlib
import json
import math
import multiprocessing
import platform
import random
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from statistics import geometric_mean, mean, median, stdev
from time import perf_counter_ns

# Full and partial Astral outputs on the pinned corpus and its Lexbor reference.
SAMPLE_SHA256 = "ad5f41f42102d8fc2ef21125e46c1acb123f0393e2030a70b6ae6a2bb9134ee4"
EXPECTED = {
    "links": 22_104,
    "pages_matching_lexbor": 137,
    "outputs_sha256": "579842beadc44e265f4836cef62d1d82ba9084ecf5b1b41197bf3e27c2adff79",
}


def prepare_pages(corpus, dest):
    # Sample the midpoint of each of 20 equal-sized bins, ordered by HTML byte length.
    meta = json.loads((corpus / "metadata.json").read_bytes())
    if any(
        len(key) != 4 or not key.isascii() or not key.isdecimal()
        for key in meta["files"]
    ):
        raise ValueError("WCXB page IDs must be four ASCII digits")
    groups = defaultdict(list)
    for key, row in meta["files"].items():
        if row["split"] == "test":
            path = corpus / "test" / "html" / f"{key}.html.gz"
            raw = gzip.decompress(path.read_bytes())
            groups[row["page_type"]].append((len(raw), key, row["domain"], raw))
    sample = []
    for group in groups.values():
        ordered = sorted(group)
        sample.extend(ordered[(2 * i + 1) * len(group) // 40] for i in range(20))
    # Pin the identities and bytes actually timed, even when a changed input
    # would yield the same extracted links, text and tag histogram.
    digest = hashlib.sha256()
    for _, key, _, raw in sorted(sample, key=lambda row: row[1]):
        digest.update(key.encode("ascii"))
        digest.update(hashlib.sha256(raw).digest())
    if digest.hexdigest() != SAMPLE_SHA256:
        raise ValueError("Page IDs or HTML bodies differ from the pinned WCXB sample")
    for _, key, _, raw in sample:
        (dest / key).write_bytes(raw)
    sizes, _, domains, _ = zip(*sample)
    return {
        "pages": len(sizes),
        "domains": len(set(domains)),
        "html_bytes": [min(sizes), median(sizes), max(sizes)],
    }


def links(doc):
    return [(node.get("href"), node.text) for node in doc.select("a[href]")]


def metadata(doc):
    result = []
    for css, attr in (
        ("title", None),
        ('link[rel~="canonical"]', "href"),
        ('meta[name="description"]', "content"),
        ('meta[property="og:image"]', "content"),
    ):
        node = doc.select_one(css)
        result.append(None if node is None else node.get(attr) if attr else node.text)
    return result


def check_links(parse, sources):
    from selectolax.lexbor import LexborHTMLParser

    count = matches = 0
    for raw in sources:
        html = raw.decode()
        actual = links(parse(html))
        if links(parse(html, retain_subtrees="a")) != actual:
            raise ValueError("Partial-tree links differ from the full tree")
        reference = LexborHTMLParser(html).css("a[href]")
        count += len(actual)
        matches += actual == [(n.attrs.get("href"), n.text()) for n in reference]
    return {"links": count, "pages_matching_lexbor": matches}


def worker(wheel_dir, pages_dir, seed):
    # Import from this exact wheel in a fresh interpreter, never an editable install.
    sys.path.insert(0, str(wheel_dir))
    from astral_html import _astral_html, parse

    if not Path(_astral_html.__file__).resolve().is_relative_to(wheel_dir.resolve()):
        raise RuntimeError(f"Loaded the wrong extension: {_astral_html.__file__}")
    rng = random.Random(0 if seed is None else seed)
    paths = sorted(pages_dir.iterdir())
    rng.shuffle(paths)
    pages = [p.read_bytes() for p in paths]
    docs = [parse(page.decode()) for page in pages]
    jobs = {
        "parse": (pages, lambda b: parse(b.decode())),
        "parse + links": (pages, lambda b: links(parse(b.decode()))),
        "partial parse + links": (
            pages,
            lambda b: links(parse(b.decode(), retain_subtrees="a")),
        ),
        "links on parsed tree": (docs, links),
        "parse + metadata": (pages, lambda b: metadata(parse(b.decode()))),
        "parse + headings and paragraphs": (
            pages,
            lambda b: [
                (n.tag, n.text.strip())
                for n in parse(b.decode()).select("h1, h2, h3, h4, h5, h6, p")
            ],
        ),
        "tag histogram on parsed tree": (
            docs,
            lambda d: Counter(n.tag for n in d.select("*")),
        ),
    }
    if seed is None:
        # Hash complete ordered results, including unmodified href and descendant text.
        result = check_links(parse, pages)
        digest = hashlib.sha256()
        for name, (inputs, run) in jobs.items():
            if name != "parse":  # The other tasks observe the contents of the parse.
                for item in inputs:
                    digest.update(json.dumps(run(item), sort_keys=True).encode())
        return dict(result, outputs_sha256=digest.hexdigest())

    names = list(jobs)
    rng.shuffle(names)  # The other wheel gets these same task and page orders.
    times = {}
    for name in names:
        inputs, run = jobs[name]
        for item in inputs:
            run(item)
        gc.collect()  # GC stays enabled. Results are released inside the timed loop.
        start = perf_counter_ns()
        for item in inputs:
            run(item)
        times[name] = (perf_counter_ns() - start) / len(inputs) / 1000
    return times


def summarize(pairs):
    print("| Workload | Native µs/page ± SE | ABI3 change (paired 95% interval) |")
    print("| --- | ---: | ---: |")
    for name in sorted(pairs[0][0]):
        times = [native[name] for native, _ in pairs]
        ratios = [abi3[name] / native[name] for native, abi3 in pairs]
        # Bootstrap whole pairs within each execution order. Pages are a fixed corpus,
        # not independent observations of the performance difference between wheels.
        strata = [list(map(math.log, ratios[i::2])) for i in (0, 1)]
        rng = random.Random(42)
        boot = sorted(
            math.expm1(sum(sum(rng.choices(s, k=len(s))) for s in strata) / len(ratios))
            for _ in range(10_000)
        )
        se = stdev(times) / math.sqrt(len(times))
        change = geometric_mean(ratios) - 1
        print(
            f"| {name} | {mean(times):.1f} ± {se:.1f} | {change:+.1%} "
            f"({boot[250]:+.1%} to {boot[9749]:+.1%}) |"
        )


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("corpus", nargs="?", type=Path, help="WCXB checkout")
    cli.add_argument("wheels", nargs="?", type=Path, help="wheel directory")
    cli.add_argument("--pairs", type=int, default=20)
    action = cli.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path, help="save raw paired µs/page")
    action.add_argument("--check", action="store_true", help="only verify both wheels")
    action.add_argument("--summarize", type=Path, help="print results from a saved run")
    args = cli.parse_args()
    if args.summarize:
        if args.corpus or args.wheels:
            cli.error("--summarize takes only the saved run file")
        summarize(json.loads(args.summarize.read_bytes())["pairs_native_then_abi3"])
        return
    if args.corpus is None or args.wheels is None:
        cli.error("a corpus and wheel directory are required")
    if args.pairs < 4 or args.pairs % 2:
        cli.error("--pairs must be even and at least 4, to balance execution order")

    with tempfile.TemporaryDirectory() as tmp:
        pages = Path(tmp, "pages")
        pages.mkdir()
        report = prepare_pages(args.corpus, pages)
        report["python"] = platform.python_version()
        print(report, flush=True)
        cp = f"cp{sys.version_info.major}{sys.version_info.minor}"
        wheels = []
        hashes = {}
        for tag in (f"{cp}-{cp}", "cp314-abi3"):
            matches = list(args.wheels.glob(f"astral_html_python-*-{tag}-*.whl"))
            if len(matches) != 1:
                cli.error(
                    f"expected one {tag} astral-html-python wheel, found {matches}"
                )
            whl = matches[0]
            directory = Path(tmp, whl.name)
            with whl.open("rb") as f:
                hashes[whl.name] = hashlib.file_digest(f, "sha256").hexdigest()
            with zipfile.ZipFile(whl) as z:
                z.extractall(directory)
            wheels.append(directory)
            print(whl.name, flush=True)
        # One process at a time. Each consecutive pair reverses which wheel goes first.
        with multiprocessing.get_context("spawn").Pool(1, maxtasksperchild=1) as pool:

            def run(wheel, seed):
                return pool.apply(worker, (wheel, pages, seed))

            for wheel in wheels:
                checked = run(wheel, None)
                if checked != EXPECTED:
                    raise ValueError(
                        f"{wheel.name} outputs differ from baseline: {checked}"
                    )
            print(
                f"Verified outputs against the corpus baseline: {EXPECTED}", flush=True
            )
            if args.check:
                return
            native, abi3 = wheels
            pairs = []
            for seed in range(args.pairs):
                order = (abi3, native) if seed % 2 else (native, abi3)
                times = {wheel: run(wheel, seed) for wheel in order}
                pairs.append([times[native], times[abi3]])
                print(f"Pair {seed + 1}/{args.pairs}", flush=True)
        report.update(
            EXPECTED,
            wheels=[w.name for w in wheels],
            wheel_sha256=hashes,
            pairs_native_then_abi3=pairs,
        )
        args.output.write_text(json.dumps(report) + "\n")
        summarize(pairs)


if __name__ == "__main__":
    main()
