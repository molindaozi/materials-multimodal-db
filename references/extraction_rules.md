# Extraction Rules

## Source Corpus

Inventory PDFs and supplements before extraction. Keep raw PDFs outside public releases unless the user explicitly owns redistribution rights.

## Specimen-Centric Extraction

Create one `specimen_id` per reported material condition. Prefer a stable record at the source-condition level rather than one row per sentence.

Capture:

- material/alloy/composition label
- manufacturing or processing route
- build direction or sample orientation
- heat treatment and post-processing
- specimen geometry when reported
- microstructure evidence
- source locator: DOI, page, section, table, figure, or caption

## Tensile Properties

Extract these fields by default:

- yield strength, MPa
- ultimate tensile strength, MPa
- elongation, percent
- test temperature, Celsius
- test direction or orientation
- source form: table, text, digitized figure, figure estimate, or unspecified
- confidence and review status

Do not treat Young's modulus or full stress-strain curve digitization as default unless the user asks.

## Figure and Caption Extraction

Use `pdffigures2` when available to extract captions and crops. Keep the raw tool output and a normalized manifest.

For each figure/table/panel candidate, capture:

- `paper_id`
- DOI when available
- figure/table label
- panel label
- page number
- caption text or caption hash
- page image path
- crop image path
- crop method
- confidence

## Linking Rules

Link a figure to a specimen or tensile record only when the paper text, caption, table, or explicit label supports the relation. Otherwise create a review queue row instead of inventing a link.
