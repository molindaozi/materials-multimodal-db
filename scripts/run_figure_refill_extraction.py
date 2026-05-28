#!/usr/bin/env python3
"""Targeted pdffigures2 refill extraction for caption-only review-queue papers."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


TARGET_SOURCE_TYPE = "figure_caption_text_fallback"


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def resolve_path(root: Path, value: str) -> Path:
    value = (value or "").strip()
    if not value:
        return Path()
    candidate = Path(value.replace("\\", "/")).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (root / candidate).resolve()


def parse_json_summary(stdout_text: str) -> dict[str, Any]:
    stdout_text = stdout_text or ""
    start = stdout_text.find("{")
    end = stdout_text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        return json.loads(stdout_text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def build_targets(
    queue_rows: list[dict[str, str]], papers_rows: list[dict[str, str]]
) -> tuple[list[dict[str, str]], Counter[str]]:
    queued_counts: Counter[str] = Counter(
        row.get("paper_id", "")
        for row in queue_rows
        if row.get("source_type", "") == TARGET_SOURCE_TYPE and row.get("paper_id", "")
    )
    paper_by_id = {row.get("paper_id", ""): row for row in papers_rows}
    targets: list[dict[str, str]] = []
    for paper_id in sorted(queued_counts):
        paper = dict(paper_by_id.get(paper_id, {}))
        if not paper:
            paper = {"paper_id": paper_id}
        paper["queued_caption_only_figures"] = str(queued_counts[paper_id])
        targets.append(paper)
    return targets, queued_counts


def run_extractor(
    *,
    python_bin: str,
    extraction_script: Path,
    project_root: Path,
    pdf_path: Path,
    paper_id: str,
    pdffigures_jar: Path,
    output_root: str,
    java_bin: str,
    timeout_seconds: int,
    page_render_dpi: int,
    crop_render_dpi: int,
    include_tables: bool,
) -> tuple[int, str, str, dict[str, Any]]:
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
        str(pdffigures_jar),
        "--output-root",
        output_root,
        "--java-bin",
        java_bin,
        "--timeout-seconds",
        str(timeout_seconds),
        "--page-render-dpi",
        str(page_render_dpi),
        "--crop-render-dpi",
        str(crop_render_dpi),
    ]
    if include_tables:
        command.append("--include-tables")

    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return (
        completed.returncode,
        completed.stdout or "",
        completed.stderr or "",
        parse_json_summary(completed.stdout or ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument(
        "--review-queue",
        type=Path,
        default=Path("data/db/scientific_data_no_image_v1/figure_modality_curation_review_queue.csv"),
    )
    parser.add_argument(
        "--papers-csv",
        type=Path,
        default=Path("data/metadata/add_papers_for_figure_extraction.csv"),
    )
    parser.add_argument(
        "--extraction-script",
        type=Path,
        default=Path("scripts/extract_pdf_figures_pdffigures2.py"),
    )
    parser.add_argument("--pdffigures-jar", type=Path, default=Path("tools/pdffigures2/pdffigures2.jar"))
    parser.add_argument("--output-root", default="data/figures_refill")
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--java-bin", default=os.environ.get("JAVA_BIN", "java"))
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--page-render-dpi", type=int, default=144)
    parser.add_argument("--crop-render-dpi", type=int, default=300)
    parser.add_argument("--include-tables", action="store_true")
    parser.add_argument(
        "--target-output",
        type=Path,
        default=Path("data/metadata/figure_refill_target_papers.csv"),
    )
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=Path("data/metadata/figure_refill_extraction_audit.csv"),
    )
    args = parser.parse_args()

    root = args.project_root.resolve()
    review_queue = args.review_queue if args.review_queue.is_absolute() else root / args.review_queue
    papers_csv = args.papers_csv if args.papers_csv.is_absolute() else root / args.papers_csv
    extraction_script = args.extraction_script if args.extraction_script.is_absolute() else root / args.extraction_script
    pdffigures_jar = args.pdffigures_jar if args.pdffigures_jar.is_absolute() else root / args.pdffigures_jar
    target_output = args.target_output if args.target_output.is_absolute() else root / args.target_output
    audit_output = args.audit_output if args.audit_output.is_absolute() else root / args.audit_output

    if not review_queue.exists():
        raise FileNotFoundError(f"Review queue not found: {review_queue}")
    if not papers_csv.exists():
        raise FileNotFoundError(f"Papers CSV not found: {papers_csv}")
    if not extraction_script.exists():
        raise FileNotFoundError(f"Extraction script not found: {extraction_script}")
    if not pdffigures_jar.exists():
        raise FileNotFoundError(f"pdffigures2 JAR not found: {pdffigures_jar}")

    queue_rows = read_csv(review_queue)
    papers_rows = read_csv(papers_csv)
    targets, queued_counts = build_targets(queue_rows, papers_rows)

    target_fields = list(papers_rows[0].keys()) if papers_rows else ["paper_id"]
    if "queued_caption_only_figures" not in target_fields:
        target_fields.append("queued_caption_only_figures")
    write_csv(target_output, target_fields, targets)

    audit_fields = [
        "paper_id",
        "doi",
        "local_pdf_path",
        "queued_caption_only_figures",
        "status",
        "figure_records",
        "accepted_figure_records",
        "csv_path",
        "json_path",
        "summary_path",
        "error",
    ]
    audit_rows: list[dict[str, Any]] = []

    for target in targets:
        paper_id = target.get("paper_id", "")
        pdf_path = resolve_path(root, target.get("local_pdf_path", ""))
        audit_row: dict[str, Any] = {
            "paper_id": paper_id,
            "doi": target.get("doi", ""),
            "local_pdf_path": target.get("local_pdf_path", ""),
            "queued_caption_only_figures": str(queued_counts.get(paper_id, 0)),
        }
        if not pdf_path or not pdf_path.exists():
            audit_row.update({"status": "missing_pdf", "error": str(pdf_path)})
            audit_rows.append(audit_row)
            continue

        print(f"Refill extracting {paper_id}: {pdf_path}", file=sys.stderr)
        returncode, stdout_text, stderr_text, summary = run_extractor(
            python_bin=args.python_bin,
            extraction_script=extraction_script,
            project_root=root,
            pdf_path=pdf_path,
            paper_id=paper_id,
            pdffigures_jar=pdffigures_jar,
            output_root=args.output_root,
            java_bin=args.java_bin,
            timeout_seconds=args.timeout_seconds,
            page_render_dpi=args.page_render_dpi,
            crop_render_dpi=args.crop_render_dpi,
            include_tables=args.include_tables,
        )
        if returncode == 0:
            audit_row.update(
                {
                    "status": "completed",
                    "figure_records": summary.get("figure_records", ""),
                    "accepted_figure_records": summary.get("accepted_figure_records", ""),
                    "csv_path": summary.get("csv_path", ""),
                    "json_path": summary.get("json_path", ""),
                    "summary_path": summary.get("summary_path", ""),
                    "error": "",
                }
            )
        else:
            audit_row.update(
                {
                    "status": "failed",
                    "error": (stderr_text or stdout_text).strip()[:4000],
                }
            )
        audit_rows.append(audit_row)

    write_csv(audit_output, audit_fields, audit_rows)

    status_counts = Counter(row.get("status", "") for row in audit_rows)
    print(
        json.dumps(
            {
                "target_papers": len(targets),
                "queued_caption_only_figures": sum(queued_counts.values()),
                "status_counts": dict(status_counts),
                "target_output": str(target_output),
                "audit_output": str(audit_output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
