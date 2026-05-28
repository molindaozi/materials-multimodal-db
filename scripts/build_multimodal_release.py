#!/usr/bin/env python3
"""Build an image-enabled or no-image multimodal materials literature release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


PAPER_FIELDS = [
    "paper_id",
    "doi",
    "title",
    "journal",
    "publisher",
    "year",
    "material_system",
    "alloy_name",
    "process",
    "inclusion_status",
    "article_license",
    "license_url",
    "open_access_status",
    "image_redistribution_status",
]

FIGURE_FIELDS = [
    "figure_index_id",
    "paper_id",
    "doi",
    "figure_key",
    "figure_label",
    "figure_number",
    "panel_label",
    "page_number",
    "source_type",
    "modality_candidates",
    "image_region_candidates",
    "evidence_terms",
    "page_image_path",
    "crop_image_path",
    "crop_method",
    "caption_hash_sha256",
    "caption_excerpt",
    "license_status",
    "redistribution_status",
    "review_status",
    "confidence",
    "notes",
]

IMAGE_MANIFEST_FIELDS = [
    "image_id",
    "figure_index_id",
    "paper_id",
    "doi",
    "figure_label",
    "panel_label",
    "image_role",
    "source_path",
    "release_path",
    "file_exists",
    "sha256",
    "crop_method",
    "license_status",
    "redistribution_status",
    "review_status",
]

FIGURE_LINK_FIELDS = [
    "link_id",
    "figure_index_id",
    "paper_id",
    "doi",
    "figure_key",
    "figure_label",
    "panel_label",
    "modality",
    "specimen_id",
    "tensile_id",
    "link_basis",
    "confidence",
    "review_status",
]

MULTIMODAL_FIELDS = [
    "multimodal_id",
    "paper_id",
    "doi",
    "figure_index_id",
    "figure_key",
    "figure_label",
    "panel_label",
    "modality",
    "specimen_id",
    "tensile_id",
    "material_system",
    "alloy_name",
    "process",
    "build_direction",
    "heat_treatment",
    "test_temperature_c",
    "direction",
    "yield_strength_mpa",
    "ultimate_tensile_strength_mpa",
    "elongation_pct",
    "crop_image_path",
    "source_locator",
    "confidence",
    "review_status",
]

REVIEW_FIELDS = [
    "review_id",
    "entity_type",
    "entity_id",
    "paper_id",
    "issue",
    "current_value",
    "recommended_action",
    "review_decision",
    "review_notes",
]

VALIDATION_FIELDS = ["check", "status", "detail"]
DICTIONARY_FIELDS = ["table", "field", "description"]

LOCAL_PATH_FIELDS = {
    "local_pdf_path",
    "local_text_path",
    "page_image_path",
    "crop_image_path",
    "panel_crop_path",
}


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def rel_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def path_from_project(raw: str, root: Path) -> Path | None:
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else root / path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def compact(text: str, max_len: int = 240) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:max_len]


def normalize_bool(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "accepted"}


def paper_lookup(rows: Sequence[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {row.get("paper_id", ""): row for row in rows if row.get("paper_id", "")}


def specimen_lookup(rows: Sequence[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {row.get("specimen_id", ""): row for row in rows if row.get("specimen_id", "")}


def tensile_lookup(rows: Sequence[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {row.get("tensile_id", ""): row for row in rows if row.get("tensile_id", "")}


def license_lookup(rows: Sequence[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {row.get("paper_id", ""): row for row in rows if row.get("paper_id", "")}


def clean_public_row(row: Dict[str, str], keep_images: bool) -> Dict[str, str]:
    output = {}
    for key, value in row.items():
        if key in {"local_pdf_path", "local_text_path"}:
            continue
        if not keep_images and key in {"page_image_path", "crop_image_path", "panel_crop_path"}:
            continue
        output[key] = value
    return output


def infer_license_status(license_row: Dict[str, str]) -> Tuple[str, str]:
    values = " ".join(str(v or "") for v in license_row.values()).lower()
    status = (
        license_row.get("image_redistribution_status")
        or license_row.get("scientific_data_image_use_status")
        or license_row.get("article_license")
        or "unknown"
    )
    if any(token in values for token in ["cc-by", "cc by", "public domain", "allowed"]):
        redistribution = "allowed"
    elif any(token in values for token in ["not allowed", "restricted", "permission required"]):
        redistribution = "restricted"
    else:
        redistribution = "uncertain"
    return status, redistribution


def infer_modality(caption: str, source_type: str) -> Tuple[str, str, str]:
    text = f"{caption} {source_type}".lower()
    hits: List[str] = []
    regions: List[str] = []
    evidence: List[str] = []
    rules = [
        ("EBSD_IPF", ["ipf", "inverse pole"]),
        ("EBSD_KAM", ["kam", "kernel average"]),
        ("EBSD", ["ebsd", "orientation map"]),
        ("SEM", ["sem", "scanning electron", "backscattered", "secondary electron"]),
        ("EDS", ["eds", "edx", "elemental map"]),
        ("TEM", ["tem", "transmission electron"]),
        ("OM_LM", ["optical micro", "light micro"]),
        ("fractography", ["fractograph", "fracture surface"]),
        ("mechanical_curve", ["stress-strain", "stress strain"]),
        ("mechanical_property_plot", ["yield strength", "ultimate tensile", "elongation"]),
        ("XRD", ["xrd", "diffraction"]),
        ("table", ["table"]),
        ("schematic", ["schematic"]),
    ]
    for label, needles in rules:
        if any(needle in text for needle in needles):
            hits.append(label)
            evidence.extend([needle for needle in needles if needle in text][:1])
    if any(token in text for token in ["fracture surface", "fractograph"]):
        regions.append("fracture_surface")
    if any(token in text for token in ["cross section", "cross-section"]):
        regions.append("cross_section")
    if any(token in text for token in ["powder", "feedstock"]):
        regions.append("feedstock_powder")
    if not regions and any(label in hits for label in ["SEM", "EBSD", "TEM", "OM_LM"]):
        regions.append("microstructure")
    if not hits:
        hits.append("unknown_non_microscopy")
    if not regions:
        regions.append("unknown")
    return "|".join(dict.fromkeys(hits)), "|".join(dict.fromkeys(regions)), "|".join(dict.fromkeys(evidence))


def build_papers(papers: Sequence[Dict[str, str]], licenses: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    rows = []
    for paper in papers:
        lic = licenses.get(paper.get("paper_id", ""), {})
        rows.append(
            {
                "paper_id": paper.get("paper_id", ""),
                "doi": paper.get("doi", ""),
                "title": paper.get("title", "") or paper.get("canonical_title", ""),
                "journal": paper.get("journal", ""),
                "publisher": paper.get("publisher", ""),
                "year": paper.get("year", ""),
                "material_system": paper.get("material_system", "") or paper.get("alloy_family", ""),
                "alloy_name": paper.get("alloy_name", "") or paper.get("material", ""),
                "process": paper.get("process", "") or paper.get("am_process", ""),
                "inclusion_status": paper.get("inclusion_status", ""),
                "article_license": lic.get("article_license", ""),
                "license_url": lic.get("license_url", ""),
                "open_access_status": lic.get("open_access_status", ""),
                "image_redistribution_status": lic.get("image_redistribution_status", "")
                or lic.get("scientific_data_image_use_status", ""),
            }
        )
    return rows


def build_tensile(tensile: Sequence[Dict[str, str]], specimens: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
    rows = []
    for row in tensile:
        output = dict(row)
        specimen = specimens.get(row.get("specimen_id", ""), {})
        output.setdefault("paper_id", specimen.get("paper_id", ""))
        if not output.get("paper_id"):
            output["paper_id"] = specimen.get("paper_id", "")
        output.setdefault("value_source", row.get("source_form", ""))
        output.setdefault("review_status", "pending" if row.get("confidence", "").lower() in {"low", "uncertain"} else "auto_curated")
        rows.append(output)
    return rows


def build_figure_index(
    figures: Sequence[Dict[str, str]],
    papers: Dict[str, Dict[str, str]],
    licenses: Dict[str, Dict[str, str]],
    keep_images: bool,
) -> List[Dict[str, str]]:
    rows = []
    for idx, figure in enumerate(figures, start=1):
        paper_id = figure.get("paper_id", "")
        paper = papers.get(paper_id, {})
        license_status, redistribution = infer_license_status(licenses.get(paper_id, {}))
        caption = figure.get("caption_text", "") or figure.get("caption", "")
        modality, region, evidence = infer_modality(caption, figure.get("source_type", ""))
        accepted_raw = figure.get("accepted", "")
        accepted = normalize_bool(accepted_raw) if accepted_raw else True
        review_status = "auto_curated"
        if not accepted or "unknown_non_microscopy" in modality or redistribution in {"uncertain", "restricted"}:
            review_status = "pending"
        rows.append(
            {
                "figure_index_id": f"FIGIDX{idx:06d}",
                "paper_id": paper_id,
                "doi": figure.get("doi", "") or paper.get("doi", ""),
                "figure_key": figure.get("figure_key", "") or f"{paper_id}:figure:{idx}",
                "figure_label": figure.get("figure_label", ""),
                "figure_number": figure.get("figure_number", ""),
                "panel_label": figure.get("panel_label", ""),
                "page_number": figure.get("page_number", ""),
                "source_type": figure.get("source_type", ""),
                "modality_candidates": modality,
                "image_region_candidates": region,
                "evidence_terms": evidence,
                "page_image_path": figure.get("page_image_path", "") if keep_images else "",
                "crop_image_path": figure.get("crop_image_path", "") if keep_images else "",
                "crop_method": figure.get("crop_method", "") if keep_images else "",
                "caption_hash_sha256": sha256_text(caption),
                "caption_excerpt": compact(caption),
                "license_status": license_status,
                "redistribution_status": redistribution,
                "review_status": review_status,
                "confidence": figure.get("confidence", ""),
                "notes": figure.get("notes", ""),
            }
        )
    return rows


def copy_release_image(source: Path, release_dir: Path, figure_index_id: str, role: str) -> str:
    suffix = source.suffix if source.suffix else ".png"
    target = release_dir / "images" / f"{figure_index_id}_{role}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return rel_path(target, release_dir)


def build_image_manifest(
    figures: Sequence[Dict[str, str]],
    root: Path,
    release_dir: Path,
    no_image: bool,
    copy_images: bool,
) -> List[Dict[str, str]]:
    if no_image:
        return []
    rows = []
    counter = 1
    for figure in figures:
        for role, field in [("page", "page_image_path"), ("crop", "crop_image_path")]:
            raw_path = figure.get(field, "")
            if not raw_path:
                continue
            source = path_from_project(raw_path, root)
            exists = bool(source and source.exists())
            release_path = ""
            checksum = ""
            if exists and source:
                checksum = sha256_file(source)
                if copy_images:
                    release_path = copy_release_image(source, release_dir, figure["figure_index_id"], role)
            rows.append(
                {
                    "image_id": f"IMG{counter:06d}",
                    "figure_index_id": figure.get("figure_index_id", ""),
                    "paper_id": figure.get("paper_id", ""),
                    "doi": figure.get("doi", ""),
                    "figure_label": figure.get("figure_label", ""),
                    "panel_label": figure.get("panel_label", ""),
                    "image_role": role,
                    "source_path": raw_path,
                    "release_path": release_path,
                    "file_exists": "yes" if exists else "no",
                    "sha256": checksum,
                    "crop_method": figure.get("crop_method", ""),
                    "license_status": figure.get("license_status", ""),
                    "redistribution_status": figure.get("redistribution_status", ""),
                    "review_status": figure.get("review_status", ""),
                }
            )
            counter += 1
    return rows


def build_links(
    figure_index: Sequence[Dict[str, str]],
    image_panels: Sequence[Dict[str, str]],
    image_links: Sequence[Dict[str, str]],
) -> List[Dict[str, str]]:
    figure_by_key = {(row.get("paper_id", ""), row.get("figure_key", "")): row for row in figure_index}
    panel_by_image = {row.get("image_id", ""): row for row in image_panels if row.get("image_id", "")}
    rows = []
    for idx, link in enumerate(image_links, start=1):
        panel = panel_by_image.get(link.get("image_id", ""), {})
        figure_key = panel.get("figure_key", "") or link.get("figure_key", "")
        fig = figure_by_key.get((link.get("paper_id", ""), figure_key), {})
        if not fig:
            continue
        confidence = link.get("confidence", "")
        rows.append(
            {
                "link_id": f"FSL{idx:06d}",
                "figure_index_id": fig.get("figure_index_id", ""),
                "paper_id": link.get("paper_id", ""),
                "doi": fig.get("doi", ""),
                "figure_key": figure_key,
                "figure_label": fig.get("figure_label", ""),
                "panel_label": panel.get("panel_label", "") or link.get("panel_label", ""),
                "modality": panel.get("modality", "") or fig.get("modality_candidates", ""),
                "specimen_id": link.get("specimen_id", ""),
                "tensile_id": link.get("tensile_id", ""),
                "link_basis": link.get("link_basis", "") or link.get("evidence", ""),
                "confidence": confidence,
                "review_status": "pending" if confidence.lower() in {"", "low", "uncertain"} else "auto_curated",
            }
        )
    return rows


def build_multimodal_rows(
    links: Sequence[Dict[str, str]],
    figures: Dict[str, Dict[str, str]],
    specimens: Dict[str, Dict[str, str]],
    tensile: Dict[str, Dict[str, str]],
) -> List[Dict[str, str]]:
    rows = []
    for idx, link in enumerate(links, start=1):
        specimen = specimens.get(link.get("specimen_id", ""), {})
        tensile_row = tensile.get(link.get("tensile_id", ""), {})
        fig = figures.get(link.get("figure_index_id", ""), {})
        rows.append(
            {
                "multimodal_id": f"MML{idx:06d}",
                "paper_id": link.get("paper_id", ""),
                "doi": link.get("doi", ""),
                "figure_index_id": link.get("figure_index_id", ""),
                "figure_key": link.get("figure_key", ""),
                "figure_label": link.get("figure_label", ""),
                "panel_label": link.get("panel_label", ""),
                "modality": link.get("modality", ""),
                "specimen_id": link.get("specimen_id", ""),
                "tensile_id": link.get("tensile_id", ""),
                "material_system": specimen.get("material_system", "") or specimen.get("alloy_family", ""),
                "alloy_name": specimen.get("alloy_name", "") or specimen.get("material", ""),
                "process": specimen.get("process", "") or specimen.get("am_process", ""),
                "build_direction": specimen.get("build_direction", ""),
                "heat_treatment": specimen.get("heat_treatment", ""),
                "test_temperature_c": tensile_row.get("test_temperature_c", ""),
                "direction": tensile_row.get("direction", ""),
                "yield_strength_mpa": tensile_row.get("yield_strength_mpa", ""),
                "ultimate_tensile_strength_mpa": tensile_row.get("ultimate_tensile_strength_mpa", ""),
                "elongation_pct": tensile_row.get("elongation_pct", ""),
                "crop_image_path": fig.get("crop_image_path", ""),
                "source_locator": tensile_row.get("source_locator", "") or specimen.get("source_locator", ""),
                "confidence": link.get("confidence", ""),
                "review_status": link.get("review_status", ""),
            }
        )
    return rows


def add_review(reviews: List[Dict[str, str]], entity_type: str, entity_id: str, paper_id: str, issue: str, current: str, action: str) -> None:
    reviews.append(
        {
            "review_id": f"REV{len(reviews) + 1:06d}",
            "entity_type": entity_type,
            "entity_id": entity_id,
            "paper_id": paper_id,
            "issue": issue,
            "current_value": current,
            "recommended_action": action,
            "review_decision": "",
            "review_notes": "",
        }
    )


def build_review_queue(
    figures: Sequence[Dict[str, str]],
    images: Sequence[Dict[str, str]],
    links: Sequence[Dict[str, str]],
    tensile_rows: Sequence[Dict[str, str]],
) -> List[Dict[str, str]]:
    reviews: List[Dict[str, str]] = []
    for fig in figures:
        if fig.get("redistribution_status") != "allowed":
            add_review(reviews, "figure", fig["figure_index_id"], fig["paper_id"], "image_license_uncertain", fig.get("redistribution_status", ""), "confirm license or use no-image release")
        if "unknown_non_microscopy" in fig.get("modality_candidates", ""):
            add_review(reviews, "figure", fig["figure_index_id"], fig["paper_id"], "modality_uncertain", fig.get("modality_candidates", ""), "classify figure modality manually")
    for image in images:
        if image.get("file_exists") == "no":
            add_review(reviews, "image", image["image_id"], image["paper_id"], "missing_image_file", image.get("source_path", ""), "restore image file or rebuild no-image release")
    for link in links:
        if link.get("review_status") == "pending":
            add_review(reviews, "figure_specimen_link", link["link_id"], link["paper_id"], "link_confidence_uncertain", link.get("confidence", ""), "verify figure-specimen-property mapping")
    for row in tensile_rows:
        if row.get("confidence", "").lower() in {"low", "uncertain"} or "figure" in row.get("value_source", "").lower():
            add_review(reviews, "tensile", row.get("tensile_id", ""), row.get("paper_id", ""), "tensile_value_needs_review", row.get("value_source", ""), "confirm source form and numeric value")
    return reviews


def dictionary_rows() -> List[Dict[str, str]]:
    rows = []
    table_fields = {
        "papers.csv": PAPER_FIELDS,
        "figure_index.csv": FIGURE_FIELDS,
        "image_manifest.csv": IMAGE_MANIFEST_FIELDS,
        "figure_specimen_links.csv": FIGURE_LINK_FIELDS,
        "multimodal_ml_database.csv": MULTIMODAL_FIELDS,
        "review_queue.csv": REVIEW_FIELDS,
    }
    for table, fields in table_fields.items():
        for field in fields:
            rows.append({"table": table, "field": field, "description": ""})
    return rows


def schema_json(table_fields: Dict[str, Sequence[str]]) -> Dict[str, object]:
    return {
        "tables": {
            table: {"fields": [{"name": field, "type": "string"} for field in fields]}
            for table, fields in table_fields.items()
        }
    }


def validation_rows(
    papers: Sequence[Dict[str, str]],
    figures: Sequence[Dict[str, str]],
    images: Sequence[Dict[str, str]],
    links: Sequence[Dict[str, str]],
    reviews: Sequence[Dict[str, str]],
    no_image: bool,
) -> List[Dict[str, str]]:
    rows = [
        {"check": "paper_count", "status": "ok" if papers else "warning", "detail": str(len(papers))},
        {"check": "figure_index_count", "status": "ok" if figures else "warning", "detail": str(len(figures))},
        {"check": "figure_link_count", "status": "ok" if links else "warning", "detail": str(len(links))},
        {"check": "review_queue_count", "status": "warning" if reviews else "ok", "detail": str(len(reviews))},
    ]
    missing_images = sum(1 for image in images if image.get("file_exists") == "no")
    rows.append({"check": "missing_image_files", "status": "warning" if missing_images else "ok", "detail": str(missing_images)})
    uncertain_license = sum(1 for fig in figures if fig.get("redistribution_status") != "allowed")
    rows.append({"check": "uncertain_image_licenses", "status": "warning" if uncertain_license else "ok", "detail": str(uncertain_license)})
    if no_image:
        leaked_paths = sum(1 for fig in figures if fig.get("page_image_path") or fig.get("crop_image_path"))
        rows.append({"check": "no_image_path_leakage", "status": "error" if leaked_paths else "ok", "detail": str(leaked_paths)})
    return rows


def write_readme(output_dir: Path, no_image: bool, counts: Dict[str, int]) -> None:
    lines = [
        "# Materials Literature Multimodal Database",
        "",
        "This release was generated from specimen-centric literature extraction outputs.",
        "",
        f"Release type: {'no-image' if no_image else 'image-enabled'}",
        "",
        "## Table Counts",
    ]
    for key, value in counts.items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "Review `review_queue.csv` and `validation_report.csv` before publication.",
            "Do not redistribute source PDFs or copyrighted image assets without permission.",
            "",
        ]
    )
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--db-v2-dir", type=Path, default=Path("data/db/v2"))
    parser.add_argument("--figure-inventory", type=Path, default=Path("data/metadata/figure_inventory.csv"))
    parser.add_argument("--source-license", type=Path, default=Path("data/metadata/source_license.csv"))
    parser.add_argument("--v3-dir", type=Path, default=Path("data/db/v3_image_ml"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/db/multimodal_release_v1"))
    parser.add_argument("--no-image", action="store_true", help="Remove image paths and do not copy image files.")
    parser.add_argument("--no-copy-images", action="store_true", help="Keep image paths but do not copy files into the release.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.project_root.resolve()
    db_v2 = args.db_v2_dir if args.db_v2_dir.is_absolute() else root / args.db_v2_dir
    v3_dir = args.v3_dir if args.v3_dir.is_absolute() else root / args.v3_dir
    figure_inventory = args.figure_inventory if args.figure_inventory.is_absolute() else root / args.figure_inventory
    source_license = args.source_license if args.source_license.is_absolute() else root / args.source_license
    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    papers_v2 = read_csv(db_v2 / "papers_v2.csv")
    specimens_v2 = read_csv(db_v2 / "specimens_v2.csv")
    tensile_v2 = read_csv(db_v2 / "tensile_records_v2.csv")
    micro_v2 = read_csv(db_v2 / "microstructure_records_v2.csv")
    figures_raw = read_csv(figure_inventory)
    licenses_raw = read_csv(source_license)
    image_panels = read_csv(v3_dir / "image_panels_v3.csv")
    image_links = read_csv(v3_dir / "image_specimen_links_v3.csv")

    licenses = license_lookup(licenses_raw)
    papers_by_id = paper_lookup(papers_v2)
    specimens_by_id = specimen_lookup(specimens_v2)

    papers = build_papers(papers_v2, licenses)
    specimens = [clean_public_row(row, keep_images=not args.no_image) for row in specimens_v2]
    micro = [clean_public_row(row, keep_images=not args.no_image) for row in micro_v2]
    tensile = build_tensile(tensile_v2, specimens_by_id)
    figure_index = build_figure_index(figures_raw, papers_by_id, licenses, keep_images=not args.no_image)
    image_manifest = build_image_manifest(
        figure_index,
        root=root,
        release_dir=output_dir,
        no_image=args.no_image,
        copy_images=not args.no_copy_images,
    )
    figure_links = build_links(figure_index, image_panels, image_links)
    multimodal = build_multimodal_rows(
        figure_links,
        {row["figure_index_id"]: row for row in figure_index},
        specimens_by_id,
        tensile_lookup(tensile),
    )
    reviews = build_review_queue(figure_index, image_manifest, figure_links, tensile)

    tensile_fields = list(tensile[0].keys()) if tensile else [
        "paper_id",
        "tensile_id",
        "specimen_id",
        "yield_strength_mpa",
        "ultimate_tensile_strength_mpa",
        "elongation_pct",
        "test_temperature_c",
        "direction",
        "value_source",
        "source_locator",
        "confidence",
        "review_status",
    ]
    specimen_fields = list(specimens[0].keys()) if specimens else ["specimen_id", "paper_id", "material_system", "alloy_name", "process"]
    micro_fields = list(micro[0].keys()) if micro else ["microstructure_id", "specimen_id", "microstructure_feature", "modality", "source_locator"]

    write_csv(output_dir / "papers.csv", PAPER_FIELDS, papers)
    write_csv(output_dir / "specimens.csv", specimen_fields, specimens)
    write_csv(output_dir / "tensile_properties.csv", tensile_fields, tensile)
    write_csv(output_dir / "microstructure_records.csv", micro_fields, micro)
    write_csv(output_dir / "figure_index.csv", FIGURE_FIELDS, figure_index)
    write_csv(output_dir / "image_manifest.csv", IMAGE_MANIFEST_FIELDS, image_manifest)
    write_csv(output_dir / "figure_specimen_links.csv", FIGURE_LINK_FIELDS, figure_links)
    write_csv(output_dir / "multimodal_ml_database.csv", MULTIMODAL_FIELDS, multimodal)
    write_csv(output_dir / "review_queue.csv", REVIEW_FIELDS, reviews)
    write_csv(output_dir / "data_dictionary.csv", DICTIONARY_FIELDS, dictionary_rows())
    validation = validation_rows(papers, figure_index, image_manifest, figure_links, reviews, args.no_image)
    write_csv(output_dir / "validation_report.csv", VALIDATION_FIELDS, validation)

    table_fields = {
        "papers.csv": PAPER_FIELDS,
        "specimens.csv": specimen_fields,
        "tensile_properties.csv": tensile_fields,
        "microstructure_records.csv": micro_fields,
        "figure_index.csv": FIGURE_FIELDS,
        "image_manifest.csv": IMAGE_MANIFEST_FIELDS,
        "figure_specimen_links.csv": FIGURE_LINK_FIELDS,
        "multimodal_ml_database.csv": MULTIMODAL_FIELDS,
        "review_queue.csv": REVIEW_FIELDS,
        "validation_report.csv": VALIDATION_FIELDS,
    }
    (output_dir / "schema.json").write_text(json.dumps(schema_json(table_fields), indent=2), encoding="utf-8")
    write_readme(
        output_dir,
        args.no_image,
        {
            "papers": len(papers),
            "specimens": len(specimens),
            "tensile_properties": len(tensile),
            "figure_index": len(figure_index),
            "image_manifest": len(image_manifest),
            "figure_specimen_links": len(figure_links),
            "multimodal_ml_database": len(multimodal),
            "review_queue": len(reviews),
        },
    )

    warning_count = Counter(row["status"] for row in validation)
    print(f"Release written to {output_dir}")
    print(f"papers: {len(papers)}")
    print(f"figures: {len(figure_index)}")
    print(f"links: {len(figure_links)}")
    print(f"review rows: {len(reviews)}")
    print(f"validation warnings: {warning_count.get('warning', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
