# Materials Multimodal DB

`materials-multimodal-db` is a Codex skill for building specimen-centric multimodal materials literature databases from scientific PDFs. It supports source-corpus inventory, figure/table/caption indexing, image extraction and cropping, tensile-property extraction, microstructure evidence records, figure-specimen-property links, review queues, validation reports, and reusable release tables.

## Affiliation


- Institution: Tsinghua University
- Research context: materials literature mining, microstructure-property databases, and multimodal scientific data extraction
- Maintainer: `molindaozi`


## What This Skill Does

- Inventories PDF papers and supplementary files.
- Extracts figure/table captions, page images, and figure crops.
- Builds specimen-centric records for material, process, build direction, heat treatment, test condition, and microstructure evidence.
- Extracts tensile properties such as YS, UTS, elongation, test temperature, direction, value source, and confidence.
- Creates figure indexes with DOI, page, figure/table label, panel label, caption hash/excerpt, image paths, and modality candidates.
- Links figures or panels to specimens and tensile records when the source evidence supports the mapping.
- Generates review queues for OCR noise, figure-estimated values, ambiguous directions, uncertain modalities, license issues, and uncertain figure-specimen-property links.
- Builds both image-enabled and no-image release variants.

## Repository Structure

```text
SKILL.md
agents/
scripts/
references/
templates/
examples/
requirements.txt
```

`SKILL.md` is the entry point used by Codex. The `scripts/` directory contains reusable automation. The `references/` and `templates/` directories define the expected schema, review rules, release policy, and CSV layouts.

## Quick Start

Install Python dependencies:

```bash
pip install -r requirements.txt
```

Run the synthetic example with image outputs:

```bash
python scripts/build_multimodal_release.py --project-root examples/synthetic_project
```

Run the synthetic example as a no-image release:

```bash
python scripts/build_multimodal_release.py --project-root examples/synthetic_project --no-image --output-dir data/db/multimodal_release_no_image_v1
```

## Public Release Note

The example data in this repository is synthetic and can be shared. Do not publish real PDFs, copyrighted figures, extracted page images, or figure crops unless redistribution rights are confirmed. Use the no-image release path when copyright or license status is uncertain.

## Codex Usage

After installing this skill in a Codex skills directory, invoke it as:

```text
$materials-multimodal-db
```

