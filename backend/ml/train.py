"""Reproduce with: python -m backend.ml.train. No test-set model selection."""
from pathlib import Path
import hashlib
import json
import time
from datetime import datetime, timezone
import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.inspection import permutation_importance
from sklearn.metrics import (average_precision_score, roc_auc_score, precision_score, recall_score, f1_score, confusion_matrix, precision_recall_curve, roc_curve, brier_score_loss)
from sklearn.calibration import calibration_curve
from backend.ml.schema import FEATURES, NUMERIC

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / 'artifacts'

def metrics(y, p, threshold):
    pred = p >= threshold
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0,1]).ravel()
    return {'precision':float(precision_score(y,pred,zero_division=0)), 'recall':float(recall_score(y,pred)), 'f1':float(f1_score(y,pred)), 'roc_auc':float(roc_auc_score(y,p)), 'pr_auc':float(average_precision_score(y,p)), 'false_positive_rate':float(fp/(fp+tn)), 'brier_score':float(brier_score_loss(y,p)), 'confusion_matrix':[[int(tn),int(fp)],[int(fn),int(tp)]]}

def train():
    ARTIFACTS.mkdir(exist_ok=True)
    source = ROOT/'datasets'/'ai4i2020.csv'
    df = pd.read_csv(source)
    X,y = df[FEATURES], df['Machine failure']
    Xdev,Xtest,ydev,ytest = train_test_split(X,y,test_size=.2,stratify=y,random_state=42)
    Xtrain,Xval,ytrain,yval = train_test_split(Xdev,ydev,test_size=.25,stratify=ydev,random_state=42)
    prep = ColumnTransformer([('type',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['Type']),('measurements',Pipeline([('imputer',SimpleImputer(strategy='median')),('scale',StandardScaler())]),NUMERIC)])
    algorithms = {'Logistic Regression':LogisticRegression(class_weight='balanced',max_iter=2000,random_state=42), 'Random Forest':RandomForestClassifier(n_estimators=250,min_samples_leaf=2,class_weight='balanced_subsample',random_state=42,n_jobs=-1), 'HistGradientBoosting':HistGradientBoostingClassifier(max_iter=200,max_leaf_nodes=15,learning_rate=.08,l2_regularization=1,random_state=42)}
    models, comparisons = {}, []
    for name, estimator in algorithms.items():
        model=Pipeline([('preprocess',clone(prep)),('classifier',estimator)])
        model.fit(Xtrain,ytrain)
        p=model.predict_proba(Xval)[:,1]
        precision,recall,thresholds=precision_recall_curve(yval,p)
        scores=2*precision[:-1]*recall[:-1]/np.maximum(precision[:-1]+recall[:-1],1e-12)
        threshold=float(thresholds[int(np.argmax(scores))])
        comparisons.append({'name':name,'threshold':threshold,**metrics(yval,p,threshold)})
        models[name]=model
        print(name,comparisons[-1],flush=True)
    selected=max(comparisons,key=lambda m:m['pr_auc'])
    model=models[selected['name']]
    threshold=selected['threshold']
    start=time.perf_counter(); p=model.predict_proba(Xtest)[:,1]; latency=(time.perf_counter()-start)*1000/len(Xtest)
    importance=permutation_importance(model,Xval,yval,n_repeats=5,scoring='average_precision',random_state=42,n_jobs=1)
    fpr,tpr,_=roc_curve(ytest,p); pr,rc,_=precision_recall_curve(ytest,p)
    actual,predicted=calibration_curve(ytest,p,n_bins=8,strategy='quantile')
    def compact(a,b,limit=100):
        ix=np.unique(np.linspace(0,len(a)-1,min(limit,len(a))).astype(int))
        return [{'x':float(a[i]),'y':float(b[i])} for i in ix]
    metadata={'version':'mechora-1.0.0','trained_at':datetime.now(timezone.utc).isoformat(),'selected_model':selected['name'],'selection_reason':'Highest validation average precision (PR-AUC); classification threshold maximizes validation F1. Test data is untouched until final evaluation.','seed':42,'dataset':'UCI AI4I 2020','dataset_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'dataset_rows':len(df),'train_rows':len(Xtrain),'validation_rows':len(Xval),'test_rows':len(Xtest),'failure_count':int(y.sum()),'split_failures':{'train':int(ytrain.sum()),'validation':int(yval.sum()),'test':int(ytest.sum())},'threshold':threshold,'watch_threshold':threshold/2,'features':FEATURES,'comparisons':comparisons,'test_metrics':metrics(ytest,p,threshold),'latency_ms':latency,'feature_importance':[{'feature':c,'importance':float(v),'std':float(s)} for c,v,s in zip(FEATURES,importance.importances_mean,importance.importances_std)],'curves':{'roc':compact(fpr,tpr),'precision_recall':compact(rc,pr),'calibration':compact(predicted,actual)},'threshold_tradeoffs':[{'threshold':round(float(t),2),**metrics(yval,model.predict_proba(Xval)[:,1],t)} for t in np.arange(.05,1,.05)],'training_distribution':{c:{'min':float(Xtrain[c].min()),'max':float(Xtrain[c].max()),'median':float(Xtrain[c].median()),'q05':float(Xtrain[c].quantile(.05)),'q95':float(Xtrain[c].quantile(.95))} for c in NUMERIC},'inspection':{'missing_values':int(df.isna().sum().sum()),'duplicate_feature_rows':int(X.duplicated().sum()),'class_distribution':y.value_counts().to_dict(),'correlations':X[NUMERIC].corr().round(4).to_dict()}}
    joblib.dump({'model':model,'reference':Xtrain[NUMERIC].median().to_dict(),'metadata':metadata},ARTIFACTS/'model.joblib')
    (ARTIFACTS/'metrics.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    # A held-out demonstration CSV, never training records.
    Xtest.to_csv(ROOT/'public'/'sample-observations.csv',index=False)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,3,figsize=(15,4))
    for ax,key,title in zip(axes,['roc','precision_recall','calibration'],['ROC curve','Precision–recall','Probability calibration']):
        curve=metadata['curves'][key];ax.plot([v['x'] for v in curve],[v['y'] for v in curve],color='#751726');ax.set_title(title);ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(ARTIFACTS/'evaluation.png',dpi=150);plt.close(fig)
    print('Saved selected model:',selected['name'],'test:',metadata['test_metrics'],flush=True)

if __name__=='__main__': train()
