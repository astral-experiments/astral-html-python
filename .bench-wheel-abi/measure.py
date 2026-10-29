"""Reproduce the wheel experiment. Use the accompanying workflow to build and install the wheels."""
import argparse
import gc
import gzip
import hashlib
import json
import math
import os
import platform
import random
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from time import perf_counter_ns
from urllib.parse import urlsplit

CORPUS_REV = "c039d5ee9f5a3a984a0e167e63aacd04e76e78a9"
JOBS = ("parse", "parse + links", "partial parse + links", "links on parsed tree",
        "parse + metadata", "parse + headings and paragraphs", "tag histogram on parsed tree")
META = (("title", None), ('link[rel~="canonical"]', "href"),
        ('meta[name="description"]', "content"), ('meta[property="og:image"]', "content"))


def dump(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def digest(value):
    contents = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(contents).hexdigest()


def prepare(root, folder):
    groups = defaultdict(list)
    for annotation in sorted((root / "test" / "ground-truth").glob("*.json")):
        record = json.loads(annotation.read_text())
        key = annotation.stem
        raw = gzip.decompress((root / "test" / "html" / f"{key}.html.gz").read_bytes())
        groups[record["page_type"]].append((len(raw), key, urlsplit(record["url"]).hostname, raw))
    if len(groups) != 7 or min(map(len, groups.values()), default=0) < 20:
        raise ValueError("Expected at least twenty pages in each of seven test-split page types")
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for kind, rows in sorted(groups.items()):
        rows.sort()
        for i in range(20):
            size, key, host, raw = rows[(2 * i + 1) * len(rows) // 40]
            (folder / f"{key}.html").write_bytes(raw)
            manifest[key] = dict(type=kind, bytes=size, host=host, sha256=hashlib.sha256(raw).hexdigest())
    if len(manifest) != 140:
        raise ValueError("Expected 140 distinct selected page IDs")
    dump(folder / "sample.json", manifest)


def links(doc):
    return [(node.get("href"), node.text) for node in doc.select("a[href]")]


def metadata(doc):
    values = []
    for selector, attribute in META:
        node = doc.select_one(selector)
        values.append(None if node is None else node.text if attribute is None else node.get(attribute))
    return values


def worker(folder, seed, verify):
    import astral_html
    from astral_html import _astral_html
    from importlib.metadata import version
    from selectolax.lexbor import LexborHTMLParser
    manifest = json.loads((folder / "sample.json").read_text())
    bodies = {key: (folder / f"{key}.html").read_bytes() for key in sorted(manifest)}
    for key, raw in bodies.items():
        if hashlib.sha256(raw).hexdigest() != manifest[key]["sha256"]:
            raise ValueError(f"Page {key} does not match its manifest")
    keys = list(bodies)
    parse = astral_html.parse
    docs = {key: parse(raw.decode()) for key, raw in bodies.items()}
    jobs = {
        JOBS[0]: lambda key: parse(bodies[key].decode()),
        JOBS[1]: lambda key: links(parse(bodies[key].decode())),
        JOBS[2]: lambda key: links(parse(bodies[key].decode(), retain_subtrees="a")),
        JOBS[3]: lambda key: links(docs[key]),
        JOBS[4]: lambda key: metadata(parse(bodies[key].decode())),
        JOBS[5]: lambda key: [(n.tag, n.text.strip()) for n in
                              parse(bodies[key].decode()).select("h1, h2, h3, h4, h5, h6, p")],
        JOBS[6]: lambda key: Counter(n.tag for n in docs[key].select("*")),
    }
    if verify:
        hashed, lexbor_count, count, matches = {}, 0, 0, 0
        differing_ids = []
        for key in keys:
            outputs = {job: jobs[job](key) for job in JOBS[1:]}
            reference = [(n.attrs.get("href"), n.text()) for n in
                         LexborHTMLParser(bodies[key].decode()).css("a[href]")]
            if not outputs[JOBS[1]] == outputs[JOBS[2]] == outputs[JOBS[3]]:
                raise ValueError(f"Full/partial/existing-tree links differ on page {key}")
            count += len(outputs[JOBS[1]])
            lexbor_count += len(reference)
            if outputs[JOBS[1]] == reference:
                matches += 1
            else:
                differing_ids.append(key)
            hashed[key] = digest(outputs)
        extension = Path(_astral_html.__file__)
        return dict(digest=digest(hashed), per_page=hashed, links=count, lexbor_links=lexbor_count,
                    lexbor_exact=matches, differing_ids=differing_ids, pages=len(keys),
                    python=sys.version, executable=sys.executable, platform=platform.platform(),
                    selectolax=version("selectolax"), extension=extension.name,
                    extension_sha256=hashlib.sha256(extension.read_bytes()).hexdigest())
    rng = random.Random(seed)
    rng.shuffle(keys)
    tasks = list(jobs)
    rng.shuffle(tasks)
    times = {}
    for name in tasks:
        job = jobs[name]
        for key in keys:
            job(key)
        gc.collect()
        start = perf_counter_ns()
        for key in keys:
            job(key)
        times[name] = perf_counter_ns() - start
    return times


def interval(records, job):
    strata = [[], []]
    for pair in records:
        strata[pair["abi3_first"]].append(math.log(pair["abi3"][job] / pair["native"][job]))
    rng = random.Random(42)
    draws = sorted(math.expm1(statistics.mean(
        x for group in strata for x in rng.choices(group, k=len(group))
    )) * 100 for _ in range(10_000))
    estimate = 100 * math.expm1(statistics.mean(x for group in strata for x in group))
    return estimate, draws[250], draws[9749]


def compare(args):
    data = args.output
    data.mkdir(parents=True, exist_ok=True)
    folder = args.sample.resolve()
    manifest = json.loads((folder / "sample.json").read_text())
    count = len(manifest)
    dump(data / "sample.json", manifest)
    binaries = {"native": args.native, "abi3": args.abi3}
    if hasattr(os, "sched_getaffinity"):
        os.sched_setaffinity(0, {min(os.sched_getaffinity(0))})
    def run(exe, seed, verify=False):
        cmd = [exe, "-I", str(Path(__file__).resolve()), "worker", str(folder), str(seed)]
        if verify:
            cmd.append("--verify")
        return json.loads(subprocess.check_output(cmd))
    validation = {name: run(exe, 0, verify=True) for name, exe in binaries.items()}
    dump(data / "validation.json", validation)
    if validation["native"]["digest"] != validation["abi3"]["digest"]:
        raise ValueError("The two wheels returned different values")
    if (validation["native"]["python"] != validation["abi3"]["python"]
        or validation["native"]["selectolax"] != validation["abi3"]["selectolax"]):
        raise ValueError("Runtime or reference library differs between wheels")
    if ".abi3." not in validation["abi3"]["extension"] or ".cpython-" not in validation["native"]["extension"]:
        raise ValueError("Unexpected extension module file suffix")
    records = []
    for pair in range(args.pairs):
        abi_first = bool(pair % 2)
        record = dict(seed=pair, abi3_first=abi_first)
        for name in (("abi3", "native") if abi_first else ("native", "abi3")):
            record[name] = run(binaries[name], pair)
        records.append(record)
        dump(data / "paired_ns.json", records)
        print(f"Completed pair {pair + 1}/{args.pairs}", flush=True)
    info = validation["native"]
    lines = [f"# Wheel ABI timings on CPython {platform.python_version()}", "",
             f"Parser source `{args.revision}`. WCXB source `{CORPUS_REV}`. Output SHA-256 `{info['digest']}`.", "",
             f"{count} test-split pages. {info['links']:,} extracted links. "
             f"{info['lexbor_exact']} pages matched Lexbor {info['selectolax']} exactly. "
             f"Both wheel builds gave identical output.", "",
             f"{args.pairs} fresh-process pairs with alternating run order. The native column gives "
             "an arithmetic mean and standard error in µs/page. Change is the geometric mean of paired "
             "ABI3/native timing ratios minus one. Positive values mean a slower ABI3 wheel. "
             "The 95% interval resamples pairs within each order (10,000 draws, seed 42).", "",
             "| Workload | Native (µs/page ± SE) | ABI3 change | 95% interval |",
             "| --- | ---: | ---: | ---: |"]
    for name in JOBS:
        native = [r["native"][name] / 1000 / count for r in records]
        ratio, lo, hi = interval(records, name)
        lines.append(f"| {name} | {statistics.mean(native):.2f} ± "
                     f"{statistics.stdev(native) / math.sqrt(len(native)):.2f} | "
                     f"{ratio:+.2f}% | {lo:+.2f}% to {hi:+.2f}% |")
    report = "\n".join(lines) + "\n"
    (data / "report.md").write_text(report)
    print(report, flush=True)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    modes = cli.add_subparsers(dest="mode", required=True)
    prep = modes.add_parser("prepare")
    prep.add_argument("corpus", type=Path)
    prep.add_argument("sample", type=Path)
    work = modes.add_parser("worker")
    work.add_argument("sample", type=Path)
    work.add_argument("seed", type=int)
    work.add_argument("--verify", action="store_true")
    bench = modes.add_parser("compare")
    bench.add_argument("sample", type=Path)
    bench.add_argument("native")
    bench.add_argument("abi3")
    bench.add_argument("--pairs", type=int, default=20)
    bench.add_argument("--revision", required=True)
    bench.add_argument("--output", type=Path, required=True)
    args = cli.parse_args()
    if args.mode == "prepare":
        prepare(args.corpus, args.sample)
    elif args.mode == "worker":
        print(json.dumps(worker(args.sample, args.seed, args.verify)))
    else:
        if args.pairs < 2 or args.pairs % 2:
            cli.error("--pairs must be an even number of at least 2")
        compare(args)


if __name__ == "__main__":
    main()
