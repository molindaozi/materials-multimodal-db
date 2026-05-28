#!/usr/bin/env python3
"""Build a no-image Scientific Data style release database from v2/v3 outputs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


PAPER_FIELDS = [
    "paper_id",
    "doi",
    "title",
    "journal",
    "publisher",
    "year",
    "alloy_name",
    "am_process",
    "inclusion_status",
    "article_license",
    "license_url",
    "open_access_status",
    "scientific_data_image_use_status",
    "notes",
]

FIGURE_INDEX_FIELDS = [
    "figure_index_id",
    "paper_id",
    "doi",
    "figure_key",
    "figure_label",
    "figure_number",
    "panel_labels_detected",
    "page_number",
    "source_type",
    "modality_candidates",
    "image_region_candidates",
    "evidence_terms",
    "include_for_sem_ebsd_tensile_dataset",
    "curation_status",
    "curation_notes",
    "caption_hash_sha256",
    "caption_excerpt",
    "license_status",
    "article_url",
    "review_status",
    "notes",
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
    "notes",
]

TENSILE_EXTRA_FIELDS = [
    "paper_id",
    "mean_or_single_value",
    "digitized_or_table_value",
    "dispersion_reported_in_source",
    "dispersion_type",
    "replicate_count_reported",
    "value_form_review_status",
    "value_form_basis",
]

TENSILE_REVIEW_FIELDS = [
    "review_id",
    "paper_id",
    "tensile_id",
    "specimen_id",
    "field_name",
    "current_value",
    "issue",
    "evidence_text",
    "review_status",
    "review_notes",
]

FIGURE_LINK_REVIEW_FIELDS = [
    "review_id",
    "paper_id",
    "figure_index_id",
    "link_id",
    "specimen_id",
    "tensile_id",
    "issue",
    "candidate_value",
    "review_status",
    "review_notes",
]

PAPER_EXTRACTION_REVIEW_FIELDS = [
    "review_id",
    "paper_id",
    "doi",
    "title",
    "issue",
    "figure_index_count",
    "microscopy_candidate_count",
    "specimen_count",
    "tensile_record_count",
    "review_status",
    "review_notes",
]

FIGURE_MODALITY_REVIEW_FIELDS = [
    "review_id",
    "figure_index_id",
    "paper_id",
    "doi",
    "figure_key",
    "figure_label",
    "source_type",
    "modality_candidates",
    "image_region_candidates",
    "evidence_terms",
    "include_for_sem_ebsd_tensile_dataset",
    "issue",
    "caption_hash_sha256",
    "review_status",
    "review_notes",
]

VALIDATION_FIELDS = ["check_id", "check_name", "status", "count", "details"]
DICTIONARY_FIELDS = ["table", "field", "type", "description", "allowed_values"]

PRESERVE_CURATION_STATUSES = {"manual_reviewed", "manual_preserved"}
FINAL_FIGURE_CURATION_FIELDS = [
    "modality_candidates",
    "image_region_candidates",
    "evidence_terms",
    "include_for_sem_ebsd_tensile_dataset",
    "curation_status",
    "curation_notes",
]
TARGET_MICROSCOPY_MODALITIES = {"SEM", "EBSD", "EBSD_IPF", "EBSD_KAM", "EBSD_GB", "EDS", "TEM", "OM_LM", "CT"}
NON_TARGET_MODALITIES = {
    "XRD",
    "mechanical_curve",
    "mechanical_property_plot",
    "hardness_plot",
    "porosity_plot",
    "thermodynamic_calculation",
    "precipitation_model_plot",
    "phase_diagram",
    "strengthening_model_plot",
    "process_parameter_plot",
    "macro_photo",
    "texture_plot",
    "thermal_analysis_plot",
    "microstructure_metric_plot",
    "composition_plot",
    "DIC_strain_map",
    "surface_topography_map",
    "corrosion_curve",
    "model_prediction_plot",
    "review_summary_plot",
    "schematic",
    "table",
}

LOCAL_PATH_FIELDS = {
    "local_pdf_path",
    "local_supp_path",
    "local_text_path",
    "page_image_path",
    "crop_image_path",
    "panel_crop_path",
    "original_crop_path",
}


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: Sequence[str], rows: Sequence[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def norm_text(text: str) -> str:
    return compact((text or "").lower())


def short_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def make_excerpt(text: str, max_chars: int) -> str:
    text = compact(text)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def scrub_public_text(text: str) -> str:
    text = text or ""
    text = re.sub(r"data[/\\](?:raw_pdfs|figures|text)[^,;\r\n]*", "local source path removed", text)
    text = re.sub(r"(?<![A-Za-z])[A-Za-z]:[/\\][^,;\r\n]*", "local source path removed", text)
    return compact(text)


def paper_doi_url(doi: str) -> str:
    return f"https://doi.org/{doi}" if doi else ""


def license_by_paper(rows: Sequence[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {row.get("paper_id", ""): row for row in rows}


def paper_by_id(rows: Sequence[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
    return {row.get("paper_id", ""): row for row in rows}


def specimen_to_paper(specimens: Sequence[Dict[str, str]]) -> Dict[str, str]:
    return {row.get("specimen_id", ""): row.get("paper_id", "") for row in specimens}


def figure_text(row: Dict[str, str]) -> str:
    return compact(
        " ".join(
            [
                row.get("caption_text", ""),
                row.get("caption_context_before", ""),
                row.get("caption_context_after", ""),
            ]
        )
    )


def detect_modalities(text: str) -> List[str]:
    low = norm_text(text)
    modalities: List[str] = []
    if re.search(r"\bebsd\b|electron backscatter|back-scatter diffraction", low):
        modalities.append("EBSD")
    if re.search(r"\bipf\b|inverse pole figure", low):
        modalities.append("EBSD_IPF")
    if re.search(r"\bkam\b|kernel average misorientation", low):
        modalities.append("EBSD_KAM")
    if re.search(r"grain boundar|lagb|hagb|\bgb\b", low):
        modalities.append("EBSD_GB")
    if re.search(r"phase map|phase distribution", low):
        modalities.append("EBSD_phase")
    if re.search(r"\bsem\b|scanning electron|secondary electron|\bbse\b|backscattered electron|\bfesem\b", low):
        modalities.append("SEM")
    if re.search(r"\btem\b|transmission electron", low):
        modalities.append("TEM")
    if re.search(r"\beds\b|energy dispersive|edx", low):
        modalities.append("EDS")
    if re.search(r"fractograph|fracture surface|fractured surface|broken area", low):
        modalities.append("fractography")
    output: List[str] = []
    for item in modalities:
        if item not in output:
            output.append(item)
    return output


def detect_regions(text: str) -> List[str]:
    low = norm_text(text)
    regions: List[str] = []
    if re.search(r"powder|particle morphology|feedstock", low):
        regions.append("feedstock_powder")
    if re.search(r"fractograph|fracture surface|fractured surface|broken area|rupture", low):
        regions.append("fracture_surface")
    if re.search(r"cross[- ]section|longitudinal section|transverse section|sectional", low):
        regions.append("cross_section")
    if re.search(r"top surface|surface morphology|melt pool|molten pool", low):
        regions.append("surface_or_melt_pool")
    if re.search(r"microstructure|grain|cellular|dendrit|laves|carbide|precipitate", low):
        regions.append("microstructure")
    return regions or ["unknown"]


def evidence_terms(text: str) -> str:
    low = norm_text(text)
    terms = []
    for pattern, label in [
        (r"\bsem\b|scanning electron|\bfesem\b", "SEM"),
        (r"\bebsd\b", "EBSD"),
        (r"\bipf\b", "IPF"),
        (r"\bkam\b", "KAM"),
        (r"\beds\b|edx|energy dispersive", "EDS"),
        (r"\btem\b", "TEM"),
        (r"fracture|fractograph|rupture", "fracture"),
        (r"grain", "grain"),
        (r"melt pool", "melt_pool"),
        (r"porosity|pore", "porosity"),
        (r"carbide|precipitate|laves", "phase_precipitate"),
    ]:
        if re.search(pattern, low):
            terms.append(label)
    return "|".join(terms)


def append_unique(values: List[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def pipe(values: Sequence[str]) -> str:
    output: List[str] = []
    for value in values:
        append_unique(output, value)
    return "|".join(output)


def caption_only_text(row: Dict[str, str]) -> str:
    return compact(row.get("caption_text", ""))


def curated_regions(caption: str, modalities: Sequence[str], include_value: str) -> List[str]:
    if include_value == "no":
        return ["not_applicable"]
    low = norm_text(caption)
    regions: List[str] = []
    if re.search(r"powder|feedstock|particle morphology|powder morphology", low):
        append_unique(regions, "feedstock_powder")
    if re.search(r"fractograph|fracture surface|fractured surface|rupture area|crack initiation|crack growth", low):
        append_unique(regions, "fracture_surface")
    if re.search(r"cross[- ]section|cross section|longitudinal section|transverse section|gauge length|sectional", low):
        append_unique(regions, "cross_section")
    if re.search(r"top surface|downskin|upskin|surface morphology|melt pool|molten pool|single track|track morphology", low):
        append_unique(regions, "surface_or_melt_pool")
    if re.search(r"microstructure|micrograph|grain|cellular|dendrit|laves|carbide|precipitate|inclusion|oxide|segregation", low):
        append_unique(regions, "microstructure")
    if "fractography" in modalities and "fracture_surface" not in regions:
        append_unique(regions, "fracture_surface")
    return regions or ["unknown"]


def curated_classification(figure: Dict[str, str]) -> Dict[str, str]:
    source_type = norm_text(figure.get("source_type", ""))
    caption = caption_only_text(figure)
    low = norm_text(caption)
    modalities: List[str] = []
    evidence: List[str] = []
    notes: List[str] = ["Caption-only final classification written directly to figure_index.csv."]

    if source_type.startswith("table") or re.match(r"^\s*table\b", low):
        return {
            "modality_candidates": "table",
            "image_region_candidates": "not_applicable",
            "evidence_terms": "table",
            "include_for_sem_ebsd_tensile_dataset": "no",
            "curation_status": "auto_curated",
            "curation_notes": "Table record; excluded from SEM/EBSD image-property dataset.",
        }

    if re.search(r"\bebsd\b|electron backscatter|back-scatter diffraction", low):
        append_unique(modalities, "EBSD")
        append_unique(evidence, "EBSD")
    if re.search(r"\bipf\b|inverse pole figure", low):
        append_unique(modalities, "EBSD_IPF")
        append_unique(evidence, "IPF")
    if re.search(r"\bkam\b|kernel average misorientation", low):
        append_unique(modalities, "EBSD_KAM")
        append_unique(evidence, "KAM")
    if re.search(r"\bgnd\b|geometrically necessary dislocation|misorientation|lagb|hagb|grain boundary map|gb map", low):
        append_unique(modalities, "EBSD_GB")
        append_unique(evidence, "grain_boundary_or_GND")
    if re.search(r"\bsem\b|scanning electron|secondary electron|\bbse\b|backscattered electron|\bfesem\b", low):
        append_unique(modalities, "SEM")
        append_unique(evidence, "SEM")
    if re.search(r"\btem\b|\bstem\b|transmission electron|hrtem|high[- ]resolution tem", low):
        append_unique(modalities, "TEM")
        append_unique(evidence, "TEM")
    if re.search(r"\beds\b|edx|energy[- ]dispersive|elemental map|elemental distribution", low):
        append_unique(modalities, "EDS")
        append_unique(evidence, "EDS")
    if re.search(r"optical micrograph|\bom\b|light micrograph|\blm\b|optical microscopy", low):
        append_unique(modalities, "OM_LM")
        append_unique(evidence, "optical_microscopy")
    if re.search(r"micro[- ]ct|\bμct\b|\buct\b|computed tomography|x[- ]ray tomography", low):
        append_unique(modalities, "CT")
        append_unique(evidence, "CT")
    if re.search(r"fractograph|fracture surface|fractured surface", low):
        append_unique(modalities, "fractography")
        append_unique(evidence, "fracture_surface")

    non_targets: List[str] = []
    if re.search(r"scheil|gulliver|thermo[- ]?calc|thermodynamic|solidification calculation|phase changes during solidification", low):
        append_unique(non_targets, "thermodynamic_calculation")
        if "scheil" in low or "gulliver" in low:
            append_unique(evidence, "Scheil-Gulliver")
        append_unique(evidence, "solidification")
        if "phase" in low:
            append_unique(evidence, "phase_changes")
    if re.search(r"phase diagram|equilibrium diagram|pseudo[- ]binary|isopleth", low):
        append_unique(non_targets, "phase_diagram")
        append_unique(evidence, "phase_diagram")
    if re.search(r"calculated strength|tested strength|strengthening contribution|strengthening mechanism|orowan|hall[- ]petch|taylor factor contribution", low):
        append_unique(non_targets, "strengthening_model_plot")
        if "calculated strength" in low:
            append_unique(evidence, "calculated_strength")
        if "tested strength" in low:
            append_unique(evidence, "tested_strength")
        if "strengthening contribution" in low:
            append_unique(evidence, "strengthening_contributions")
    if re.search(r"stress[-– ]strain|stress strain|tensile curve|tensile curves|engineering stress|true stress|load[-– ]displacement|s[-– ]n curve|fatigue life", low):
        append_unique(non_targets, "mechanical_curve")
        append_unique(evidence, "mechanical_curve")
    if re.search(r"mechanical propert|tensile propert|yield strength|\buts\b|elongation|normalized stress", low):
        append_unique(non_targets, "mechanical_property_plot")
        append_unique(evidence, "mechanical_properties")
    if re.search(r"\bxrd\b|x[- ]ray diffraction|diffraction pattern", low) and not any(item in modalities for item in ["TEM", "EBSD"]):
        append_unique(non_targets, "XRD")
        append_unique(evidence, "XRD")
    if re.search(r"hardness|microhardness|micro[- ]hardness|vickers", low):
        append_unique(non_targets, "hardness_plot")
        append_unique(evidence, "hardness")
    if re.search(r"\bdta\b|\bdsc\b|differential thermal|melting temperature range|heating rate", low):
        append_unique(non_targets, "thermal_analysis_plot")
        append_unique(evidence, "thermal_analysis")
    if re.search(r"porosity|pore size distribution|density|relative density", low) and not modalities:
        append_unique(non_targets, "porosity_plot")
        append_unique(evidence, "porosity")
    if re.search(r"\bd50\b|grain size|grain diameter|sphericity factor|\bsf\b|aspect ratio|size distribution", low):
        append_unique(non_targets, "microstructure_metric_plot")
        append_unique(evidence, "microstructure_metric")
    if re.search(r"calculated radius|mean radius|precipitate radius|precipitate size|isothermal holding", low):
        append_unique(non_targets, "precipitation_model_plot")
        append_unique(evidence, "precipitation_model")
    if re.search(r"concentration of chemical elements|chemical elements|composition profile|element concentration|elemental concentration", low):
        append_unique(non_targets, "composition_plot")
        append_unique(evidence, "composition")
    if re.search(r"\bdic\b|digital image correlation|true effective strain|strain scale|strain map", low):
        append_unique(non_targets, "DIC_strain_map")
        append_unique(evidence, "DIC")
    if re.search(r"surface topography|topography map|optical profilometer|surface profiling|roughness|average roughness|\bra\b", low):
        append_unique(non_targets, "surface_topography_map")
        append_unique(evidence, "surface_topography")
    if re.search(r"cyclic polarization|corrosion potential|pitting potential|eis[- ]nyquist|bode plot|ocp|pdp plot", low):
        append_unique(non_targets, "corrosion_curve")
        append_unique(evidence, "corrosion_curve")
    if re.search(r"predicted values|prediction|bpnn|hybrid model|rmse|mape|mae|training set|testing set", low):
        append_unique(non_targets, "model_prediction_plot")
        append_unique(evidence, "model_prediction")
    if re.search(r"studies|research to date|state[- ]of[- ]the[- ]art|overview of", low):
        append_unique(non_targets, "review_summary_plot")
        append_unique(evidence, "review_summary")
    if re.search(r"pole figure|pole figures|texture evolution|crystallographic texture|\bodf\b", low):
        append_unique(non_targets, "texture_plot")
        append_unique(evidence, "texture")
    if re.search(r"process window|process map|processing map|laser power|scan speed|scanning speed|hatch spacing|energy density|heat input|interpass temperature", low):
        append_unique(non_targets, "process_parameter_plot")
        append_unique(evidence, "process_parameters")
    if re.search(r"macroscopic morphology|macrograph|optical image of .*sample|photograph|photo of|equipment", low):
        append_unique(non_targets, "macro_photo")
        append_unique(evidence, "macro_photo")
    if re.search(r"schematic|illustration|diagram|experimental setup|setup|geometry|sample extraction|specimen geometry", low):
        append_unique(non_targets, "schematic")
        append_unique(evidence, "schematic")

    if modalities and non_targets:
        include_value = "uncertain"
        status = "auto_uncertain"
        curated_modalities = pipe(modalities + non_targets)
        notes.append("Mixed caption contains microscopy/image terms and non-microscopy plot/schematic terms; panel-level manual review required.")
    elif modalities:
        if "fractography" in modalities and not any(item in TARGET_MICROSCOPY_MODALITIES for item in modalities):
            include_value = "uncertain"
            status = "auto_uncertain"
            notes.append("Fractography detected without explicit SEM/optical modality; manual review recommended.")
        else:
            include_value = "yes"
            status = "auto_curated"
        curated_modalities = pipe(modalities)
    elif non_targets:
        include_value = "no"
        status = "auto_curated"
        curated_modalities = pipe(non_targets)
    else:
        include_value = "uncertain"
        status = "auto_uncertain"
        curated_modalities = "unknown_non_microscopy"
        notes.append("Caption-only rules could not identify a target microscopy modality or a clear non-target figure type.")

    if len(caption) < 20:
        include_value = "uncertain"
        status = "auto_uncertain"
        notes.append("Caption is too short for reliable automatic classification.")

    regions = curated_regions(caption, modalities, include_value if include_value == "no" and non_targets else include_value)
    if include_value == "no":
        regions = ["not_applicable"]
    return {
        "modality_candidates": curated_modalities,
        "image_region_candidates": pipe(regions),
        "evidence_terms": pipe(evidence),
        "include_for_sem_ebsd_tensile_dataset": include_value,
        "curation_status": status,
        "curation_notes": " ".join(notes),
    }


def has_manual_curation(row: Dict[str, str]) -> bool:
    return row.get("curation_status", "") in PRESERVE_CURATION_STATUSES and any(
        row.get(field, "") for field in FINAL_FIGURE_CURATION_FIELDS
    )


def merge_existing_manual_figure_annotations(
    new_rows: List[Dict[str, str]], existing_rows: Sequence[Dict[str, str]]
) -> List[Dict[str, str]]:
    existing_by_key = {(row.get("paper_id", ""), row.get("figure_key", "")): row for row in existing_rows}
    for row in new_rows:
        existing = existing_by_key.get((row.get("paper_id", ""), row.get("figure_key", "")), {})
        if not existing:
            continue
        if has_manual_curation(existing):
            for field in FINAL_FIGURE_CURATION_FIELDS:
                row[field] = existing.get(field, "")
    return new_rows


def build_figure_modality_review(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    review_rows = []
    counter = 1
    for row in rows:
        if row.get("curation_status", "") in PRESERVE_CURATION_STATUSES:
            continue
        issues = []
        include_value = row.get("include_for_sem_ebsd_tensile_dataset", "")
        classification_unknown = row.get("modality_candidates", "") == "unknown_non_microscopy"
        if include_value == "uncertain":
            issues.append("classification_uncertain")
        if classification_unknown:
            issues.append("caption_unclassified")
        if row.get("curation_status") == "auto_uncertain":
            issues.append("manual_review_recommended")
        if not issues:
            continue
        review_rows.append(
            {
                "review_id": f"FMR{counter:05d}",
                "figure_index_id": row.get("figure_index_id", ""),
                "paper_id": row.get("paper_id", ""),
                "doi": row.get("doi", ""),
                "figure_key": row.get("figure_key", ""),
                "figure_label": row.get("figure_label", ""),
                "source_type": row.get("source_type", ""),
                "modality_candidates": row.get("modality_candidates", ""),
                "image_region_candidates": row.get("image_region_candidates", ""),
                "evidence_terms": row.get("evidence_terms", ""),
                "include_for_sem_ebsd_tensile_dataset": include_value,
                "issue": "|".join(dict.fromkeys(issues)),
                "caption_hash_sha256": row.get("caption_hash_sha256", ""),
                "review_status": "pending",
                "review_notes": "",
            }
        )
        counter += 1
    return review_rows


def labels_from_group(group: str) -> List[str]:
    group = norm_text(group).replace("&", ",").replace(" and ", ",")
    labels: List[str] = []
    for start, end in re.findall(r"\b([a-z])-([a-z])\b", group):
        if ord(start) <= ord(end) and ord(end) - ord(start) <= 20:
            labels.extend(chr(code) for code in range(ord(start), ord(end) + 1))
    group = re.sub(r"\b[a-z]-[a-z]\b", "", group)
    for token in re.split(r"[\s,]+", group):
        token = token.strip(".-")
        if re.fullmatch(r"[a-z0-9]{1,4}", token):
            labels.append(token)
    return labels


def panel_labels_from_caption(caption: str) -> List[str]:
    labels: List[str] = []
    for match in re.finditer(r"\(([^)]{1,40})\)", caption or ""):
        labels.extend(labels_from_group(match.group(1)))
    for label in re.findall(r"(?<![a-z0-9])([a-z])\)\s+", caption or "", re.I):
        labels.append(label.lower())
    output: List[str] = []
    for label in labels:
        if label and label not in output:
            output.append(label)
    return output


def infer_digitized_or_table_value(row: Dict[str, str]) -> str:
    source_type = norm_text(row.get("source_type", ""))
    figure_or_table = norm_text(row.get("figure_or_table_id", ""))
    digitized = norm_text(row.get("digitized", ""))
    if digitized in {"yes", "true", "1"}:
        return "digitized_from_figure"
    if source_type == "figure_estimate":
        return "figure_estimate_pending_digitization"
    if source_type == "table" or "table" in figure_or_table:
        return "table_value"
    if source_type == "text":
        return "text_reported_value"
    if source_type == "figure_label":
        return "text_reported_from_associated_figure"
    return "source_form_unspecified"


def infer_value_form(row: Dict[str, str]) -> Dict[str, str]:
    evidence = norm_text(" ".join([row.get("evidence_text", ""), row.get("value_origin_note", ""), row.get("notes", "")]))
    source_form = infer_digitized_or_table_value(row)
    result = {
        "mean_or_single_value": "reported_value_unspecified",
        "dispersion_reported_in_source": "unknown",
        "dispersion_type": "unknown",
        "replicate_count_reported": "",
        "value_form_review_status": "review_recommended",
        "value_form_basis": "Central value extracted, but current evidence does not prove whether it is mean, single measurement, or representative value.",
    }
    if "standard error" in evidence:
        result.update(
            {
                "mean_or_single_value": "mean_value_with_standard_error",
                "dispersion_reported_in_source": "yes",
                "dispersion_type": "standard_error",
                "value_form_review_status": "accepted_by_extracted_evidence",
                "value_form_basis": "Evidence mentions average behavior and standard error.",
            }
        )
    elif "average" in evidence or "mean" in evidence:
        result.update(
            {
                "mean_or_single_value": "mean_value",
                "dispersion_reported_in_source": "unknown",
                "dispersion_type": "unknown",
                "value_form_review_status": "accepted_by_extracted_evidence",
                "value_form_basis": "Evidence identifies the central value as average/mean.",
            }
        )
    if "three tested" in evidence or "three samples" in evidence:
        result["replicate_count_reported"] = "3"
    if source_form == "figure_estimate_pending_digitization":
        result["mean_or_single_value"] = "figure_estimated_or_partial_value"
        result["value_form_review_status"] = "review_required"
        result["value_form_basis"] = "Figure-estimated or partial value needs manual digitization/audit before publication-grade release."
    return result


def build_papers(papers: Sequence[Dict[str, str]], license_rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    licenses = license_by_paper(license_rows)
    output = []
    for paper in papers:
        lic = licenses.get(paper.get("paper_id", ""), {})
        output.append(
            {
                "paper_id": paper.get("paper_id", ""),
                "doi": paper.get("doi", ""),
                "title": paper.get("title", "") or paper.get("canonical_title", ""),
                "journal": paper.get("journal", ""),
                "publisher": paper.get("publisher", ""),
                "year": paper.get("year", ""),
                "alloy_name": paper.get("alloy_name", ""),
                "am_process": paper.get("am_process", ""),
                "inclusion_status": paper.get("inclusion_status", ""),
                "article_license": lic.get("article_license", ""),
                "license_url": lic.get("license_url", ""),
                "open_access_status": lic.get("open_access_status", ""),
                "scientific_data_image_use_status": lic.get("scientific_data_image_use_status", "index_only_no_image_release"),
                "notes": scrub_public_text(paper.get("notes", "")),
            }
        )
    return output


def build_tensile(tensile: Sequence[Dict[str, str]], specimens: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    paper_by_specimen = specimen_to_paper(specimens)
    output = []
    for row in tensile:
        enriched = dict(row)
        enriched["paper_id"] = paper_by_specimen.get(row.get("specimen_id", ""), "")
        enriched["digitized_or_table_value"] = infer_digitized_or_table_value(row)
        enriched.update(infer_value_form(row))
        output.append(enriched)
    return output


def build_tensile_review(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    reviews = []
    counter = 1
    for row in rows:
        if row.get("mean_or_single_value") == "reported_value_unspecified":
            reviews.append(
                {
                    "review_id": f"TVF{counter:05d}",
                    "paper_id": row.get("paper_id", ""),
                    "tensile_id": row.get("tensile_id", ""),
                    "specimen_id": row.get("specimen_id", ""),
                    "field_name": "mean_or_single_value",
                    "current_value": row.get("mean_or_single_value", ""),
                    "issue": "Confirm whether central tensile value is mean, single measurement, representative value, or unspecified.",
                    "evidence_text": row.get("evidence_text", ""),
                    "review_status": "pending",
                    "review_notes": "",
                }
            )
            counter += 1
        if row.get("digitized_or_table_value") == "figure_estimate_pending_digitization":
            reviews.append(
                {
                    "review_id": f"TVF{counter:05d}",
                    "paper_id": row.get("paper_id", ""),
                    "tensile_id": row.get("tensile_id", ""),
                    "specimen_id": row.get("specimen_id", ""),
                    "field_name": "digitized_or_table_value",
                    "current_value": row.get("digitized_or_table_value", ""),
                    "issue": "Digitize figure value manually or exclude from publication-grade table.",
                    "evidence_text": row.get("evidence_text", ""),
                    "review_status": "pending",
                    "review_notes": "",
                }
            )
            counter += 1
    return reviews


def build_figure_index(
    figures: Sequence[Dict[str, str]],
    papers: Sequence[Dict[str, str]],
    license_rows: Sequence[Dict[str, str]],
    include_caption_excerpts: bool,
) -> List[Dict[str, str]]:
    papers_by_id = paper_by_id(papers)
    licenses = license_by_paper(license_rows)
    output = []
    for idx, figure in enumerate(figures, start=1):
        paper_id = figure.get("paper_id", "")
        paper = papers_by_id.get(paper_id, {})
        lic = licenses.get(paper_id, {})
        source_type = figure.get("source_type", "figure")
        curation = curated_classification(figure)
        output.append(
            {
                "figure_index_id": f"FIGIDX{idx:05d}",
                "paper_id": paper_id,
                "doi": paper.get("doi", ""),
                "figure_key": figure.get("figure_key", ""),
                "figure_label": figure.get("figure_label", ""),
                "figure_number": figure.get("figure_number", ""),
                "panel_labels_detected": "|".join(panel_labels_from_caption(figure.get("caption_text", ""))),
                "page_number": figure.get("page_number", ""),
                "source_type": source_type,
                "modality_candidates": curation.get("modality_candidates", ""),
                "image_region_candidates": curation.get("image_region_candidates", ""),
                "evidence_terms": curation.get("evidence_terms", ""),
                "include_for_sem_ebsd_tensile_dataset": curation.get("include_for_sem_ebsd_tensile_dataset", ""),
                "curation_status": curation.get("curation_status", ""),
                "curation_notes": curation.get("curation_notes", ""),
                "caption_hash_sha256": short_hash(figure.get("caption_text", "")),
                "caption_excerpt": make_excerpt(figure.get("caption_text", ""), 240) if include_caption_excerpts else "",
                "license_status": lic.get("scientific_data_image_use_status", "index_only_no_image_release"),
                "article_url": paper_doi_url(paper.get("doi", "")),
                "review_status": "pending",
                "notes": "No image file redistributed; index points to DOI, page, figure, and panel labels.",
            }
        )
    return output


def build_figure_links(
    figure_index: Sequence[Dict[str, str]],
    image_panels: Sequence[Dict[str, str]],
    image_links: Sequence[Dict[str, str]],
) -> List[Dict[str, str]]:
    idx_by_key = {(row.get("paper_id", ""), row.get("figure_key", "")): row for row in figure_index}
    panel_by_image = {row.get("image_id", ""): row for row in image_panels}
    output = []
    for link in image_links:
        panel = panel_by_image.get(link.get("image_id", ""), {})
        idx = idx_by_key.get((link.get("paper_id", ""), panel.get("figure_key", "")), {})
        if not idx:
            continue
        output.append(
            {
                "link_id": link.get("link_id", ""),
                "figure_index_id": idx.get("figure_index_id", ""),
                "paper_id": link.get("paper_id", ""),
                "doi": idx.get("doi", ""),
                "figure_key": panel.get("figure_key", ""),
                "figure_label": panel.get("figure_label", ""),
                "panel_label": panel.get("panel_label", ""),
                "modality": panel.get("modality", ""),
                "specimen_id": link.get("specimen_id", ""),
                "tensile_id": link.get("tensile_id", ""),
                "link_basis": link.get("link_basis", ""),
                "confidence": link.get("confidence", ""),
                "review_status": link.get("review_status", "pending"),
                "notes": link.get("notes", ""),
            }
        )
    return output


def build_figure_link_review(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    reviews = []
    for counter, row in enumerate(rows, start=1):
        status = norm_text(row.get("review_status", ""))
        if status not in {"accepted"}:
            reviews.append(
                {
                    "review_id": f"FLR{counter:05d}",
                    "paper_id": row.get("paper_id", ""),
                    "figure_index_id": row.get("figure_index_id", ""),
                    "link_id": row.get("link_id", ""),
                    "specimen_id": row.get("specimen_id", ""),
                    "tensile_id": row.get("tensile_id", ""),
                    "issue": "Confirm figure/panel-to-specimen/tensile mapping before publication-grade use.",
                    "candidate_value": row.get("link_basis", ""),
                    "review_status": "pending",
                    "review_notes": "",
                }
            )
    return reviews


def build_paper_extraction_review(
    papers: Sequence[Dict[str, str]],
    specimens: Sequence[Dict[str, str]],
    tensile_rows: Sequence[Dict[str, str]],
    figure_index: Sequence[Dict[str, str]],
) -> List[Dict[str, str]]:
    specimen_counts = Counter(row.get("paper_id", "") for row in specimens if row.get("paper_id", ""))
    paper_for_specimen = specimen_to_paper(specimens)
    tensile_counts = Counter(paper_for_specimen.get(row.get("specimen_id", ""), "") for row in tensile_rows)
    figure_counts = Counter(row.get("paper_id", "") for row in figure_index if row.get("paper_id", ""))
    microscopy_counts = Counter(
        row.get("paper_id", "")
        for row in figure_index
        if re.search(r"\b(SEM|EBSD|EBSD_IPF|EBSD_KAM|EBSD_GB)\b", row.get("modality_candidates", ""))
    )

    reviews = []
    counter = 1
    for paper in papers:
        paper_id = paper.get("paper_id", "")
        if tensile_counts.get(paper_id, 0):
            continue
        reviews.append(
            {
                "review_id": f"PER{counter:05d}",
                "paper_id": paper_id,
                "doi": paper.get("doi", ""),
                "title": paper.get("title", "") or paper.get("canonical_title", ""),
                "issue": "No specimen/tensile records are present in v2 for this paper; extract and verify tensile data before claiming an image-property relationship for this source.",
                "figure_index_count": str(figure_counts.get(paper_id, 0)),
                "microscopy_candidate_count": str(microscopy_counts.get(paper_id, 0)),
                "specimen_count": str(specimen_counts.get(paper_id, 0)),
                "tensile_record_count": "0",
                "review_status": "pending",
                "review_notes": "",
            }
        )
        counter += 1
    return reviews


def remove_local_path_fields(rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    return [{key: value for key, value in row.items() if key not in LOCAL_PATH_FIELDS} for row in rows]


def public_specimen_fields(specimens: Sequence[Dict[str, str]]) -> List[str]:
    if not specimens:
        return []
    return [field for field in specimens[0].keys() if field not in LOCAL_PATH_FIELDS]


def public_micro_fields(micro: Sequence[Dict[str, str]]) -> List[str]:
    if not micro:
        return []
    return [field for field in micro[0].keys() if field not in LOCAL_PATH_FIELDS]


def build_source_license_output(papers: Sequence[Dict[str, str]], license_rows: Sequence[Dict[str, str]]) -> List[Dict[str, str]]:
    if license_rows:
        return remove_local_path_fields(license_rows)
    return [
        {
            "paper_id": paper.get("paper_id", ""),
            "doi": paper.get("doi", ""),
            "title": paper.get("title", ""),
            "article_license": "",
            "license_url": "",
            "open_access_status": "not_checked",
            "scientific_data_image_use_status": "index_only_no_image_release",
            "checked_date": "",
            "notes": "License not checked by this script; no images are redistributed in this release.",
        }
        for paper in papers
    ]


def dictionary_rows() -> List[Dict[str, str]]:
    return [
        {"table": "figure_index.csv", "field": "figure_index_id", "type": "string", "description": "Stable identifier for the indexed figure record.", "allowed_values": ""},
        {"table": "figure_index.csv", "field": "modality_candidates", "type": "pipe-delimited string", "description": "Caption-only final figure modality/type used for downstream SEM/EBSD-tensile filtering.", "allowed_values": "SEM|EBSD|EBSD_IPF|EBSD_KAM|EBSD_GB|EDS|TEM|OM_LM|CT|fractography|XRD|mechanical_curve|mechanical_property_plot|hardness_plot|porosity_plot|thermodynamic_calculation|precipitation_model_plot|phase_diagram|strengthening_model_plot|process_parameter_plot|macro_photo|texture_plot|thermal_analysis_plot|microstructure_metric_plot|composition_plot|DIC_strain_map|surface_topography_map|corrosion_curve|model_prediction_plot|review_summary_plot|schematic|table|unknown_non_microscopy"},
        {"table": "figure_index.csv", "field": "image_region_candidates", "type": "pipe-delimited string", "description": "Caption-only final specimen/image region for the indexed figure.", "allowed_values": "microstructure|feedstock_powder|fracture_surface|cross_section|surface_or_melt_pool|not_applicable|unknown"},
        {"table": "figure_index.csv", "field": "evidence_terms", "type": "pipe-delimited string", "description": "Caption terms that support the final modality/type classification.", "allowed_values": ""},
        {"table": "figure_index.csv", "field": "include_for_sem_ebsd_tensile_dataset", "type": "string", "description": "Whether this figure should enter the SEM/EBSD/image-property analysis after caption-only curation.", "allowed_values": "yes|no|uncertain"},
        {"table": "figure_index.csv", "field": "curation_status", "type": "string", "description": "Automatic/manual status of final figure modality fields.", "allowed_values": "auto_curated|auto_uncertain|manual_reviewed|manual_preserved"},
        {"table": "figure_index.csv", "field": "curation_notes", "type": "string", "description": "Short reason for final figure modality and inclusion decision.", "allowed_values": ""},
        {"table": "figure_index.csv", "field": "caption_hash_sha256", "type": "string", "description": "Hash of the full extracted caption for internal traceability without redistributing the caption text.", "allowed_values": ""},
        {"table": "figure_modality_curation_review_queue.csv", "field": "issue", "type": "string", "description": "Reason the figure modality curation row needs manual review.", "allowed_values": "classification_uncertain|caption_unclassified|manual_review_recommended"},
        {"table": "figure_specimen_links.csv", "field": "review_status", "type": "string", "description": "Manual review state for figure-to-specimen/tensile mapping.", "allowed_values": "pending|accepted|rejected"},
        {"table": "paper_extraction_review_queue.csv", "field": "issue", "type": "string", "description": "Paper-level extraction gap that must be resolved before image-property relationship claims.", "allowed_values": ""},
        {"table": "tensile_properties.csv", "field": "mean_or_single_value", "type": "string", "description": "Whether central tensile value is mean, single, representative, partial, figure-estimated, or unspecified.", "allowed_values": "mean_value|mean_value_with_dispersion|mean_value_with_standard_error|single_measurement|representative_value|reported_value_unspecified|mean_value_partial_record|figure_estimated_or_partial_value"},
        {"table": "tensile_properties.csv", "field": "digitized_or_table_value", "type": "string", "description": "Source form of tensile values.", "allowed_values": "table_value|text_reported_value|text_reported_from_associated_figure|digitized_from_figure|figure_estimate_pending_digitization|source_form_unspecified"},
        {"table": "source_license.csv", "field": "scientific_data_image_use_status", "type": "string", "description": "License-oriented image reuse classification. For no-image release this is documentation only.", "allowed_values": ""},
    ]


def schema_json(table_fields: Dict[str, Sequence[str]]) -> Dict[str, object]:
    return {
        "name": "Materials_Microstructure_Tensile_Index_NoImage",
        "release_type": "no_image_index_database",
        "tables": {
            table: {"primary_key": fields[0] if fields else "", "fields": list(fields)}
            for table, fields in table_fields.items()
        },
        "public_exclusions": sorted(LOCAL_PATH_FIELDS),
    }


def validate_outputs(
    output_dir: Path,
    papers: Sequence[Dict[str, str]],
    figure_index: Sequence[Dict[str, str]],
    figure_links: Sequence[Dict[str, str]],
    tensile_rows: Sequence[Dict[str, str]],
    tensile_review: Sequence[Dict[str, str]],
    figure_link_review: Sequence[Dict[str, str]],
    paper_extraction_review: Sequence[Dict[str, str]],
    figure_modality_review: Sequence[Dict[str, str]],
) -> List[Dict[str, str]]:
    rows = []
    counter = 1

    def add(name: str, status: str, count: int, details: str) -> None:
        nonlocal counter
        rows.append({"check_id": f"VAL{counter:04d}", "check_name": name, "status": status, "count": str(count), "details": details})
        counter += 1

    add("papers_have_doi", "pass" if all(row.get("doi") for row in papers) else "warn", sum(1 for row in papers if not row.get("doi")), "Missing DOI count.")
    add("figure_index_rows", "pass" if figure_index else "warn", len(figure_index), "Indexed figure/table records from figure_inventory.")
    add("figure_links_pending_review", "warn" if figure_link_review else "pass", len(figure_link_review), "Figure-specimen links requiring manual validation.")
    add("tensile_value_form_pending_review", "warn" if tensile_review else "pass", len(tensile_review), "Tensile value source-form records requiring manual validation.")
    add("figure_estimates", "warn" if any(row.get("digitized_or_table_value") == "figure_estimate_pending_digitization" for row in tensile_rows) else "pass", sum(1 for row in tensile_rows if row.get("digitized_or_table_value") == "figure_estimate_pending_digitization"), "Figure-estimated tensile rows.")
    add("papers_without_tensile_records", "warn" if paper_extraction_review else "pass", len(paper_extraction_review), "Papers requiring specimen/tensile extraction before image-property relationship use.")
    add("figure_modality_curation_pending_review", "warn" if figure_modality_review else "pass", len(figure_modality_review), "Figure modality/type curation rows requiring manual review.")

    local_path_hits = 0
    for csv_path in output_dir.glob("*.csv"):
        text = csv_path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"data[/\\](raw_pdfs|figures|text)|(?<![A-Za-z])[A-Za-z]:[/\\]", text):
            local_path_hits += 1
    add("no_local_paths_in_public_csv", "pass" if local_path_hits == 0 else "fail", local_path_hits, "CSV files containing local paths or image/PDF directories.")
    return rows


def write_readme(output_dir: Path, counts: Dict[str, int]) -> None:
    lines = [
        "# Materials Microstructure-Tensile No-Image Index Database",
        "",
        "This release package contains structured literature-derived metadata and figure indexes only.",
        "It does not redistribute PDFs, page images, figure crops, or panel crops.",
        "",
        "## Tables",
        "",
        "- `papers.csv`",
        "- `source_license.csv`",
        "- `specimens.csv`",
        "- `tensile_properties.csv`",
        "- `microstructure_records.csv`",
        "- `figure_index.csv`",
        "- `figure_specimen_links.csv`",
        "- `figure_modality_curation_review_queue.csv`",
        "- `tensile_value_form_review_queue.csv`",
        "- `figure_link_review_queue.csv`",
        "- `paper_extraction_review_queue.csv`",
        "- `data_dictionary.csv`",
        "- `schema.json`",
        "- `validation_report.csv`",
        "",
        "## Counts",
        "",
    ]
    for key, value in counts.items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Manual Validation",
            "",
            "Rows in review queues must be manually verified before publication-grade claims are made.",
            "Use DOI, page number, figure label, panel label, specimen ID, and tensile ID to audit each linkage.",
            "",
        ]
    )
    (output_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--db-v2-dir", type=Path, default=Path("data/db/v2"))
    parser.add_argument("--figure-inventory", type=Path, default=Path("data/metadata/figure_inventory.csv"))
    parser.add_argument("--source-license", type=Path, default=Path("data/metadata/source_license.csv"))
    parser.add_argument("--v3-dir", type=Path, default=Path("data/db/v3_image_ml"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/db/scientific_data_no_image_v1"))
    parser.add_argument("--include-caption-excerpts", action="store_true")
    args = parser.parse_args()

    root = args.project_root.resolve()
    db_v2 = args.db_v2_dir if args.db_v2_dir.is_absolute() else root / args.db_v2_dir
    figure_inventory_path = args.figure_inventory if args.figure_inventory.is_absolute() else root / args.figure_inventory
    license_path = args.source_license if args.source_license.is_absolute() else root / args.source_license
    v3_dir = args.v3_dir if args.v3_dir.is_absolute() else root / args.v3_dir
    output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    papers_v2 = read_csv(db_v2 / "papers_v2.csv")
    specimens = read_csv(db_v2 / "specimens_v2.csv")
    tensile_v2 = read_csv(db_v2 / "tensile_records_v2.csv")
    micro = read_csv(db_v2 / "microstructure_records_v2.csv")
    figures = read_csv(figure_inventory_path)
    license_rows = read_csv(license_path)
    image_panels = read_csv(v3_dir / "image_panels_v3.csv")
    image_links = read_csv(v3_dir / "image_specimen_links_v3.csv")
    existing_figure_index = read_csv(output_dir / "figure_index.csv")

    papers = build_papers(papers_v2, license_rows)
    tensile = build_tensile(tensile_v2, specimens)
    tensile_review = build_tensile_review(tensile)
    figure_index = build_figure_index(figures, papers_v2, license_rows, args.include_caption_excerpts)
    figure_index = merge_existing_manual_figure_annotations(figure_index, existing_figure_index)
    figure_modality_review = build_figure_modality_review(figure_index)
    figure_links = build_figure_links(figure_index, image_panels, image_links)
    figure_link_review = build_figure_link_review(figure_links)
    paper_extraction_review = build_paper_extraction_review(papers_v2, specimens, tensile_v2, figure_index)
    source_license = build_source_license_output(papers_v2, license_rows)

    specimen_rows = remove_local_path_fields(specimens)
    micro_rows = remove_local_path_fields(micro)

    tensile_fields = ["paper_id"] + [field for field in tensile_v2[0].keys() if field != "paper_id"] + [field for field in TENSILE_EXTRA_FIELDS if field != "paper_id"] if tensile_v2 else TENSILE_EXTRA_FIELDS
    source_license_fields = list(source_license[0].keys()) if source_license else ["paper_id", "doi", "article_license", "license_url", "open_access_status", "scientific_data_image_use_status", "notes"]

    write_csv(output_dir / "papers.csv", PAPER_FIELDS, papers)
    write_csv(output_dir / "source_license.csv", source_license_fields, source_license)
    write_csv(output_dir / "specimens.csv", public_specimen_fields(specimen_rows), specimen_rows)
    write_csv(output_dir / "tensile_properties.csv", tensile_fields, tensile)
    write_csv(output_dir / "microstructure_records.csv", public_micro_fields(micro_rows), micro_rows)
    write_csv(output_dir / "figure_index.csv", FIGURE_INDEX_FIELDS, figure_index)
    write_csv(output_dir / "figure_specimen_links.csv", FIGURE_LINK_FIELDS, figure_links)
    write_csv(output_dir / "figure_modality_curation_review_queue.csv", FIGURE_MODALITY_REVIEW_FIELDS, figure_modality_review)
    write_csv(output_dir / "tensile_value_form_review_queue.csv", TENSILE_REVIEW_FIELDS, tensile_review)
    write_csv(output_dir / "figure_link_review_queue.csv", FIGURE_LINK_REVIEW_FIELDS, figure_link_review)
    write_csv(output_dir / "paper_extraction_review_queue.csv", PAPER_EXTRACTION_REVIEW_FIELDS, paper_extraction_review)
    write_csv(output_dir / "data_dictionary.csv", DICTIONARY_FIELDS, dictionary_rows())

    table_fields = {
        "papers.csv": PAPER_FIELDS,
        "source_license.csv": source_license_fields,
        "specimens.csv": public_specimen_fields(specimen_rows),
        "tensile_properties.csv": tensile_fields,
        "microstructure_records.csv": public_micro_fields(micro_rows),
        "figure_index.csv": FIGURE_INDEX_FIELDS,
        "figure_specimen_links.csv": FIGURE_LINK_FIELDS,
        "figure_modality_curation_review_queue.csv": FIGURE_MODALITY_REVIEW_FIELDS,
        "paper_extraction_review_queue.csv": PAPER_EXTRACTION_REVIEW_FIELDS,
    }
    (output_dir / "schema.json").write_text(json.dumps(schema_json(table_fields), indent=2, ensure_ascii=False), encoding="utf-8")

    validation = validate_outputs(output_dir, papers, figure_index, figure_links, tensile, tensile_review, figure_link_review, paper_extraction_review, figure_modality_review)
    write_csv(output_dir / "validation_report.csv", VALIDATION_FIELDS, validation)

    counts = {
        "papers": len(papers),
        "specimens": len(specimen_rows),
        "tensile records": len(tensile),
        "microstructure records": len(micro_rows),
        "figure index records": len(figure_index),
        "figure-specimen links": len(figure_links),
        "figure modality curation review rows": len(figure_modality_review),
        "tensile value-form review rows": len(tensile_review),
        "figure link review rows": len(figure_link_review),
        "paper extraction review rows": len(paper_extraction_review),
    }
    write_readme(output_dir, counts)

    for key, value in counts.items():
        print(f"{key}: {value}")
    print(f"output_dir: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
