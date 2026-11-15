"""Reproduce historical models from the bundled NASA POWER archive."""
import json, pathlib, statistics, sys
import numpy as np
import pandas as pd
from scipy.stats import norm
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import IsolationForest
import joblib, sklearn
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'training'; DATA=OUT/'datasets'; MODELS=OUT/'models'
COUNTRIES=['United States of America','Australia','India','United Kingdom','Sri Lanka']
FEATURES=['z_temp','soil_delta_pct','z_rain']
def main():
    DATA.mkdir(exist_ok=True); MODELS.mkdir(exist_ok=True)
    archive=json.loads((ROOT/'data/history/nasa_power_global_monthly_2011_2025.json').read_text())
    rows=[]; baselines=[]
    for c in archive['cells']:
        if c.get('country') not in COUNTRIES: continue
        for month in range(1,13):
            base=[r for r in c['series'] if int(r['date'][:4])<=2020 and int(r['date'][5:])==month]
            t=[r['temperature_c'] for r in base]; w=[r['root_zone_soil_wetness'] for r in base]; p=[r['precipitation_mm_day'] for r in base]
            tm=statistics.fmean(t); ts=statistics.pstdev(t) or .5; wm=statistics.fmean(w)
            baselines.append(dict(cell_id=c['id'],month=month,temp_mean=tm,temp_sigma=ts,soil_mean=wm,rain_values=p))
            for r in c['series']:
                if int(r['date'][5:])!=month: continue
                rain=r['precipitation_mm_day']; pct=100*(sum(v<rain for v in p)+.5*sum(v==rain for v in p))/len(p)
                rows.append(dict(country=c['country'],area=c.get('area'),cell_id=c['id'],lat=c['lat'],lon=c['lon'],**r,z_temp=(r['temperature_c']-tm)/ts,soil_delta_pct=(r['root_zone_soil_wetness']-wm)/abs(wm)*100 if wm else 0,z_rain=norm.ppf(np.clip(pct,.5,99.5)/100),rain_percentile=pct))
    df=pd.DataFrame(rows).sort_values(['country','cell_id','date']); df.to_csv(DATA/'power_observations_features.csv',index=False)
    (MODELS/'seasonal_baselines.json').write_text(json.dumps(baselines))
    report={'sklearn_version':sklearn.__version__,'baseline':'2011–2020','fit':'2021–2023','holdout':'2024–2025','features':FEATURES,'countries':{},'limitations':'Unsupervised; no ground truth. Soil wetness is not NDVI. No historical fire or LST.'}
    for country,g in df.groupby('country'):
        train=g[g.date.str[:4].between('2021','2023')]; test=g[g.date.str[:4].between('2024','2025')].copy()
        model=make_pipeline(StandardScaler(),IsolationForest(n_estimators=200,contamination=.08,random_state=42,n_jobs=1)).fit(train[FEATURES].to_numpy())
        filename=country.lower().replace(' ','_')+'.joblib'; joblib.dump(model,MODELS/filename)
        test['anomaly']=model.predict(test[FEATURES].to_numpy())==-1; test['score']=-model.score_samples(test[FEATURES].to_numpy()); test.to_csv(DATA/(filename.replace('.joblib','_holdout.csv')),index=False)
        report['countries'][country]={'cells':int(g.cell_id.nunique()),'fit_rows':len(train),'holdout_rows':len(test),'holdout_anomaly_fraction':float(test.anomaly.mean()),'model':filename}
    (MODELS/'manifest.json').write_text(json.dumps(report,indent=2)); print(json.dumps(report,indent=2))
if __name__=='__main__': main()
