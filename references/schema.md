# Schema Reference

Use stable identifiers throughout the database:

- `paper_id`: one source paper.
- `specimen_id`: one reported material condition or specimen group.
- `tensile_id`: one tensile property record.
- `figure_index_id`: one indexed figure/table/panel candidate.
- `image_id`: one extracted page image, figure crop, or panel crop.
- `link_id`: one figure-to-specimen/property relation.

## Core Tables

`papers.csv` stores bibliographic metadata and license fields.

`specimens.csv` stores specimen-centric material condition metadata: material/alloy, processing route, build direction, heat treatment, post-processing, and source locator.

`tensile_properties.csv` stores YS, UTS, elongation, test temperature, test direction, value source, value form, confidence, and `specimen_id`.

`microstructure_records.csv` stores specimen-level microstructure evidence and text/table/figure source locators.

`figure_index.csv` stores DOI, paper, page, figure/table label, panel label, modality candidates, image-region candidates, caption hash/excerpt, crop provenance, license/status fields, and review status.

`image_manifest.csv` stores image assets included in the release or referenced locally. Every row must include source provenance, file existence, checksum when available, and redistribution status.

`figure_specimen_links.csv` stores candidate links from image evidence to `specimen_id` and `tensile_id`.

`multimodal_ml_database.csv` denormalizes accepted/pending figure-specimen-property links for downstream image-property analysis.

`review_queue.csv` stores all unresolved extraction, modality, license, and link issues.

## Required Provenance Fields

Every extracted property or image-derived record should preserve:

- `paper_id`
- DOI when available
- page number
- figure/table label when applicable
- panel label when applicable
- source field or source locator
- extraction method
- confidence or review status

## Release Variants

The image-enabled release may include image paths and copied image files.

The no-image release must remove `page_image_path`, `crop_image_path`, panel crop paths, and copied image files while preserving DOI/page/figure/panel index rows.
