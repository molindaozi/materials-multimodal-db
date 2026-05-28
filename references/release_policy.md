# Release Policy

The default workflow can build an image-enabled release. This does not mean every image is safe to redistribute.

For every image row, preserve:

- DOI
- source title or `paper_id`
- page number
- figure/table label
- panel label
- source path
- release path when copied
- checksum when file exists
- license status
- redistribution status
- review status

## Image-Enabled Release

Use image-enabled release only when the project policy allows local image assets to be packaged. Unknown license status must remain visible in `review_queue.csv` and `validation_report.csv`.

## No-Image Release

Generate a no-image release when copyright, journal policy, or image redistribution status is uncertain. The no-image release keeps DOI/page/figure/panel indexing and removes local image paths and image files.

## Public Database

Do not publish raw PDFs, full-text paper dumps, or long copyrighted captions unless explicitly permitted. Use caption hashes and short excerpts when needed for traceability.
