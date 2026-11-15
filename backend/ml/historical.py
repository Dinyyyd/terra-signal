"""Persisted country-specific historical inference; no fitting at request time."""
import json
from functools import lru_cache
import joblib
import numpy as np
import config

@lru_cache(maxsize=1)
def manifest():
    return json.loads((config.ROOT/'training/models/manifest.json').read_text())

@lru_cache(maxsize=8)
def load_model(country):
    return joblib.load(config.ROOT/'training/models'/manifest()['countries'][country]['model'])

def apply_models(matrix, countries, outlier, score, drivers):
    methods=['spatial snapshot (not historical model)']*len(countries)
    for country in manifest()['countries']:
        idx=np.array([i for i,c in enumerate(countries) if c==country],dtype=int)
        if not len(idx): continue
        model=load_model(country); x=matrix[idx]; scaled=model[0].transform(x)
        outlier[idx]=model.predict(x)==-1; score[idx]=-model.score_samples(x)
        names=[('warmer than baseline','cooler than baseline'),('wetter soil than baseline','drier soil than baseline'),('wetter than normal','rainfall deficit')]
        for k,i in enumerate(idx):
            drivers[i]=[names[j][0 if scaled[k,j]>=0 else 1] for j in np.argsort(-abs(scaled[k]))[:2] if abs(scaled[k,j])>=1]
            methods[i]='historical country Isolation Forest (fit 2021–2023)'
    return methods
