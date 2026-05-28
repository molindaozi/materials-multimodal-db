#!/usr/bin/env python3
"""Create contact sheets for visual review of uncertain figure modality rows."""

from __future__ import annotations

import argparse
import csv
import textwrap
from pathlib import Path
from typing import Dict, Iterable, List

from PIL import Image, ImageDraw, ImageFont, ImageOps


MANIFEST_FIELDS = [
    "visual_batch_id",
    "sheet_path",
    "sheet_slot",
    "review_id",
    "figure_index_id",
    "paper_id",
    "doi",
    "figure_key",
    "figure_label",
    "source_type",
    "crop_image_path",
    "page_image_path",
    "current_modality_candidates",
    "current_image_region_candidates",
    "current_evidence_terms",
    "current_include_for_sem_ebsd_tensile_dataset",
    "issue",
    "caption_excerpt",
]

DECISION_FIELDS = [
    "review_id",
    "figure_index_id",
    "paper_id",
    "figure_key",
    "final_modality_candidates",
    "final_image_region_candidates",
    "final_evidence_terms",
    "final_include_for_sem_ebsd_tensile_dataset",
    "visual_review_status",
    "visual_review_notes",
]


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def compact(value: str) -> str:
    return " ".join((value or "").split())


def safe_font(size: int) -> ImageFont.ImageFont:
    for name in ("arial.ttf", "calibri.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def fit_thumbnail(path: Path, max_size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", max_size, "white")
        x = (max_size[0] - img.width) // 2
        y = (max_size[1] - img.height) // 2
        canvas.paste(img, (x, y))
        return canvas


def draw_wrapped(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont, width: int) -> int:
    x, y = xy
    line_height = int(font.size * 1.25) if hasattr(font, "size") else 16
    for line in textwrap.wrap(text, width=width):
        draw.text((x, y), line, fill=(20, 20, 20), font=font)
        y += line_height
    return y


def make_sheet(rows: List[Dict[str, str]], out_path: Path, cols: int, thumb_size: tuple[int, int]) -> None:
    label_h = 96
    gutter = 16
    rows_n = (len(rows) + cols - 1) // cols
    cell_w = thumb_size[0]
    cell_h = thumb_size[1] + label_h
    sheet_w = cols * cell_w + (cols + 1) * gutter
    sheet_h = rows_n * cell_h + (rows_n + 1) * gutter
    sheet = Image.new("RGB", (sheet_w, sheet_h), (245, 246, 248))
    draw = ImageDraw.Draw(sheet)
    font = safe_font(18)
    small = safe_font(15)
    for i, row in enumerate(rows):
        col = i % cols
        row_n = i // cols
        x = gutter + col * (cell_w + gutter)
        y = gutter + row_n * (cell_h + gutter)
        draw.rectangle((x, y, x + cell_w - 1, y + cell_h - 1), fill="white", outline=(190, 194, 200), width=2)
        image = fit_thumbnail(Path(row["crop_image_path"]), thumb_size)
        sheet.paste(image, (x, y))
        label_y = y + thumb_size[1] + 8
        title = f"{row['sheet_slot']}  {row['review_id']}  {row['paper_id']} {row['figure_label']}"
        draw.text((x + 8, label_y), title, fill=(0, 0, 0), font=font)
        label_y += 26
        draw_wrapped(draw, (x + 8, label_y), f"{row['figure_key']} | {row['current_modality_candidates']} | {row['issue']}", small, 52)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--release-dir",
        default="data/db/scientific_data_no_image_v1",
        help="Release directory containing figure_modality_curation_review_queue.csv.",
    )
    parser.add_argument(
        "--output-dir",
        default="data/metadata/figure_modality_visual_review_batches",
        help="Directory for generated contact sheets and manifests.",
    )
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument("--cols", type=int, default=3)
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    release_dir = Path(args.release_dir)
    if not release_dir.is_absolute():
        release_dir = root / release_dir
    review_path = release_dir / "figure_modality_curation_review_queue.csv"
    inventory_path = root / "data" / "metadata" / "figure_inventory.csv"
    out_dir = Path(args.output_dir)
    if not out_dir.is_absolute():
        out_dir = root / out_dir

    review_rows = read_csv(review_path)
    inventory_rows = read_csv(inventory_path)
    inventory_by_key = {row.get("figure_key", ""): row for row in inventory_rows}

    visual_rows: List[Dict[str, str]] = []
    text_only_rows: List[Dict[str, str]] = []
    for row in review_rows:
        inv = inventory_by_key.get(row.get("figure_key", ""), {})
        crop = inv.get("crop_image_path", "")
        page = inv.get("page_image_path", "")
        merged = {
            "review_id": row.get("review_id", ""),
            "figure_index_id": row.get("figure_index_id", ""),
            "paper_id": row.get("paper_id", ""),
            "doi": row.get("doi", ""),
            "figure_key": row.get("figure_key", ""),
            "figure_label": row.get("figure_label", ""),
            "source_type": row.get("source_type", ""),
            "crop_image_path": crop,
            "page_image_path": page,
            "current_modality_candidates": row.get("modality_candidates", ""),
            "current_image_region_candidates": row.get("image_region_candidates", ""),
            "current_evidence_terms": row.get("evidence_terms", ""),
            "current_include_for_sem_ebsd_tensile_dataset": row.get("include_for_sem_ebsd_tensile_dataset", ""),
            "issue": row.get("issue", ""),
            "caption_excerpt": compact(inv.get("caption_text", ""))[:500],
        }
        if crop and (root / crop).exists():
            visual_rows.append(merged)
        else:
            text_only_rows.append(merged)

    manifest_rows: List[Dict[str, str]] = []
    for batch_idx in range(0, len(visual_rows), args.batch_size):
        batch = visual_rows[batch_idx : batch_idx + args.batch_size]
        batch_id = f"VRB{batch_idx // args.batch_size + 1:03d}"
        try:
            sheet_rel = sheet_path = (out_dir / f"{batch_id}.png").resolve()
            sheet_rel = sheet_rel.relative_to(root.resolve())
        except ValueError:
            sheet_rel = out_dir / f"{batch_id}.png"
        sheet_path = root / sheet_rel
        sheet_rows = []
        for slot, row in enumerate(batch, start=1):
            out_row = dict(row)
            out_row["visual_batch_id"] = batch_id
            out_row["sheet_path"] = str(sheet_rel).replace("\\", "/")
            out_row["sheet_slot"] = str(slot)
            out_row["crop_image_path"] = str((root / row["crop_image_path"]).resolve())
            out_row["page_image_path"] = str((root / row["page_image_path"]).resolve()) if row["page_image_path"] else ""
            sheet_rows.append(out_row)
            manifest_rows.append(out_row)
        make_sheet(sheet_rows, sheet_path, args.cols, (520, 360))

    write_csv(out_dir / "visual_review_manifest.csv", MANIFEST_FIELDS, manifest_rows)
    write_csv(out_dir / "text_only_review_manifest.csv", MANIFEST_FIELDS, text_only_rows)
    write_csv(out_dir / "visual_review_decisions_template.csv", DECISION_FIELDS, [])
    print(f"visual rows with crops: {len(visual_rows)}")
    print(f"text-only rows without crops: {len(text_only_rows)}")
    print(f"contact sheets: {(len(visual_rows) + args.batch_size - 1) // args.batch_size}")
    print(f"output_dir: {out_dir}")


if __name__ == "__main__":
    main()
