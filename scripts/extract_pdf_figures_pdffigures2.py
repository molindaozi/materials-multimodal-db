#!/usr/bin/env python3
"""
Wrap a local pdffigures2 JAR and normalize outputs into the workspace figure manifest.

This script is designed as the Python replacement for the Windows-only PowerShell
proof of concept. It relies on:

1. pdffigures2 for scholarly figure / table detection and caption extraction
2. PyMuPDF for page rendering and high-resolution region cropping

Expected output per paper:
    data/figures/<paper_id>/
        pages/page_0001.png
        figure_crops/P001_F001.png
        metadata/figure_manifest.csv
        metadata/figure_manifest.json
        metadata/pdffigures2_raw.json
        metadata/summary.txt
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def project_relative(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def normalize_text(text: str) -> str:
    return " ".join((text or "").split())


def infer_paper_id(pdf_path: Path, paper_id: str | None) -> str:
    return paper_id.strip() if paper_id else pdf_path.stem


def run_pdffigures2(
    pdf_path: Path,
    jar_path: Path,
    raw_output_dir: Path,
    java_bin: str,
    figure_dpi: int,
    timeout_s: int,
) -> tuple[Path, str, str]:
    ensure_dir(raw_output_dir)

    output_prefix = str(raw_output_dir.resolve()) + os.sep
    command = [
        java_bin,
        "-Dsun.java2d.cmm=sun.java2d.cmm.kcms.KcmsServiceProvider",
        "-jar",
        str(jar_path.resolve()),
        str(pdf_path.resolve()),
        "-m",
        output_prefix,
        "-d",
        output_prefix,
        "--dpi",
        str(figure_dpi),
    ]

    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )

    if completed.returncode != 0:
        raise RuntimeError(
            "pdffigures2 failed.\n"
            f"Command: {' '.join(command)}\n"
            f"Return code: {completed.returncode}\n"
            f"STDOUT:\n{completed.stdout}\n"
            f"STDERR:\n{completed.stderr}"
        )

    expected_json = raw_output_dir / f"{pdf_path.stem}.json"
    if expected_json.exists():
        return expected_json, completed.stdout, completed.stderr

    json_candidates = sorted(raw_output_dir.glob("*.json"))
    if len(json_candidates) == 1:
        return json_candidates[0], completed.stdout, completed.stderr

    raise FileNotFoundError(
        "pdffigures2 finished without a uniquely identifiable JSON output.\n"
        f"Expected: {expected_json}\n"
        f"Found: {[str(path) for path in json_candidates]}"
    )


def load_pdffigures_records(json_path: Path) -> list[dict[str, Any]]:
    raw_bytes = json_path.read_bytes()
    data = None
    last_error: Exception | None = None

    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "cp1252", "latin-1"):
        try:
            decoded = raw_bytes.decode(encoding)
            data = json.loads(decoded)
            break
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            last_error = exc

    if data is None:
        raise RuntimeError(
            f"Could not decode pdffigures2 JSON with supported encodings: {json_path}"
        ) from last_error

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        if "figures" in data and isinstance(data["figures"], list):
            return [item for item in data["figures"] if isinstance(item, dict)]
        return [data]
    raise TypeError(f"Unexpected pdffigures2 JSON type: {type(data)!r}")


def render_page_images(doc: fitz.Document, pages_dir: Path, page_render_dpi: int) -> dict[int, dict[str, Any]]:
    ensure_dir(pages_dir)
    page_cache: dict[int, dict[str, Any]] = {}

    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        pix = page.get_pixmap(dpi=page_render_dpi, alpha=False)
        page_path = pages_dir / f"page_{page_index + 1:04d}.png"
        pix.save(page_path)
        page_cache[page_index] = {
            "page_number": page_index + 1,
            "page_path": page_path,
            "page_width_px": pix.width,
            "page_height_px": pix.height,
            "page_rect": page.rect,
            "page": page,
        }

    return page_cache


def boundary_to_rect(boundary: dict[str, Any] | None, page_rect: fitz.Rect) -> fitz.Rect | None:
    if not boundary:
        return None

    try:
        x1 = float(boundary["x1"])
        y1 = float(boundary["y1"])
        x2 = float(boundary["x2"])
        y2 = float(boundary["y2"])
    except (KeyError, TypeError, ValueError):
        return None

    rect = fitz.Rect(x1, y1, x2, y2)
    rect = rect & page_rect
    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        return None
    return rect


def rect_to_page_pixels(rect: fitz.Rect | None, page_render_dpi: int) -> dict[str, int | str]:
    if rect is None:
        return {
            "left": "",
            "top": "",
            "width": "",
            "height": "",
        }

    scale = page_render_dpi / 72.0
    left = int(round(rect.x0 * scale))
    top = int(round(rect.y0 * scale))
    width = int(round(rect.width * scale))
    height = int(round(rect.height * scale))

    return {
        "left": left,
        "top": top,
        "width": width,
        "height": height,
    }


def extract_neighboring_text(page: fitz.Page, caption_rect: fitz.Rect | None) -> tuple[str, str]:
    if caption_rect is None:
        return "", ""

    blocks = []
    for block in page.get_text("blocks"):
        if len(block) < 5:
            continue
        x0, y0, x1, y1, text = block[:5]
        cleaned = normalize_text(text)
        if not cleaned:
            continue
        rect = fitz.Rect(x0, y0, x1, y1)
        if rect.intersects(caption_rect):
            continue
        blocks.append((rect, cleaned))

    above_candidates = [item for item in blocks if item[0].y1 <= caption_rect.y0]
    below_candidates = [item for item in blocks if item[0].y0 >= caption_rect.y1]

    before = ""
    after = ""

    if above_candidates:
        best_above = max(above_candidates, key=lambda item: item[0].y1)
        before = best_above[1]

    if below_candidates:
        best_below = min(below_candidates, key=lambda item: item[0].y0)
        after = best_below[1]

    return before, after


def figure_label(source_type: str, figure_number: str) -> str:
    prefix = "Table" if source_type == "table" else "Fig."
    return f"{prefix} {figure_number}".strip()


def compute_confidence(source_type: str, region_rect: fitz.Rect | None, caption_rect: fitz.Rect | None) -> float:
    score = 0.50
    if source_type == "figure":
        score += 0.10
    if region_rect is not None:
        score += 0.20
    if caption_rect is not None:
        score += 0.15
    if region_rect is not None and region_rect.width > 40 and region_rect.height > 40:
        score += 0.05
    return round(min(score, 0.95), 2)


def copy_or_write_crop(
    page: fitz.Page,
    region_rect: fitz.Rect | None,
    crop_path: Path | None,
    crop_render_dpi: int,
) -> bool:
    if region_rect is None or crop_path is None:
        return False

    ensure_dir(crop_path.parent)
    pix = page.get_pixmap(clip=region_rect, dpi=crop_render_dpi, alpha=False)
    pix.save(crop_path)
    return True


def build_manifest_records(
    raw_records: list[dict[str, Any]],
    paper_id: str,
    doc: fitz.Document,
    page_cache: dict[int, dict[str, Any]],
    figure_crops_dir: Path,
    project_root: Path,
    page_render_dpi: int,
    crop_render_dpi: int,
    include_tables: bool,
) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    figure_counter = 1
    table_counter = 1

    for raw in raw_records:
        source_type = str(raw.get("figType", "Figure")).strip().lower()
        if source_type not in {"figure", "table"}:
            source_type = "figure"

        zero_based_page = int(raw.get("page", 0))
        if zero_based_page not in page_cache:
            continue

        page_info = page_cache[zero_based_page]
        page = page_info["page"]
        page_rect = page_info["page_rect"]

        region_rect = boundary_to_rect(raw.get("regionBoundary"), page_rect)
        caption_rect = boundary_to_rect(raw.get("captionBoundary"), page_rect)
        caption_text = normalize_text(str(raw.get("caption", "")))
        before_text, after_text = extract_neighboring_text(page, caption_rect)

        if source_type == "figure":
            figure_key = f"{paper_id}_F{figure_counter:03d}"
            figure_counter += 1
        else:
            figure_key = f"{paper_id}_T{table_counter:03d}"
            table_counter += 1

        number = str(raw.get("name", "")).strip()
        accepted = bool(region_rect) and (source_type == "figure" or include_tables)

        crop_path = None
        if accepted:
            crop_path = figure_crops_dir / f"{figure_key}.png"
            copy_or_write_crop(page, region_rect, crop_path, crop_render_dpi)

        crop_bbox = rect_to_page_pixels(region_rect, page_render_dpi)
        caption_bbox = rect_to_page_pixels(caption_rect, page_render_dpi)
        confidence = compute_confidence(source_type, region_rect, caption_rect)

        notes = [
            f"pdffigures2 page index converted from 0-based ({zero_based_page}) to 1-based ({page_info['page_number']}).",
            f"crop generated at {crop_render_dpi} dpi.",
        ]
        if source_type == "table" and not include_tables:
            notes.append("table detected but not accepted because --include-tables was not set.")
        if region_rect is None:
            notes.append("missing regionBoundary from pdffigures2 output.")
        if caption_rect is None:
            notes.append("missing captionBoundary from pdffigures2 output.")

        record = {
            "paper_id": paper_id,
            "figure_key": figure_key,
            "accepted": accepted,
            "source_type": source_type,
            "figure_label": figure_label(source_type, number),
            "figure_number": number,
            "panel_label": "",
            "page_number": page_info["page_number"],
            "page_width": page_info["page_width_px"],
            "page_height": page_info["page_height_px"],
            "caption_text": caption_text,
            "caption_context_before": before_text,
            "caption_context_after": after_text,
            "caption_left": caption_bbox["left"],
            "caption_top": caption_bbox["top"],
            "caption_width": caption_bbox["width"],
            "caption_height": caption_bbox["height"],
            "crop_left": crop_bbox["left"],
            "crop_top": crop_bbox["top"],
            "crop_width": crop_bbox["width"],
            "crop_height": crop_bbox["height"],
            "page_image_path": project_relative(page_info["page_path"], project_root),
            "crop_image_path": project_relative(crop_path, project_root) if crop_path and crop_path.exists() else "",
            "crop_method": "pdffigures2_region_boundary",
            "confidence": confidence,
            "notes": " ".join(notes),
        }
        manifest.append(record)

    return manifest


def write_manifest_csv(records: list[dict[str, Any]], csv_path: Path) -> None:
    ensure_dir(csv_path.parent)
    fieldnames = [
        "paper_id",
        "figure_key",
        "accepted",
        "source_type",
        "figure_label",
        "figure_number",
        "panel_label",
        "page_number",
        "page_width",
        "page_height",
        "caption_text",
        "caption_context_before",
        "caption_context_after",
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
        "notes",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def write_manifest_json(
    paper_id: str,
    pdf_path: Path,
    raw_json_path: Path,
    manifest_records: list[dict[str, Any]],
    json_path: Path,
    project_root: Path,
) -> None:
    payload = {
        "paper_id": paper_id,
        "pdf_path": project_relative(pdf_path, project_root),
        "pdffigures2_raw_json_path": project_relative(raw_json_path, project_root),
        "figure_count": len(manifest_records),
        "accepted_figure_count": sum(1 for row in manifest_records if row["accepted"]),
        "figures": manifest_records,
    }
    ensure_dir(json_path.parent)
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_summary(
    paper_id: str,
    pdf_path: Path,
    raw_json_path: Path,
    records: list[dict[str, Any]],
    summary_path: Path,
    project_root: Path,
) -> None:
    accepted_count = sum(1 for row in records if row["accepted"])
    lines = [
        f"paper_id: {paper_id}",
        f"pdf_path: {project_relative(pdf_path, project_root)}",
        f"pdffigures2_raw_json_path: {project_relative(raw_json_path, project_root)}",
        f"figure_records: {len(records)}",
        f"accepted_figure_records: {accepted_count}",
    ]
    ensure_dir(summary_path.parent)
    summary_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract figure crops from a scholarly PDF by wrapping pdffigures2 and normalizing the output."
    )
    parser.add_argument("--pdf-path", required=True, help="Path to the source PDF.")
    parser.add_argument("--paper-id", default="", help="Stable paper identifier. Defaults to the PDF stem.")
    parser.add_argument(
        "--pdffigures-jar",
        default=os.environ.get("PDFFIGURES2_JAR", ""),
        help="Path to the pdffigures2 assembled JAR. Can also be set via PDFFIGURES2_JAR.",
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Workspace root used to compute relative output paths.",
    )
    parser.add_argument(
        "--output-root",
        default="data/figures",
        help="Root output folder for extracted figure assets.",
    )
    parser.add_argument(
        "--java-bin",
        default=os.environ.get("JAVA_BIN", "java"),
        help="Java executable to use when invoking pdffigures2.",
    )
    parser.add_argument(
        "--page-render-dpi",
        type=int,
        default=144,
        help="DPI for full page snapshots used in the manifest.",
    )
    parser.add_argument(
        "--crop-render-dpi",
        type=int,
        default=300,
        help="DPI for saved figure crops.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=300,
        help="Timeout for the pdffigures2 subprocess.",
    )
    parser.add_argument(
        "--include-tables",
        action="store_true",
        help="Also accept and crop tables instead of figures only.",
    )
    parser.add_argument(
        "--keep-raw-dir",
        action="store_true",
        help="Keep the raw pdffigures2 output directory after manifest generation.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    pdf_path = Path(args.pdf_path).expanduser().resolve()
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if not args.pdffigures_jar:
        raise ValueError("Missing --pdffigures-jar. Set it explicitly or via PDFFIGURES2_JAR.")

    jar_path = Path(args.pdffigures_jar).expanduser().resolve()
    if not jar_path.exists():
        raise FileNotFoundError(f"pdffigures2 JAR not found: {jar_path}")

    project_root = Path(args.project_root).expanduser().resolve()
    output_root = (project_root / args.output_root).resolve() if not Path(args.output_root).is_absolute() else Path(args.output_root).resolve()
    paper_id = infer_paper_id(pdf_path, args.paper_id)

    paper_root = output_root / paper_id
    pages_dir = paper_root / "pages"
    crops_dir = paper_root / "figure_crops"
    metadata_dir = paper_root / "metadata"
    raw_dir = paper_root / "pdffigures2_raw"

    for path in (pages_dir, crops_dir, metadata_dir, raw_dir):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        ensure_dir(path)

    doc = fitz.open(pdf_path)
    page_cache = render_page_images(doc, pages_dir, args.page_render_dpi)

    raw_json_path, stdout_text, stderr_text = run_pdffigures2(
        pdf_path=pdf_path,
        jar_path=jar_path,
        raw_output_dir=raw_dir,
        java_bin=args.java_bin,
        figure_dpi=args.crop_render_dpi,
        timeout_s=args.timeout_seconds,
    )

    raw_copy_path = metadata_dir / "pdffigures2_raw.json"
    shutil.copy2(raw_json_path, raw_copy_path)

    raw_records = load_pdffigures_records(raw_json_path)
    manifest_records = build_manifest_records(
        raw_records=raw_records,
        paper_id=paper_id,
        doc=doc,
        page_cache=page_cache,
        figure_crops_dir=crops_dir,
        project_root=project_root,
        page_render_dpi=args.page_render_dpi,
        crop_render_dpi=args.crop_render_dpi,
        include_tables=args.include_tables,
    )

    csv_path = metadata_dir / "figure_manifest.csv"
    json_path = metadata_dir / "figure_manifest.json"
    summary_path = metadata_dir / "summary.txt"
    pdffigures_stdout_path = metadata_dir / "pdffigures2_stdout.txt"
    pdffigures_stderr_path = metadata_dir / "pdffigures2_stderr.txt"

    write_manifest_csv(manifest_records, csv_path)
    write_manifest_json(
        paper_id=paper_id,
        pdf_path=pdf_path,
        raw_json_path=raw_copy_path,
        manifest_records=manifest_records,
        json_path=json_path,
        project_root=project_root,
    )
    write_summary(
        paper_id=paper_id,
        pdf_path=pdf_path,
        raw_json_path=raw_copy_path,
        records=manifest_records,
        summary_path=summary_path,
        project_root=project_root,
    )
    pdffigures_stdout_path.write_text(stdout_text or "", encoding="utf-8")
    pdffigures_stderr_path.write_text(stderr_text or "", encoding="utf-8")

    page_count = doc.page_count

    if not args.keep_raw_dir:
        shutil.rmtree(raw_dir, ignore_errors=True)

    print(
        json.dumps(
            {
                "paper_id": paper_id,
                "pdf_path": str(pdf_path),
                "page_count": page_count,
                "figure_records": len(manifest_records),
                "accepted_figure_records": sum(1 for row in manifest_records if row["accepted"]),
                "csv_path": str(csv_path),
                "json_path": str(json_path),
                "summary_path": str(summary_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    doc.close()
    return 0


if __name__ == "__main__":
    main()
