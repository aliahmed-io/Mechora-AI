"""Train the same six-feature classifiers with defensible user-selected holdouts."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import time
import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier,HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split,GroupShuffleSplit
from sklearn.metrics import precision_recall_curve,roc_curve
from sklearn.calibration import calibration_curve
from sklearn.inspection import permutation_importance
from threadpoolctl import threadpool_limits
from backend.ml.schema import FEATURES,NUMERIC,validate_frame
from backend.ml.context import extract_context
from backend.ml.train import metrics

def validate_training(frame):
    clean,summary=validate_frame(frame)
    if 'Machine failure' not in frame:raise ValueError('Include a Machine failure column containing confirmed 0/1 outcomes.')
    y=pd.to_numeric(frame['Machine failure'],errors='coerce')
    if y.isna().any() or not y.isin([0,1]).all():raise ValueError('Machine failure must contain only 0 and 1, with no missing labels.')
    if len(clean)<100 or y.value_counts().min()<10 or y.nunique()!=2:raise ValueError('Training needs at least 100 records and at least 10 records of each outcome.')
    context=extract_context(frame)
    return clean,y.astype(int),context,summary

def split_indices(frame,y,context,strategy):
    indices=np.arange(len(frame))
    if strategy=='random':
        dev,test=train_test_split(indices,test_size=.2,stratify=y,random_state=42)
        train,val=train_test_split(dev,test_size=.25,stratify=y.iloc[dev],random_state=42)
    elif strategy=='temporal':
        if not all(c.get('observed_at') for c in context):raise ValueError('A temporal split requires machine_id and timezone-aware observed_at on every row.')
        dates=pd.to_datetime([c['observed_at'] for c in context],utc=True)
        unique=np.sort(dates.unique())
        if len(unique)<10:raise ValueError('A temporal split requires at least 10 distinct observation timestamps.')
        first=unique[int(len(unique)*.6)];second=unique[int(len(unique)*.8)]
        train=indices[dates<first];val=indices[(dates>=first)&(dates<second)];test=indices[dates>=second]
    elif strategy=='machine':
        if not all(c.get('machine_id') for c in context):raise ValueError('A machine-held-out split requires machine_id and observed_at on every row.')
        groups=np.array([c['machine_id'] for c in context])
        if len(set(groups))<5:raise ValueError('A machine-held-out split requires at least five distinct machines.')
        dev,test=next(GroupShuffleSplit(n_splits=1,test_size=.2,random_state=42).split(indices,y,groups))
        ti,vi=next(GroupShuffleSplit(n_splits=1,test_size=.25,random_state=42).split(dev,y.iloc[dev],groups[dev]))
        train,val=dev[ti],dev[vi]
    else:raise ValueError('Choose random, temporal, or machine holdout.')
    for name,part in [('training',train),('validation',val),('test',test)]:
        if len(part)<10 or y.iloc[part].nunique()!=2:raise ValueError(f'The {name} split needs at least 10 rows and both failure outcomes. Collect more representative labels; do not rebalance the test set.')
    return train,val,test

def train_equipment(frame,strategy,directory,name,progress=lambda _:None):
    X,y,context,inspection=validate_training(frame)
    train,val,test=split_indices(X,y,context,strategy)
    Xtrain,Xval,Xtest=X.iloc[train],X.iloc[val],X.iloc[test]
    ytrain,yval,ytest=y.iloc[train],y.iloc[val],y.iloc[test]
    prep=ColumnTransformer([('type',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['Type']),('measurements',Pipeline([('imputer',SimpleImputer(strategy='median')),('scale',StandardScaler())]),NUMERIC)])
    algorithms={'Logistic Regression':LogisticRegression(class_weight='balanced',max_iter=2000,random_state=42),'Random Forest':RandomForestClassifier(n_estimators=250,min_samples_leaf=2,class_weight='balanced_subsample',n_jobs=1,random_state=42),'HistGradientBoosting':HistGradientBoostingClassifier(max_iter=200,max_leaf_nodes=15,learning_rate=.08,l2_regularization=1,random_state=42)}
    fitted={};comparison=[]
    with threadpool_limits(limits=1):
        for label,estimator in algorithms.items():
            progress(f'Training {label}')
            model=Pipeline([('preprocess',clone(prep)),('classifier',estimator)]).fit(Xtrain,ytrain)
            p=model.predict_proba(Xval)[:,1]
            precision,recall,thresholds=precision_recall_curve(yval,p)
            f1=2*precision[:-1]*recall[:-1]/np.maximum(precision[:-1]+recall[:-1],1e-12)
            threshold=float(thresholds[np.argmax(f1)])
            # A zero boundary cannot define a separate low/watch region.
            threshold=max(threshold,float(np.nextafter(0.,1.)))
            comparison.append({'name':label,'threshold':threshold,**metrics(yval,p,threshold)});fitted[label]=model
        chosen=max(comparison,key=lambda c:c['pr_auc']);model=fitted[chosen['name']];threshold=chosen['threshold']
        started=time.perf_counter();p=model.predict_proba(Xtest)[:,1];latency=(time.perf_counter()-started)*1000/len(Xtest)
        importance=permutation_importance(model,Xval,yval,n_repeats=5,scoring='average_precision',random_state=42,n_jobs=1)
        fpr,tpr,_=roc_curve(ytest,p);pr,rc,_=precision_recall_curve(ytest,p);actual,predicted=calibration_curve(ytest,p,n_bins=8,strategy='quantile')
        vp=model.predict_proba(Xval)[:,1]
        def points(a,b):
            ix=np.unique(np.linspace(0,len(a)-1,min(100,len(a))).astype(int));return [{'x':float(a[i]),'y':float(b[i])} for i in ix]
        audit={'strategy':strategy,'train_indices':train.tolist(),'validation_indices':val.tolist(),'test_indices':test.tolist()}
        if strategy=='machine':audit['machines']={key:sorted({context[i]['machine_id'] for i in part}) for key,part in [('train',train),('validation',val),('test',test)]}
        if strategy=='temporal':audit['time_ranges']={key:{'start':min(context[i]['observed_at'] for i in part),'end':max(context[i]['observed_at'] for i in part)} for key,part in [('train',train),('validation',val),('test',test)]}
        meta={'version':'equipment-1.0.0','trained_at':datetime.now(timezone.utc).isoformat(),'selected_model':chosen['name'],'selection_reason':f'Highest validation average precision using a {strategy} split; boundary maximizes validation F1. Separate test data is evaluated only after selection.','seed':42,'dataset':name,'data_origin':'User-supplied labeled data; external provenance and label quality are not independently verified.','dataset_sha256':hashlib.sha256(frame.to_csv(index=False).encode()).hexdigest(),'dataset_rows':len(X),'train_rows':len(train),'validation_rows':len(val),'test_rows':len(test),'failure_count':int(y.sum()),'split_failures':{'train':int(ytrain.sum()),'validation':int(yval.sum()),'test':int(ytest.sum())},'threshold':threshold,'watch_threshold':threshold/2,'features':FEATURES,'comparisons':comparison,'test_metrics':metrics(ytest,p,threshold),'latency_ms':latency,'feature_importance':[{'feature':c,'importance':float(v),'std':float(s)} for c,v,s in zip(FEATURES,importance.importances_mean,importance.importances_std)],'curves':{'roc':points(fpr,tpr),'precision_recall':points(rc,pr),'calibration':points(predicted,actual)},'threshold_tradeoffs':[{'threshold':float(t),**metrics(yval,vp,t)} for t in np.arange(.05,1,.05)],'training_distribution':{c:{'min':float(Xtrain[c].min()),'max':float(Xtrain[c].max()),'median':float(Xtrain[c].median()),'q05':float(Xtrain[c].quantile(.05)),'q95':float(Xtrain[c].quantile(.95))} for c in NUMERIC},'inspection':inspection,'split_audit':audit}
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    joblib.dump({'model':model,'reference':Xtrain[NUMERIC].median().to_dict(),'metadata':meta},directory/'model.joblib')
    (directory/'metrics.json').write_text(json.dumps(meta,indent=2),encoding='utf-8')
    return meta
