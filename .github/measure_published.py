from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

root = Path.cwd()
run = Path("benchmarks/run.py")
subprocess.run([sys.executable, "-I", run, "--check"], check=True)
print("WCXB archive bytes:", (Path(os.environ["RUNNER_TEMP"]) / "wcxb.tar.gz").stat().st_size, flush=True)
