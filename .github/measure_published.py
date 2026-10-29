"""Run the published suite on the selected source checkout; emit portable results."""

import base64
import csv
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
from importlib.metadata import distribution, version

directory = Path("benchmarks")
out = Path(os.environ["RUNNER_TEMP"]) / "results"
out.mkdir()
cpu = min(os.sched_getaffinity(0))
def output(args):
    return subprocess.check_output(args, text=True).strip()

def measure(filename, args):
    command = ["taskset", "-c", str(cpu), sys.executable, "-I", "benchmarks/run.py", *args]
    print("Running", *command, flush=True)
    with (out / filename).open("w") as capture:
        with subprocess.Popen(command, stdout=subprocess.PIPE, text=True) as worker:
            for line in worker.stdout:
                print(line, end="", flush=True)
                capture.write(line)
        if worker.returncode:
            raise subprocess.CalledProcessError(worker.returncode, command)
    return (out / filename).read_text()

def cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]

def fixture_rows(log):
    rows = {}
    for line in log.splitlines():
        if not line.startswith(("| pypi |", "| github |", "| wikipedia |")):
            continue
        page, parser, workload, timing = cells(line)
        rows.setdefault(page, {}).setdefault(parser, {})[workload] = timing
    return rows

packages = {name: version(name) for name in ("astral-html-python", "selectolax", "lxml", "cssselect", "beautifulsoup4")}
wheel_header = distribution("astral-html-python").read_text("WHEEL")
build = re.search(r"^Generator: (.*)$", wheel_header, re.M).group(1).strip()
cpu_model = next(line.partition(":")[2].strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name"))
meta = {
    "revision": output(["git", "rev-parse", "HEAD"]),
    "measured_on": datetime.datetime.now(datetime.timezone.utc).date().isoformat(),
    "cpu": cpu,
    "cpu_model": cpu_model,
    "machine": platform.machine(),
    "kernel": platform.release(),
    "glibc": platform.libc_ver()[1],
    "runner_image": os.environ.get("ImageOS"),
    "image_version": os.environ.get("ImageVersion"),
    "os": platform.freedesktop_os_release()["PRETTY_NAME"],
    "python": platform.python_version(),
    "rust": output(["rustc", "--version"]),
    "build": build,
    "packages": packages,
    "run_id": os.environ["GITHUB_RUN_ID"],
}
print("ENVIRONMENT " + json.dumps(meta), flush=True)
archive = Path(os.environ["RUNNER_TEMP"]) / "wcxb.tar.gz"
measure("snapshot-check.txt", ["--check"])
fixtures = fixture_rows(measure("snapshot-times.txt", ["--samples", "12", "--min-sample-ms", "12"]))
assert sum(len(work) for page in fixtures.values() for work in page.values()) == 66, fixtures
memory = fixture_rows(measure("snapshot-memory.txt", ["--memory", "--samples", "7"]))
assert sum(len(work) for page in memory.values() for work in page.values()) == 6, memory

data = json.loads((directory / "filtered-links.json").read_text())
provenance = data["provenance"]
provenance.update(
    measured_on=meta["measured_on"],
    parser_revision=meta["revision"],
    runner_revision=meta["revision"],
    machine=f'{meta["os"]} {meta["machine"]}, {meta["cpu_model"]}, pinned to logical CPU {cpu}, glibc {meta["glibc"]}',
    python="CPython " + meta["python"],
    build=f'Release wheel built from the source distribution with {meta["rust"]} and {build}',
    packages=packages,
    measurement_run=f'https://github.com/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{meta["run_id"]}',
)
for entry in data["measurements"]:
    mean, se = fixtures[entry["fixture"]][entry["parser"]]["parse + filtered links"].split(" ± ")
    entry.update(mean_us=float(mean), stderr_us=float(se))
json_file = directory / "filtered-links.json"
json_file.write_text(json.dumps(data, indent=2, ensure_ascii=False)+"\n")
(out / json_file.name).write_bytes(json_file.read_bytes())
subprocess.run(["uv","run","--script","benchmarks/plot.py"], check=True)
for name in ["filtered-links.png", "filtered-links-dark.png"]:
    (out / name).write_bytes((directory / name).read_bytes())

wcxb = measure("wcxb-log.txt", ["--wcxb", str(archive), "--samples", "10"])
agreement = {}
results = {}
samples = []
rejects = []
for line in wcxb.splitlines():
    if " rejected " in line and not line.startswith("|"):
        rejects.append(line)
    if not line.startswith("| "):
        continue
    parts = cells(line)
    if parts[0].isdecimal():
        samples.append(parts)
    elif len(parts)==4 and parts[1].isdecimal():
        agreement[parts[0]] = parts[1:]
    elif len(parts)==3 and " ± " in parts[1] and parts[0] != "Parser":
        results[parts[0]] = parts[1:]
matches = re.search(r"All parsers completed (\d+) pages\. Outputs were identical on (\d+)\.",wcxb)
assert matches and len(samples) == 50 and len(results) == 5 and len(agreement) == 5
for sample in range(1, 11):
    assert len({parser for idx, parser, *others in samples if int(idx)==sample}) == 5
csv_path = out / "wcxb-samples.csv"
with csv_path.open("w", newline="") as f:
    w = csv.writer(f, lineterminator="\n")
    w.writerow(["sample","parser","all_completed_us_per_page","identical_output_us_per_page"])
    w.writerows(samples)
ratios = []
for sample in range(1,11):
    same = {parser:float(identical) for idx, parser, _, identical in samples if int(idx)==sample}
    ratios.append(100*(1-same["astral-html"]/same["selectolax (Lexbor)"]))
mean = statistics.mean(ratios)
halfwidth = 2.2621571627982045 * statistics.stdev(ratios)/math.sqrt(len(ratios))
report = {
    "environment": meta, "fixtures": fixtures, "memory": memory,
    "wcxb": {
        "counts": list(map(int,matches.groups())), "agreement":agreement, "times":results,
        "rejections":rejects, "paired_reduction_ci":[mean,mean-halfwidth,mean+halfwidth],
    },
}
(out / "observations.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n")
for name in ["observations.json","wcxb-samples.csv","filtered-links.json","filtered-links.png","filtered-links-dark.png"]:
    raw = (out / name).read_bytes()
    print("MEASURE_SHA", name, hashlib.sha256(raw).hexdigest(),flush=True)
    payload = base64.b64encode(raw).decode()
    for index in range(0,len(payload),4000):
        print("MEASURE_DATA",name,index,payload[index:index+4000],flush=True)
