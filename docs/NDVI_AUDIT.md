# Canberra NDVI validation record

## Implemented checks

Candidate version 2 rejects invalid thresholds, masks and scaled NDVI values.
The shared package validator checks source hashes, study geometry, configured
policy, dates, summary/time-series agreement, pixel calculations and map medians.
Authenticated API routes all read through this validator; malformed or absent
packages return unavailable responses. The command-line checker uses it too.

Tests cover known-answer calculations, missing history, low baseline, coverage
boundaries, raster alignment, corrupt packages, authentication and API responses.
The frontend presents unavailable observations as gaps, not zero NDVI.

## Observed candidate

The saved v2 latest composite label is 2025-12-19: current NDVI approximately
0.4382, baseline 0.5433, change -19.34%, matched coverage 92.50%.
These are matched-location seasonal comparisons, not a model accuracy score.
Source calculations are shared between Colab and the backend.

## Scientific limitations

- Full-history pixel acquisition dates are not used by the candidate. Seasonal
  composite labels are used; December pixels can include next-year acquisitions.
- Original raster hashes and reruns require the full dataset in Drive. Package
  validation checks internal consistency, not authenticity of the observations.
- Missing periods are not interpolated; latest available need not be latest expected.
- QA-accepted pixels include different land-cover types. Lower NDVI does not
  independently establish vegetation damage or its cause.
- The 80% coverage and 0.1 baseline limits are provisional reporting policies.
  Regional medians can hide local changes.
- HLS comparisons cover subsets and assess sensor agreement. They do not validate
  historical decline or establish an ecological accuracy percentage.
- Canberra is excluded from compound analysis until geography and time align
  with independently available observations for the other indicators.

The local review is implemented. Production deployment is not approved. Browser
acceptance checks remain necessary after frontend changes.
