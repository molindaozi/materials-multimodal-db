---
name: materials-multimodal-db
description: Use this skill when processing materials science literature PDFs into a multimodal, specimen-centric database with tensile properties, figure/table/caption indexing, image extraction and cropping, microstructure modality recognition, figure-specimen-property links, review queues, validation reports, and a reusable public database release.
---

# Materials Multimodal DB

Use this skill to build a structured materials literature database from PDF papers. The workflow is semi-automatic: generate candidate records and image links first, then review uncertain values before treating the database as publication-ready.

## Default Workflow

1. Inventory source PDFs and supplements with `scripts/sync_pdf_inventory.py`.
2. Extract figure/table captions, page images, and figure crops with `scripts/extract_pdf_figures_pdffigures2.py` or `scripts/run_figure_extraction_batch.py`.
3. Create specimen-centric records for material/alloy, process, build direction, heat treatment, test condition, microstructure evidence, and source locator.
4. Extract tensile properties: YS, UTS, elongation, test temperature, direction, value source, and confidence.
5. Build figure indexes with DOI, `paper_id`, page, figure/table label, panel label, caption hash/excerpt, image paths, and modality candidates.
6. Run image selection and quality checks for relevance, readability, duplicates, license status, and supported formats.
7. Link figures or panels to specimens and tensile records when evidence supports the mapping.
8. Generate review queues for OCR noise, figure-estimated values, ambiguous direction, long heat treatment, uncertain modality, uncertain licenses, and uncertain figure-specimen-property links.
9. Apply human review decisions, then rebuild the release.
10. Build public release tables, optional image package, no-image variant, schema, data dictionary, validation report, and README.

## Core Commands

Inventory a project:

```bash
python scripts/sync_pdf_inventory.py --project-root .
```

Extract figures for one PDF:

```bash
python scripts/extract_pdf_figures_pdffigures2.py --pdf-path <paper.pdf> --paper-id <paper_id> --pdffigures-jar <pdffigures2.jar>
```

Build the multimodal release with image paths and copied images when available:

```bash
python scripts/build_multimodal_release.py --project-root .
```

Build a no-image release when redistribution is uncertain:

```bash
python scripts/build_multimodal_release.py --project-root . --no-image --output-dir data/db/multimodal_release_no_image_v1
```

Generate a no-image Scientific Data style release from existing v2/v3 outputs:

```bash
python scripts/build_scidata_no_image_release.py --project-root .
```

Create visual review sheets for uncertain figure modality rows:

```bash
python scripts/build_figure_modality_visual_review_sheets.py --project-root .
```

## Expected Inputs

Use the templates in `templates/` rather than inventing new CSV shapes. A mature project should have:

- `data/db/v2/papers_v2.csv`
- `data/db/v2/specimens_v2.csv`
- `data/db/v2/tensile_records_v2.csv`
- `data/db/v2/microstructure_records_v2.csv`
- `data/metadata/figure_inventory.csv`
- optional `data/db/v3_image_ml/image_panels_v3.csv`
- optional `data/db/v3_image_ml/image_specimen_links_v3.csv`
- optional `data/metadata/source_license.csv`

## Core Outputs

The multimodal release builder creates:

- `papers.csv`
- `specimens.csv`
- `tensile_properties.csv`
- `microstructure_records.csv`
- `figure_index.csv`
- `figure_specimen_links.csv`
- `multimodal_ml_database.csv`
- `image_manifest.csv`
- `review_queue.csv`
- `data_dictionary.csv`
- `schema.json`
- `validation_report.csv`
- `README.md`

## References

Load only the files needed for the current task:

- `references/schema.md` for table and field expectations.
- `references/extraction_rules.md` before extracting specimen/tensile records.
- `references/modality_labels.md` before classifying figures or panels.
- `references/review_rules.md` before accepting uncertain records.
- `references/release_policy.md` before packaging public outputs with images.

## Public Release Policy

Default releases may include extracted images and crops, but every image row must carry DOI, source paper, figure label, crop provenance, license/status fields, and review status.

Always offer or generate a no-image release when copyright, journal policy, license metadata, or redistribution status is uncertain. Do not claim publication-ready status while `review_queue.csv` contains unresolved high-risk rows.

## Review Policy

Treat review queues as mandatory for:

- figure-estimated or digitized tensile values
- OCR-noisy values
- ambiguous test direction or heat treatment
- uncertain figure modality or image region
- uncertain figure-specimen-property links
- missing image files in an image-enabled release
- unknown or restrictive image redistribution status

Use `review_decision` and `review_notes` fields to record accepted, corrected, rejected, or deferred decisions before rebuilding final outputs.
