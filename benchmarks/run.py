"""独立进程测量合成数据规模；完整基准按需运行，不给 CI 设时间阈值。"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from benchmarks.synthetic import generate_case

PHASES = ("ingest", "repeat_ingest", "query", "quality")
REPO = Path(__file__).resolve().parents[1]


def peak_rss_mib() -> float | None:
    try:
        import resource
    except ImportError:
        return None
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 * 1024 if sys.platform == "darwin" else 1024)


def fingerprint(root: Path) -> dict[str, str]:
    from lifebase.core.hashing import sha256_file
    return {str(path.relative_to(root)): sha256_file(path)
            for path in root.rglob("*") if path.is_file()}


def worker(args: argparse.Namespace) -> dict[str, Any]:
    if args.worker == "generate":
        return asdict(generate_case(args.exports, args.messages, args.body_chars))
    from lifebase.sync.pipeline import ingest_file
    from lifebase.sync.quality import quality
    from lifebase.sync.registry import SourceRegistry
    from lifebase.vault.query import query

    before = fingerprint(args.data_dir) if args.worker == "repeat_ingest" else None
    started = perf_counter()
    if args.worker in {"ingest", "repeat_ingest"}:
        imports = [ingest_file(args.exports / f"{label}.zip", args.data_dir,
                               "chatgpt:synthetic-scale") for label in ("export-a", "export-b")]
        result: dict[str, Any] = {"created": [item.created for item in imports]}
    elif args.worker == "query":
        selected = SourceRegistry(args.data_dir).partitions()
        output = query(args.data_dir / "vault" / "silver", selected,
                       "SELECT count(DISTINCT record_id), count(*) FROM artifacts")
        result = {"messages": output.rows[0][0], "versions": output.rows[0][1]}
    else:
        result = asdict(quality(args.data_dir))
    elapsed = perf_counter() - started
    peak = peak_rss_mib()
    if before is not None and fingerprint(args.data_dir) != before:
        raise AssertionError("重复导入改变了持久化文件")
    return {"elapsed_seconds": elapsed, "peak_rss_mib": peak, "result": result}


def run_worker(phase: str, exports: Path, data_dir: Path, messages: int,
               body_chars: int) -> dict[str, Any]:
    completed = subprocess.run([
        sys.executable, "-m", "benchmarks.run", "--worker", phase,
        "--exports", str(exports), "--data-dir", str(data_dir), "--messages", str(messages),
        "--body-chars", str(body_chars),
    ], cwd=REPO, capture_output=True, text=True, check=True, timeout=180)
    return json.loads(completed.stdout)


def _summary(trials: list[dict[str, Any]]) -> dict[str, dict[str, float | None]]:
    return {phase: {
        "median_elapsed_seconds": statistics.median(trial[phase]["elapsed_seconds"] for trial in trials),
        "max_peak_rss_mib": max((trial[phase]["peak_rss_mib"] for trial in trials
                                 if trial[phase]["peak_rss_mib"] is not None), default=None),
    } for phase in PHASES}


def benchmark(sizes: list[int], repeats: int, body_chars: int) -> dict[str, Any]:
    if not sizes or any(size < 1 for size in sizes) or repeats < 1 or body_chars < 0:
        raise ValueError("sizes/repeats 必须为正数，body_chars 不能为负")
    source_files = sorted([*(REPO / "src" / "lifebase").rglob("*.py"),
                           *(REPO / "benchmarks").rglob("*.py")])
    digest = hashlib.sha256()
    for path in source_files:
        digest.update(str(path.relative_to(REPO)).encode())
        digest.update(path.read_bytes())
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                              text=True, check=True).stdout.strip()
    report: dict[str, Any] = {
        "measured_at_utc": datetime.now(UTC).isoformat(), "dataset": "synthetic only",
        "environment": {"python": platform.python_version(), "system": platform.system(),
                        "release": platform.release(), "machine": platform.machine(),
                        "cpu_count": os.cpu_count(), "duckdb": importlib.metadata.version("duckdb"),
                        "pyarrow": importlib.metadata.version("pyarrow")},
        "code": {"git_head": revision, "source_sha256": digest.hexdigest(),
                 "lock_sha256": hashlib.sha256((REPO / "uv.lock").read_bytes()).hexdigest()},
        "method": {"repeats": repeats, "phases": list(PHASES),
                   "elapsed": "operation wall time; Python/library startup excluded",
                   "memory": "absolute per-worker process peak RSS; startup included",
                   "rss_available": sys.platform != "win32", "cold_cache": False,
                   "temporary_data": "removed after run"}, "cases": [],
    }
    with tempfile.TemporaryDirectory(prefix="lifebase-scale-") as temporary:
        for size in sizes:
            case_root = Path(temporary) / str(size)
            exports = case_root / "exports"
            spec = run_worker("generate", exports, case_root / "unused", size, body_chars)
            trials = []
            for repeat in range(repeats):
                trial = {}
                for phase in PHASES:
                    data_dir = case_root / f"trial-{repeat}"
                    measurement = run_worker(phase, exports, data_dir, size, body_chars)
                    result = measurement["result"]
                    if phase in {"ingest", "repeat_ingest"}:
                        if result["created"] != [phase == "ingest"] * 2:
                            raise AssertionError("导入状态与基准阶段不一致")
                    elif phase == "query":
                        if result != {"messages": spec["logical_messages"], "versions": spec["message_versions"]}:
                            raise AssertionError("规模查询结果不符合合成输入预期")
                    else:
                        if (result["quality"]["messages"]["identities"] != spec["logical_messages"]
                                or result["quality"]["messages"]["versions"] != spec["message_versions"]
                                or result["quality"]["evidence"] != spec["evidence"]):
                            raise AssertionError("规模质量报告数量不符合预期")
                    trial[phase] = measurement
                trials.append(trial)
                print(json.dumps({"base_messages": size, "completed_repeat": repeat + 1}), flush=True)
            case = {"input": spec, "summary": _summary(trials), "trials": trials}
            report["cases"].append(case)
            print(json.dumps({"base_messages": size, "summary": case["summary"]}), flush=True)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="合成导出规模基准，所有数据在临时目录")
    parser.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 50000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--body-chars", type=int, default=256)
    parser.add_argument("--output", type=Path, default=REPO / "docs/benchmarks/quality-scale-baseline.json")
    parser.add_argument("--worker", choices=("generate", *PHASES), help=argparse.SUPPRESS)
    parser.add_argument("--exports", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--data-dir", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--messages", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args)))
    else:
        result = benchmark(args.sizes, args.repeats, args.body_chars)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(f"Baseline saved to {args.output}")


if __name__ == "__main__":
    main()
