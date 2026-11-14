# Vegetation proposal and implementation

Source: SAT_SCOPE_Earth_System_Trend_Detective_Proposal.pdf in the repository.
Pages 1-2 describe MODIS NDVI and percentage change from a historical baseline.
Page 2 describes an individual vegetation endpoint and eventual compound features.
Page 3 supports prefetched, processed data for a 48-hour hackathon. The proposal
does not prescribe these baseline years, five countries or heavy model training.
The team has accepted Canberra as the vegetation pilot.

## Implementation

- `backend/ml/ndvi_pipeline.py`: raster discovery, scaling and QA; also retains
  the earlier regional-median implementation for reproducibility.
- `backend/ml/ndvi_candidate.py`: matched-pixel seasonal baseline and changes.
- `notebooks/SAT_SCOPE_NDVI_Candidate_Validation.ipynb`: Colab workflow using
  those same Python modules.
- `backend/services/ndvi_package.py`: complete v2 export validation.
- `backend/routers/ndvi.py`: authenticated summary, time-series, GeoJSON and
  combined review endpoints. Disabled unless a review package is configured.
- `frontend/src/components/NdviReview.jsx` and `.css`: Canberra presentation in
  the existing Australia/area selection workflow.
- `backend/ml/ndvi_dates.py`: limited December acquisition-day decoder for
  cross-sensor review, not a full-history acquisition-date correction.

The original global country catalog and teammates' analytics remain in place.
Canberra NDVI is distinct from the archive's soil-wetness indicator. Unavailable
Canberra indicators are shown as unavailable; NDVI is not joined to unrelated
country samples or used in compound analysis.

See [validation record](NDVI_AUDIT.md) for scientific limitations and
[local workflow](NDVI_NEXT_STEPS.md) for verification and review commands.
