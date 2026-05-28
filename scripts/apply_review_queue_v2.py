#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import datetime
import shutil
import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply review_queue_v2 decisions back into the v2 CSV tables.")
    parser.add_argument("--db-dir", default="data/db/v2", help="Directory containing v2 CSV files.")
    parser.add_argument("--review-queue", default="", help="Path to review_queue_v2.csv. Defaults to <db-dir>/review_queue_v2.csv")
    parser.add_argument(
        "--write-dir",
        default="",
        help="Optional directory for writing updated CSVs. Defaults to in-place writes inside <db-dir>.",
    )
    parser.add_argument("--create-backup", action="store_true", help="Create a timestamped backup copy before modifying CSV files.")
    parser.add_argument("--backup-root", default="", help="Optional backup root. Defaults to <db-dir>/backups")
    return parser.parse_args()


def load_csv(path: Path) -> pd.DataFrame:
    encodings = ["utf-8", "utf-8-sig", "gb18030", "gbk"]
    last_error = None
    for encoding in encodings:
        try:
            return pd.read_csv(path, keep_default_na=False, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error


def split_note_tokens(review_notes: str) -> tuple[dict[str, str], list[str]]:
    assignments: dict[str, str] = {}
    comments: list[str] = []
    for raw_part in str(review_notes or "").split(";"):
        part = raw_part.strip()
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
            assignments[key.strip()] = value.strip()
        else:
            comments.append(part)
    return assignments, comments


def append_note(existing: object, new_text: str) -> str:
    existing_text = str(existing or "").strip()
    new_text = str(new_text or "").strip()
    if existing_text and new_text:
        if new_text in existing_text:
            return existing_text
        return f"{existing_text} | {new_text}"
    return existing_text or new_text


def to_float_if_possible(value: str) -> object:
    try:
        if value == "":
            return ""
        return float(value)
    except ValueError:
        return value


def backup_files(db_dir: Path, backup_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = backup_root / timestamp
    target.mkdir(parents=True, exist_ok=True)
    for name in [
        "specimens_v2.csv",
        "microstructure_records_v2.csv",
        "tensile_records_v2.csv",
        "review_queue_v2.csv",
    ]:
        source = db_dir / name
        if source.exists():
            shutil.copy2(source, target / name)
    return target


def match_single(df: pd.DataFrame, mask: pd.Series, description: str) -> int:
    matched = df.index[mask].tolist()
    if len(matched) == 1:
        return matched[0]
    if len(matched) == 0:
        raise RuntimeError(f"No row matched for {description}")
    raise RuntimeError(f"Multiple rows matched for {description}")


def apply_to_tensile(row: pd.Series, tensile: pd.DataFrame) -> tuple[str, list[str]]:
    idx = match_single(
        tensile,
        (tensile["specimen_id"] == row["specimen_id"])
        & (tensile["source_type"] == row["source_type"])
        & (tensile["figure_or_table_id"] == row["figure_or_table_id"]),
        f"tensile {row['specimen_id']} {row['figure_or_table_id']}",
    )
    assignments, comments = split_note_tokens(row["review_notes"])
    changed: list[str] = []

    if row["review_status"] == "accepted":
        for key in ["yield_strength_mpa", "ultimate_tensile_strength_mpa", "elongation_pct", "test_temperature_c", "strain_rate_s_inv", "loading_direction", "fracture_mode"]:
            if key in assignments:
                tensile.at[idx, key] = to_float_if_possible(assignments[key])
                changed.append(key)
        tensile.at[idx, "verification_status"] = "accepted"
        note_text = "review accepted"
        if comments:
            note_text = append_note(note_text, " | ".join(comments))
        tensile.at[idx, "value_origin_note"] = append_note(tensile.at[idx, "value_origin_note"], note_text)
        tensile.at[idx, "notes"] = append_note(tensile.at[idx, "notes"], note_text)
    elif row["review_status"] == "rejected":
        tensile.at[idx, "verification_status"] = "rejected"
        note_text = append_note("review rejected", " | ".join(comments)) if comments else "review rejected"
        tensile.at[idx, "value_origin_note"] = append_note(tensile.at[idx, "value_origin_note"], note_text)
        tensile.at[idx, "notes"] = append_note(tensile.at[idx, "notes"], note_text)
    return tensile.at[idx, "verification_status"], changed


def apply_to_micro(row: pd.Series, micro: pd.DataFrame) -> tuple[str, list[str]]:
    idx = match_single(
        micro,
        (micro["specimen_id"] == row["specimen_id"])
        & (micro["feature_name"] == row["field_name"])
        & (micro["source_type"] == row["source_type"])
        & (micro["figure_or_table_id"] == row["figure_or_table_id"]),
        f"micro {row['specimen_id']} {row['field_name']} {row['figure_or_table_id']}",
    )
    assignments, comments = split_note_tokens(row["review_notes"])
    changed: list[str] = []

    if row["review_status"] == "accepted":
        for key in ["feature_value", "value_unit", "feature_category", "condition_text", "characterization_method"]:
            if key in assignments:
                micro.at[idx, key] = assignments[key]
                changed.append(key)
        micro.at[idx, "verification_status"] = "accepted"
        note_text = "review accepted"
        if comments:
            note_text = append_note(note_text, " | ".join(comments))
        micro.at[idx, "notes"] = append_note(micro.at[idx, "notes"], note_text)
    elif row["review_status"] == "rejected":
        micro.at[idx, "verification_status"] = "rejected"
        note_text = append_note("review rejected", " | ".join(comments)) if comments else "review rejected"
        micro.at[idx, "notes"] = append_note(micro.at[idx, "notes"], note_text)
    return micro.at[idx, "verification_status"], changed


def apply_to_specimen(row: pd.Series, specimens: pd.DataFrame) -> tuple[str, list[str]]:
    idx = match_single(specimens, specimens["specimen_id"] == row["specimen_id"], f"specimen {row['specimen_id']}")
    assignments, comments = split_note_tokens(row["review_notes"])
    changed: list[str] = []

    if row["review_status"] == "accepted":
        allowed_keys = [
            "build_direction",
            "sampling_direction",
            "direction_raw_text",
            "post_treatment",
            "heat_treatment",
            "treatment_raw_text",
            "temperature_condition",
        ]
        for key in allowed_keys:
            if key in assignments:
                specimens.at[idx, key] = assignments[key]
                changed.append(key)
        note_text = "review accepted"
        if comments:
            note_text = append_note(note_text, " | ".join(comments))
        specimens.at[idx, "notes"] = append_note(specimens.at[idx, "notes"], note_text)
    elif row["review_status"] == "rejected":
        note_text = append_note("review rejected", " | ".join(comments)) if comments else "review rejected"
        specimens.at[idx, "notes"] = append_note(specimens.at[idx, "notes"], note_text)
    return row["review_status"], changed


def main() -> int:
    args = parse_args()
    db_dir = Path(args.db_dir).resolve()
    review_queue_path = Path(args.review_queue).resolve() if args.review_queue else db_dir / "review_queue_v2.csv"
    write_dir = Path(args.write_dir).resolve() if args.write_dir else db_dir
    write_dir.mkdir(parents=True, exist_ok=True)

    specimens_path = db_dir / "specimens_v2.csv"
    micro_path = db_dir / "microstructure_records_v2.csv"
    tensile_path = db_dir / "tensile_records_v2.csv"

    specimens = load_csv(specimens_path)
    micro = load_csv(micro_path)
    tensile = load_csv(tensile_path)
    review = load_csv(review_queue_path)

    if args.create_backup:
        backup_root = Path(args.backup_root).resolve() if args.backup_root else db_dir / "backups"
        backup_path = backup_files(db_dir, backup_root)
    else:
        backup_path = None

    applied_rows = 0
    skipped_rows = 0
    updated_rows: list[dict[str, object]] = []

    for idx, row in review.iterrows():
        status = str(row["review_status"] or "").strip().lower()
        if status not in {"accepted", "rejected"}:
            skipped_rows += 1
            continue

        field_name = str(row["field_name"])
        if field_name == "tensile_record":
            new_status, changed_fields = apply_to_tensile(row, tensile)
        elif field_name in {"direction_normalization", "treatment_normalization"}:
            new_status, changed_fields = apply_to_specimen(row, specimens)
        else:
            new_status, changed_fields = apply_to_micro(row, micro)

        review.at[idx, "review_status"] = status
        review.at[idx, "review_notes"] = str(row["review_notes"])
        applied_rows += 1
        updated_rows.append(
            {
                "paper_id": row["paper_id"],
                "specimen_id": row["specimen_id"],
                "field_name": field_name,
                "review_status": status,
                "applied_status": new_status,
                "changed_fields": ",".join(changed_fields),
            }
        )

    specimens_out = write_dir / "specimens_v2.csv"
    micro_out = write_dir / "microstructure_records_v2.csv"
    tensile_out = write_dir / "tensile_records_v2.csv"
    review_out = write_dir / "review_queue_v2.csv"

    try:
        specimens.to_csv(specimens_out, index=False, encoding="utf-8")
        micro.to_csv(micro_out, index=False, encoding="utf-8")
        tensile.to_csv(tensile_out, index=False, encoding="utf-8")
        review.to_csv(review_out, index=False, encoding="utf-8")
    except PermissionError as exc:
        raise RuntimeError(
            f"Could not write updated CSVs because a target file is locked: {exc}. "
            "Close the CSV in Excel or rerun with --write-dir to stage the updated files elsewhere."
        ) from exc

    summary = {
        "db_dir": str(db_dir),
        "review_queue": str(review_queue_path),
        "write_dir": str(write_dir),
        "backup_path": str(backup_path) if backup_path else "",
        "applied_rows": applied_rows,
        "skipped_rows": skipped_rows,
        "updated_examples": updated_rows[:10],
    }
    (write_dir / "review_apply_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
