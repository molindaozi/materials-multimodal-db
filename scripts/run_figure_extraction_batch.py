#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run pdffigures2-based figure extraction for ready_for_extraction papers."
    )
    parser.add_argument(
        "--project-root",
        default=Path(__file__).resolve().parents[1],
        help="Workspace root that contains data/db/v1/papers_v1.csv.",
    )
    parser.add_argument(
        "--papers-csv",
        default="data/db/v1/papers_v1.csv",
        help="papers_v1.csv path relative to project root, unless absolute.",
    )
    parser.add_argument(
        "--include-status",
        default="ready_for_extraction",
        help="Only process rows whose inclusion_status matches this value.",
    )
    parser.add_argument(
        "--max-papers",
        type=int,
        default=0,
        help="Optional cap on processed papers. 0 means no cap.",
    )
    parser.add_argument(
        "--pdffigures-jar",
        default="",
        help="Path to pdffigures2 JAR. Falls back to PDFFIGURES2_JAR env var.",
    )
    parser.add_argument(
        "--python-bin",
        default=sys.executable,
        help="Python interpreter used to invoke extract_pdf_figures_pdffigures2.py.",
    )
    parser.add_argument("--java-bin", default="java", help="Java binary for pdffigures2.")
    parser.add_argument("--page-render-dpi", type=int, default=144)
    parser.add_argument("--crop-render-dpi", type=int, default=300)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--include-tables", action="store_true")
    parser.add_argument(
        "--keep-going",
        action="store_true",
        help="Continue processing later papers after one extraction failure.",
    )
    return parser.parse_args()


def load_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    raw_bytes = csv_path.read_bytes()
    last_error: Exception | None = None
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "cp1252", "latin-1"):
        try:
            decoded = raw_bytes.decode(encoding)
            return list(csv.DictReader(decoded.splitlines()))
        except (UnicodeDecodeError, csv.Error) as exc:
            last_error = exc
    raise RuntimeError(f"Could not decode CSV: {csv_path}") from last_error


def resolve_workspace_path(project_root: Path, raw_path: str) -> Path:
    if not raw_path:
        raise ValueError("Missing path value.")
    normalized = raw_path.replace("\\", "/")
    candidate = Path(normalized).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root / candidate).resolve()


def run_single_paper(
    *,
    extraction_script: Path,
    python_bin: str,
    project_root: Path,
    pdffigures_jar: str,
    java_bin: str,
    pdf_path: Path,
    paper_id: str,
    page_render_dpi: int,
    crop_render_dpi: int,
    timeout_seconds: int,
    include_tables: bool,
) -> dict[str, Any]:
    command = [
        python_bin,
        str(extraction_script),
        "--project-root",
        str(project_root),
        "--pdf-path",
        str(pdf_path),
        "--paper-id",
        paper_id,
        "--pdffigures-jar",
        pdffigures_jar,
        "--java-bin",
        java_bin,
        "--page-render-dpi",
        str(page_render_dpi),
        "--crop-render-dpi",
        str(crop_render_dpi),
        "--timeout-seconds",
        str(timeout_seconds),
    ]
    if include_tables:
        command.append("--include-tables")

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Figure extraction failed.\n"
            f"Command: {' '.join(command)}\n"
            f"Return code: {completed.returncode}\n"
            f"STDOUT:\n{completed.stdout}\n"
            f"STDERR:\n{completed.stderr}"
        )

    stdout_text = completed.stdout.strip()
    if not stdout_text:
        raise RuntimeError(f"No JSON summary returned for {paper_id}.")
    return json.loads(stdout_text)


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).expanduser().resolve()

    papers_csv = Path(args.papers_csv)
    if not papers_csv.is_absolute():
        papers_csv = (project_root / papers_csv).resolve()
    if not papers_csv.exists():
        raise FileNotFoundError(f"papers CSV not found: {papers_csv}")

    pdffigures_jar = args.pdffigures_jar or os.environ.get("PDFFIGURES2_JAR", "")
    if not pdffigures_jar:
        raise ValueError("Missing --pdffigures-jar and PDFFIGURES2_JAR is not set.")
    pdffigures_jar = str(Path(pdffigures_jar).expanduser().resolve())
    if not Path(pdffigures_jar).exists():
        raise FileNotFoundError(f"pdffigures2 JAR not found: {pdffigures_jar}")

    extraction_script = Path(__file__).with_name("extract_pdf_figures_pdffigures2.py").resolve()
    if not extraction_script.exists():
        raise FileNotFoundError(f"Extraction script not found: {extraction_script}")

    rows = [
        row
        for row in load_csv_rows(papers_csv)
        if row.get("inclusion_status") == args.include_status and row.get("local_pdf_path")
    ]
    if args.max_papers > 0:
        rows = rows[: args.max_papers]

    results: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []

    for row in rows:
        paper_id = (row.get("paper_id") or "").strip()
        pdf_path = resolve_workspace_path(project_root, row["local_pdf_path"])
        if not pdf_path.exists():
            message = f"Missing PDF for {paper_id}: {pdf_path}"
            failures.append({"paper_id": paper_id, "error": message})
            if not args.keep_going:
                raise FileNotFoundError(message)
            print(message, file=sys.stderr)
            continue

        print(f"Extracting figures for {paper_id} from {pdf_path}", file=sys.stderr)
        try:
            result = run_single_paper(
                extraction_script=extraction_script,
                python_bin=args.python_bin,
                project_root=project_root,
                pdffigures_jar=pdffigures_jar,
                java_bin=args.java_bin,
                pdf_path=pdf_path,
                paper_id=paper_id,
                page_render_dpi=args.page_render_dpi,
                crop_render_dpi=args.crop_render_dpi,
                timeout_seconds=args.timeout_seconds,
                include_tables=args.include_tables,
            )
            results.append(result)
        except Exception as exc:  # noqa: BLE001
            failures.append({"paper_id": paper_id, "error": str(exc)})
            if not args.keep_going:
                raise
            print(f"Failed {paper_id}: {exc}", file=sys.stderr)

    print(
        json.dumps(
            {
                "papers_requested": len(rows),
                "papers_completed": len(results),
                "papers_failed": len(failures),
                "results": results,
                "failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
