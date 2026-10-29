"""Run the frozen runtime dependency self-check on its native build host."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


def main(executable: Path) -> int:
    result = subprocess.run(
        [str(executable), "--self-check"],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Frozen runtime self-check failed ({result.returncode}): {result.stderr.strip()}")
    try:
        report = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Frozen runtime returned invalid self-check output: {result.stdout[:500]}") from error
    if not report.get("ok"):
        raise RuntimeError(f"One or more packaged inference runtimes are unavailable: {report}")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python packaging/check_frozen_runtime.py PATH_TO_RUNTIME")
    try:
        raise SystemExit(main(Path(sys.argv[1])))
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        raise SystemExit(str(error)) from error
