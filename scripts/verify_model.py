"""Independently reproduce saved metrics without training or changing the model."""
from pathlib import Path
import json
import sys
import joblib
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from threadpoolctl import threadpool_limits
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.ml.schema import FEATURES,NUMERIC
from backend.ml.train import metrics

def verify():
    root=Path(__file__).resolve().parents[1]
    bundle=joblib.load(root/'artifacts'/'model.joblib');meta=bundle['metadata']
    frame=pd.read_csv(root/'datasets'/'ai4i2020.csv');X,y=frame[FEATURES],frame['Machine failure']
    dev,test,ydev,ytest=train_test_split(X,y,test_size=.2,stratify=y,random_state=42)
    train,val,ytrain,yval=train_test_split(dev,ydev,test_size=.25,stratify=ydev,random_state=42)
    assert set(train.index).isdisjoint(val.index) and set(train.index).isdisjoint(test.index) and set(val.index).isdisjoint(test.index)
    assert list(bundle['model'].feature_names_in_)==FEATURES
    np.testing.assert_allclose(bundle['model']['preprocess'].named_transformers_['measurements']['scale'].mean_,train[NUMERIC].mean().values)
    sample=pd.read_csv(root/'public'/'sample-observations.csv')
    pd.testing.assert_frame_equal(test.reset_index(drop=True),sample,check_dtype=False)
    with threadpool_limits(limits=1):
        actual=metrics(ytest,bundle['model'].predict_proba(test)[:,1],meta['threshold'])
        selected=next(c for c in meta['comparisons'] if c['name']==meta['selected_model'])
        validation=metrics(yval,bundle['model'].predict_proba(val)[:,1],meta['threshold'])
    for key,value in actual.items():np.testing.assert_allclose(value,meta['test_metrics'][key],rtol=1e-10,atol=1e-10)
    for key,value in validation.items():np.testing.assert_allclose(value,selected[key],rtol=1e-10,atol=1e-10)
    assert selected['pr_auc']==max(c['pr_auc'] for c in meta['comparisons'])
    result={'status':'passed','checks':['disjoint stratified splits','six-feature input schema','training-only scaling','held-out sample provenance','independently reproduced test metrics','independently reproduced selected validation metrics','validation-only selection criterion'],'test_metrics':actual}
    return result

if __name__=='__main__':print(json.dumps(verify(),indent=2))
