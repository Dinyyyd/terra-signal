# Vegetation proposal review and integration status

Source: SAT_SCOPE_Earth_System_Trend_Detective_Proposal.pdf in this repository.

Pages 1–2 specify MODIS NDVI and percentage change from a baseline. Page 2
specifies an individual vegetation endpoint and an eventual compound feature
vector containing NDVI percentage change. Page 3 explicitly supports prefetched,
processed observations and cached local presentation for a 48-hour hackathon.
Heavy training, real-time downloads, five countries and particular baseline years
are not requirements in the PDF. The five-country scope is a later team decision.

## Implemented foundation

- `ml/ndvi_pipeline.py` provides the shared raster reader with scaling and QA.
- `ml/ndvi_candidate.py` computes seasonal matched-pixel medians and descriptive
  changes, requiring sufficient historical support and coverage.
- The candidate Colab notebook uses these same modules.
- `ml/ndvi_dates.py` decodes the December 2025 acquisition-day rollover for
  cross-sensor review. It is deliberately not a general all-year decoder.
- An authenticated `/api/ndvi/canberra` review endpoint is disabled by default.
  To review locally, set SATSCOPE_NDVI_REVIEW_DIR to a trusted candidate export
  folder containing candidate_latest.json. It does not feed compound analysis.
  Non-reportable values remain null. Existing soil-wetness routes are unchanged.

## Remaining integration work

1. Validate export identity, geometry, finite numeric values, provenance and full
   schema before enabling a production adapter; current endpoint is local review.
2. Connect a labelled NDVI time-series/map panel and the proposal's vegetation
   API contract without replacing soil wetness or fabricating matching grid IDs.
3. Surface composite-period labels separately from actual acquisition ranges.
   Historical candidate exports lack full-record acquisition-day data. Do not
   claim strict calendar-year splits or complete year-boundary correction.
4. Import and verify the existing Canberra candidate as observed pilot data;
   acquire small matched seasonal datasets for other country study areas.
5. Run full frontend and API integration checks before push of a completed feature.

Deployment is not approved. Descriptive NDVI differences are not independently
validated vegetation damage. The existing candidate's 80% coverage rule is a
provisional reporting policy, not a calibrated accuracy criterion.
