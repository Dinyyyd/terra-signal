# Running the Canberra vegetation component

Canberra is the agreed pilot. Additional countries are not required for this
contribution. Keep the original website country catalog and other indicators.

## Local verification

Run from the repository root in PowerShell:

```powershell
.\.venv\Scripts\python.exe backend/scripts/verify_ndvi_export.py data/local_ndvi_research/20261114T174019816157Z_candidate_v2_review.zip
.\.venv\Scripts\python.exe -m pytest backend/tests -q
npm --prefix frontend run build
```

The checker and API use the same package validator. A standalone summary is not
a complete export. Keep research ZIPs and raw rasters out of Git.

## Local review

Set `SATSCOPE_NDVI_REVIEW_PACKAGE` to the v2 ZIP in the backend terminal, then
start the backend. Use the root `.venv/Scripts/python.exe` interpreter.
Select Australia, then Canberra (MODIS study area) in the website. Check the
summary, time series, missing-data explanation and map. Other locations should
retain their existing dashboard behavior.

No package configured means NDVI is unavailable. The NDVI feature does not
supply temperature, rainfall, fire or compound-anomaly results for Canberra.

## Before sharing

Review the diff against upstream, repeat browser checks at desktop and mobile
sizes, and confirm that the original countries remain available. Software tests
and package consistency do not establish ecological accuracy. See NDVI_AUDIT.md.
Commit, push and deployment remain separate actions awaiting the user's request.
No new Colab run is needed for UI or API-only changes; changes to the scientific
pipeline require a new versioned export with matching source hashes.
