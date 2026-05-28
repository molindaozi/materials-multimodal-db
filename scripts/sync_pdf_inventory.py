#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class InventoryRow:
    source_type: str
    publisher_folder: str
    file_name: str
    extension: str
    relative_path: str
    size_bytes: int
    last_write_time: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inventory raw PDF and supplement files into data/metadata/pdf_inventory.csv."
    )
    parser.add_argument(
        "--project-root",
        default=Path(__file__).resolve().parents[1],
        help="Workspace root that contains data/raw_pdfs and data/raw_supp.",
    )
    parser.add_argument(
        "--inventory-path",
        default="data/metadata/pdf_inventory.csv",
        help="Inventory CSV path relative to project root, unless absolute.",
    )
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def relative_to_project(path: Path, project_root: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def scan_files(root: Path, project_root: Path, source_type: str) -> list[InventoryRow]:
    if not root.exists():
        return []

    rows: list[InventoryRow] = []
    for file_path in sorted(p for p in root.rglob("*") if p.is_file()):
        publisher_folder = ""
        if source_type == "pdf" and file_path.parent != root:
            publisher_folder = file_path.parent.name

        rows.append(
            InventoryRow(
                source_type=source_type,
                publisher_folder=publisher_folder,
                file_name=file_path.name,
                extension=file_path.suffix,
                relative_path=relative_to_project(file_path, project_root),
                size_bytes=file_path.stat().st_size,
                last_write_time=datetime.fromtimestamp(file_path.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
            )
        )
    return rows


def write_inventory(rows: list[InventoryRow], inventory_path: Path) -> None:
    fieldnames = [
        "source_type",
        "publisher_folder",
        "file_name",
        "extension",
        "relative_path",
        "size_bytes",
        "last_write_time",
    ]
    with inventory_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(
            rows,
            key=lambda item: (
                item.source_type,
                item.publisher_folder,
                item.file_name.lower(),
            ),
        ):
            writer.writerow(row.__dict__)


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).expanduser().resolve()
    inventory_path = Path(args.inventory_path)
    if not inventory_path.is_absolute():
        inventory_path = (project_root / inventory_path).resolve()

    data_root = project_root / "data"
    pdf_root = data_root / "raw_pdfs"
    supp_root = data_root / "raw_supp"
    metadata_root = inventory_path.parent

    for path in (pdf_root, supp_root, metadata_root):
        ensure_dir(path)

    rows = []
    rows.extend(scan_files(pdf_root, project_root, "pdf"))
    rows.extend(scan_files(supp_root, project_root, "supplement"))
    write_inventory(rows, inventory_path)

    print(f"Inventory written to {inventory_path}")
    print(f"File count: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
