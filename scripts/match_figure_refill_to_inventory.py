#!/usr/bin/env python3
"""Match refill pdffigures2 crops back to caption-only figure inventory rows."""

from __future__ import annotations

import argparse
import csv
import difflib
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


TARGET_SOURCE_TYPE = "figure_caption_text_fallback"
MANIFEST_NAME = "figure_manifest.csv"
UPDATE_FIELDS = [
    "accepted",
    "source_type",
    "page_number",
    "page_width",
    "page_height",
    "caption_left",
    "caption_top",
    "caption_width",
    "caption_height",
    "crop_left",
    "crop_top",
    "crop_width",
    "crop_height",
    "page_image_path",
    "crop_image_path",
    "crop_method",
    "confidence",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def compact(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (value or "").lower())


def text_similarity(a: str, b: str) -> float:
    a = compact(a).lower()
    b = compact(b).lower()
    if not a or not b:
        return 0.0
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    aw = set(words(a))
    bw = set(words(b))
    jac = len(aw & bw) / len(aw | bw) if aw and bw else 0.0
    return round((seq * 0.65) + (jac * 0.35), 4)


def normalize_label(raw_label: str, caption: str = "") -> str:
    text = f"{raw_label} {caption}".lower()
    text = text.replace("figure", "fig")
    match = re.search(r"\b(fig|table)\.?\s*([a-z]?\d+[a-z0-9]*(?:[.\-]\d+)?)", text)
    if not match:
        return ""
    prefix = "T" if match.group(1) == "table" else "F"
    number = match.group(2).strip(". ")
    return f"{prefix}:{number}"


def is_true(value: str) -> bool:
    return (value or "").strip().lower() in {"true", "1", "yes", "y"}


def append_note(original: str, note: str) -> str:
    original = compact(original)
    if not original:
        return note
    if note in original:
        return original
    return f"{original} {note}"


def load_refill_manifest_rows(root: Path, refill_root: Path, paper_ids: Iterable[str]) -> dict[str, list[dict[str, str]]]:
    by_paper: dict[str, list[dict[str, str]]] = {}
    for paper_id in paper_ids:
        manifest = refill_root / paper_id / "metadata" / MANIFEST_NAME
        rows = read_csv(manifest)
        valid_rows = []
        for row in rows:
            crop = row.get("crop_image_path", "")
            if row.get("paper_id", "") != paper_id:
                row["paper_id"] = paper_id
            if not is_true(row.get("accepted", "")):
                continue
            if not crop or not (root / crop).exists():
                continue
            row["_normalized_label"] = normalize_label(row.get("figure_label", ""), row.get("caption_text", ""))
            valid_rows.append(row)
        by_paper[paper_id] = valid_rows
    return by_paper


def choose_match(
    queue_row: dict[str, str],
    inventory_row: dict[str, str],
    manifest_rows: list[dict[str, str]],
    min_similarity: float,
) -> tuple[str, dict[str, str] | None, float, str]:
    target_label = normalize_label(queue_row.get("figure_label", ""), inventory_row.get("caption_text", ""))
    if not target_label:
        return "no_target_label", None, 0.0, ""
    candidates = [row for row in manifest_rows if row.get("_normalized_label", "") == target_label]
    if not candidates:
        return "no_label_match", None, 0.0, ""

    scored = [
        (text_similarity(inventory_row.get("caption_text", ""), row.get("caption_text", "")), row)
        for row in candidates
    ]
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_row = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0

    if best_score >= min_similarity and best_score - second_score >= 0.02:
        return "matched_high_confidence", best_row, best_score, target_label
    if len(candidates) == 1 and best_score >= max(0.35, min_similarity - 0.15):
        return "matched_label_single_candidate", best_row, best_score, target_label
    return "low_confidence_label_match", best_row, best_score, target_label


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument(
        "--review-queue",
        type=Path,
        default=Path("data/db/scientific_data_no_image_v1/figure_modality_curation_review_queue.csv"),
    )
    parser.add_argument("--figure-inventory", type=Path, default=Path("data/metadata/figure_inventory.csv"))
    parser.add_argument("--refill-root", type=Path, default=Path("data/figures_refill"))
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=Path("data/metadata/figure_refill_match_audit.csv"),
    )
    parser.add_argument("--min-similarity", type=float, default=0.50)
    args = parser.parse_args()

    root = args.project_root.resolve()
    review_queue = args.review_queue if args.review_queue.is_absolute() else root / args.review_queue
    inventory_path = args.figure_inventory if args.figure_inventory.is_absolute() else root / args.figure_inventory
    refill_root = args.refill_root if args.refill_root.is_absolute() else root / args.refill_root
    audit_output = args.audit_output if args.audit_output.is_absolute() else root / args.audit_output

    queue_rows = [
        row for row in read_csv(review_queue) if row.get("source_type", "") == TARGET_SOURCE_TYPE
    ]
    inventory_rows = read_csv(inventory_path)
    if not inventory_rows:
        raise SystemExit(f"No inventory rows found at {inventory_path}")
    fieldnames = list(inventory_rows[0].keys())
    inventory_by_key = {(row.get("paper_id", ""), row.get("figure_key", "")): row for row in inventory_rows}
    paper_ids = sorted({row.get("paper_id", "") for row in queue_rows if row.get("paper_id", "")})
    manifests_by_paper = load_refill_manifest_rows(root, refill_root, paper_ids)

    audit_fields = [
        "paper_id",
        "figure_key",
        "figure_label",
        "target_label",
        "match_status",
        "caption_similarity",
        "matched_refill_figure_key",
        "matched_refill_figure_label",
        "matched_crop_image_path",
        "matched_page_number",
        "caption_excerpt",
        "matched_caption_excerpt",
        "notes",
    ]
    audit_rows: list[dict[str, str]] = []
    status_counts: Counter[str] = Counter()
    matched_keys: set[tuple[str, str]] = set()
    manifest_use_counts: Counter[tuple[str, str]] = Counter()

    queue_by_paper = defaultdict(int)
    for row in queue_rows:
        queue_by_paper[row.get("paper_id", "")] += 1

    for queue_row in queue_rows:
        paper_id = queue_row.get("paper_id", "")
        figure_key = queue_row.get("figure_key", "")
        inv = inventory_by_key.get((paper_id, figure_key))
        if not inv:
            status = "missing_inventory_row"
            match = None
            score = 0.0
            target_label = normalize_label(queue_row.get("figure_label", ""))
        elif not manifests_by_paper.get(paper_id):
            status = "missing_or_empty_manifest"
            match = None
            score = 0.0
            target_label = normalize_label(queue_row.get("figure_label", ""), inv.get("caption_text", ""))
        else:
            status, match, score, target_label = choose_match(
                queue_row, inv, manifests_by_paper.get(paper_id, []), args.min_similarity
            )

        applied = status in {"matched_high_confidence", "matched_label_single_candidate"} and match is not None and inv is not None
        if applied:
            source_key = match.get("figure_key", "")
            manifest_identity = (paper_id, source_key)
            manifest_use_counts[manifest_identity] += 1
            for field in UPDATE_FIELDS:
                if field == "accepted":
                    inv[field] = "True"
                elif field == "source_type":
                    inv[field] = "figure_refill_pdffigures2_matched"
                elif field == "crop_method":
                    inv[field] = "refill_pdffigures2_caption_match"
                elif field == "confidence":
                    try:
                        inv[field] = f"{min(float(match.get(field, '0') or 0) + 0.03, 0.98):.2f}"
                    except ValueError:
                        inv[field] = match.get(field, "")
                else:
                    inv[field] = match.get(field, "")
            if not compact(inv.get("caption_text", "")):
                inv["caption_text"] = match.get("caption_text", "")
            if not compact(inv.get("caption_context_before", "")):
                inv["caption_context_before"] = match.get("caption_context_before", "")
            if not compact(inv.get("caption_context_after", "")):
                inv["caption_context_after"] = match.get("caption_context_after", "")
            inv["notes"] = append_note(
                inv.get("notes", ""),
                (
                    "Matched to refill pdffigures2 crop "
                    f"{source_key} by paper_id+figure_label+caption_similarity={score:.3f}; "
                    "fallback figure_key preserved."
                ),
            )
            matched_keys.add((paper_id, figure_key))

        status_counts[status] += 1
        audit_rows.append(
            {
                "paper_id": paper_id,
                "figure_key": figure_key,
                "figure_label": queue_row.get("figure_label", ""),
                "target_label": target_label,
                "match_status": status,
                "caption_similarity": f"{score:.4f}",
                "matched_refill_figure_key": match.get("figure_key", "") if match else "",
                "matched_refill_figure_label": match.get("figure_label", "") if match else "",
                "matched_crop_image_path": match.get("crop_image_path", "") if match else "",
                "matched_page_number": match.get("page_number", "") if match else "",
                "caption_excerpt": compact((inv or {}).get("caption_text", ""))[:240],
                "matched_caption_excerpt": compact(match.get("caption_text", ""))[:240] if match else "",
                "notes": "inventory updated" if applied else "",
            }
        )

    write_csv(inventory_path, fieldnames, inventory_rows)
    write_csv(audit_output, audit_fields, audit_rows)

    duplicate_manifest_uses = sum(1 for count in manifest_use_counts.values() if count > 1)
    print(f"queue rows considered: {len(queue_rows)}")
    print(f"target papers: {len(queue_by_paper)}")
    print(f"inventory rows updated: {len(matched_keys)}")
    print(f"duplicate refill crop uses: {duplicate_manifest_uses}")
    for status, count in status_counts.most_common():
        print(f"{status}: {count}")
    print(f"audit_output: {audit_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
