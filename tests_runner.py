"""Standalone pytest runner used by the /health/run endpoint.

Runs in a separate subprocess so the live Flask app's globals
(SessionLocal binding, mocked workers, mocked LLM) are never touched.

Pytest writes progress and summary lines to stdout and buffers them in ways
that are hard to fully suppress. Instead of trying to silence stdout, we
write the JSON report to a path supplied by the caller (argv[1]) so the
parent process can read it back without parsing stdout at all.
"""
import json
import sys
import time

import pytest


class _Collector:
    def __init__(self):
        self.results = []
        self.summary = {
            "total": 0,
            "passed": 0,
            "failed": 0,
            "error": 0,
            "skipped": 0,
            "duration": 0.0,
        }

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            outcome = report.outcome
        elif report.failed and report.when in ("setup", "teardown"):
            outcome = "error"
        else:
            return

        node = report.nodeid
        module, _, name = node.rpartition("::")
        self.results.append({
            "nodeid": node,
            "module": module or node,
            "name": name or node,
            "outcome": outcome,
            "duration": round(float(report.duration or 0.0), 4),
            "longrepr": str(report.longrepr) if outcome != "passed" and report.longrepr else None,
        })
        self.summary["total"] += 1
        if outcome in self.summary:
            self.summary[outcome] += 1
        self.summary["duration"] = round(self.summary["duration"] + float(report.duration or 0.0), 4)


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: tests_runner.py <output_json_path> [pytest_args...]\n")
        return 2

    output_path = sys.argv[1]
    extra_args = list(sys.argv[2:])  # forwarded to pytest (e.g. -k filter)
    collector = _Collector()
    started = time.time()
    exit_code = pytest.main(
        ["-q", "--no-header", "--no-summary", "--disable-warnings", *extra_args, "tests/"],
        plugins=[collector],
    )
    elapsed = round(time.time() - started, 4)

    payload = {
        "exit_code": int(exit_code) if exit_code is not None else -1,
        "duration": elapsed,
        "summary": collector.summary,
        "tests": collector.results,
    }
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
