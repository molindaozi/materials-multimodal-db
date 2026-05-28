# Review Rules

Generate review queue rows for:

- OCR noise or malformed numeric values.
- Tensile values estimated from figures.
- Values with unclear mean/single/representative status.
- Ambiguous test direction or build direction.
- Long or multi-step heat treatments that cannot be normalized safely.
- Figure modality conflicts or unclassified figures.
- Missing image files in an image-enabled release.
- Unknown image redistribution status.
- Figure-specimen-property links without explicit support.

## Review Decisions

Use these decision values:

- `accepted`
- `corrected`
- `rejected`
- `deferred`

Use `review_notes` for short key-value corrections, for example:

```text
direction=Z; heat_treatment=solution + aging; confidence=high
```

Do not remove unresolved review rows from the queue unless the source data was corrected and the release was rebuilt.
