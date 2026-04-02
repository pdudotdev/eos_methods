#!/usr/bin/env python3
"""
Runs arista.py 100 times and averages the elapsed time per method.
"""

import subprocess
import sys
import re
from collections import defaultdict

RUNS = 100
SCRIPT = "arista.py"

totals = defaultdict(float)
counts = defaultdict(int)

try:
    for i in range(1, RUNS + 1):
        print(f"  Run {i}/{RUNS}...", end="\r")
        result = subprocess.run(
            ["python", SCRIPT],
            capture_output=True, text=True
        )
        for line in result.stdout.splitlines():
            m = re.match(r"\s+\d+\s+(.+?)\s{2,}([\d.]+)\s+(OK|FAIL)", line)
            if m:
                method, elapsed, status = m.group(1).strip(), float(m.group(2)), m.group(3)
                if status == "FAIL":
                    print(f"\n  ERROR: {method} failed on run {i}. Stopping.")
                    sys.exit(1)
                totals[method] += elapsed
                counts[method] += 1
except KeyboardInterrupt:
    print(f"\n\n  Interrupted at run {i}/{RUNS}.\n")

if not totals:
    sys.exit(1)

print(f"\n  Completed {i} runs\n")
print(f"  {'Rank':<6} {'Method':<30} {'Avg Time (s)':<14} {'Success Rate'}")
print(f"  {'-' * 65}")

averages = [(m, totals[m] / counts[m], counts[m]) for m in totals]
averages.sort(key=lambda x: x[1])

for rank, (method, avg, count) in enumerate(averages, 1):
    print(f"  {rank:<6} {method:<30} {avg:<14.4f} {count}/{RUNS}")
