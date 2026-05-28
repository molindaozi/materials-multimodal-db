#!/usr/bin/env python3
"""Apply visual/manual figure modality decisions to the no-image release tables."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Dict, Iterable, List


FIGURE_FIELDS_TO_UPDATE = [
    "modality_candidates",
    "image_region_candidates",
    "evidence_terms",
    "include_for_sem_ebsd_tensile_dataset",
    "curation_status",
    "curation_notes",
]


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[Dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def compact(value: str) -> str:
    return " ".join((value or "").split())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--decisions", required=True, help="CSV containing visual/manual decisions.")
    parser.add_argument(
        "--release-dir",
        default="data/db/scientific_data_no_image_v1",
        help="Release directory containing figure_index.csv and figure_modality_curation_review_queue.csv.",
    )
    parser.add_argument("--status", default="manual_reviewed")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    decisions_path = Path(args.decisions)
    if not decisions_path.is_absolute():
        decisions_path = root / decisions_path

    release_dir = Path(args.release_dir)
    if not release_dir.is_absolute():
        release_dir = root / release_dir
    figure_index_path = release_dir / "figure_index.csv"
    review_queue_path = release_dir / "figure_modality_curation_review_queue.csv"

    decisions = read_csv(decisions_path)
    usable = {
        row.get("figure_index_id", ""): row
        for row in decisions
        if row.get("figure_index_id", "")
        and compact(row.get("visual_review_status", "")).lower() in {"accepted", "resolved", "manual_reviewed"}
    }

    figure_rows = read_csv(figure_index_path)
    if not figure_rows:
        raise SystemExit(f"No figure rows found at {figure_index_path}")
    figure_fieldnames = list(figure_rows[0].keys())

    updated = 0
    for row in figure_rows:
        decision = usable.get(row.get("figure_index_id", ""))
        if not decision:
            continue
        mapping = {
            "modality_candidates": decision.get("final_modality_candidates", ""),
            "image_region_candidates": decision.get("final_image_region_candidates", ""),
            "evidence_terms": decision.get("final_evidence_terms", ""),
            "include_for_sem_ebsd_tensile_dataset": decision.get("final_include_for_sem_ebsd_tensile_dataset", ""),
            "curation_status": args.status,
            "curation_notes": decision.get("visual_review_notes", ""),
        }
        for field, value in mapping.items():
            if value:
                row[field] = value
        updated += 1

    write_csv(figure_index_path, figure_fieldnames, figure_rows)

    review_rows = read_csv(review_queue_path)
    if review_rows:
        review_fieldnames = list(review_rows[0].keys())
        resolved_ids = set(usable.keys())
        kept = [row for row in review_rows if row.get("figure_index_id", "") not in resolved_ids]
        write_csv(review_queue_path, review_fieldnames, kept)
    else:
        kept = []

    print(f"decisions accepted: {len(usable)}")
    print(f"figure_index rows updated: {updated}")
    print(f"remaining modality review rows: {len(kept)}")


if __name__ == "__main__":
    main()
