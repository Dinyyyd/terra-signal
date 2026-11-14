# Two-day hackathon scope

This is an initial historical-data prototype, not a real-time satellite service.
The default archive is restricted to Sri Lanka, United States of America,
United Kingdom, Australia and India. Original source values and baseline years
are preserved. Rebuild with `python backend/scripts/build_hackathon_subset.py`.
The full archive is retained for reproducibility; it is not loaded by default.

The coarse source grid has no Sri Lanka sample. Sri Lanka remains selectable
with unavailable data; neither interpolation nor mock observations fill this gap.
Country selections summarize available sample cells, not complete national coverage.

## Vegetation component

The existing dashboard archive contains NASA POWER root-zone soil wetness.
It is NOT MODIS NDVI. Do not present it as the vegetation proposal implementation.
The separately developed Canberra MOD13Q1 candidate remains offline and has not
been deployed into this repository. Its historical percentage change is not yet
independently validated.

For a small NDVI demonstration, use one explicitly named study polygon in each
requested country, three corresponding seasonal composites per year for
2020–2024, and the same three periods in 2025. This is a proposed acquisition
plan, not existing five-country NDVI coverage. Keep NDVI, pixel reliability,
VI Quality and composite acquisition day for each observation. Preserve actual
acquisition years at year boundaries. Process with the same matched-pixel code;
do not train a new model or pool baselines across countries. Label results as
study-area pilots, not national estimates. Australia can reuse Canberra.

Stop expanding the HLS validation download for the hackathon. Retain the existing
date-matched diagnostics and state their coverage and limits. Avoid claims of
validated ecological decline, prediction accuracy or real-time operation.
Production deployment remains on hold. A local prototype is suitable for
explaining the method and showing clearly labelled historical observations.
