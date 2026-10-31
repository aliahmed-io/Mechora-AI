"""Keep each saved prediction and explanation linked to the model that produced it."""
from pathlib import Path
import hashlib
import json
import shutil
import threading
import joblib
import numpy as np
import pandas as pd
from fastapi import HTTPException
from backend.app.database import Session, ModelMetadata
from backend.ml.schema import FEATURES

ARTIFACTS=Path(__file__).resolve().parents[2]/'artifacts'
_bundle=None
_lock=threading.RLock()

def load_bundle(path):
    try:
        b=joblib.load(path)
        if list(b['model'].feature_names_in_)!=FEATURES:raise ValueError('Feature schema mismatch')
        meta=b['metadata']
        if meta['features']!=FEATURES or not 0<=meta['watch_threshold']<meta['threshold']<=1:raise ValueError('Invalid model metadata')
        probe=pd.DataFrame([{'Type':'M',**b['reference']}])[FEATURES]
        p=b['model'].predict_proba(probe)
        if p.shape!=(1,2) or not np.isfinite(p).all():raise ValueError('Model prediction failed')
        return b
    except Exception as exc:
        raise HTTPException(503,'The trained model could not be loaded. Run python -m backend.ml.train with the project dependencies, then restart the backend.') from exc

def get_model():
    global _bundle
    with _lock:
        if _bundle is None:
            path=ARTIFACTS/'model.joblib'
            if not path.exists():raise HTTPException(503,'Train the model first: python -m backend.ml.train')
            b=load_bundle(path)
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            archive=ARTIFACTS/'models';archive.mkdir(exist_ok=True)
            archived=archive/f'{digest}.joblib'
            if not archived.exists():shutil.copyfile(path,archived)
            meta={**b['metadata'],'artifact_sha256':digest,'version':f"{b['metadata']['version']}-{digest[:10]}"}
            with Session() as session:
                if not session.get(ModelMetadata,meta['version']):session.add(ModelMetadata(id=meta['version'],metadata_json=json.dumps(meta)))
                # Recognize existing course-demo records by their exact training provenance.
                legacy=session.get(ModelMetadata,b['metadata']['version'])
                if legacy:
                    old=json.loads(legacy.metadata_json)
                    if old.get('trained_at')==meta.get('trained_at') and old.get('dataset_sha256')==meta.get('dataset_sha256'):
                        legacy.metadata_json=json.dumps({**old,'artifact_sha256':digest})
                session.commit()
            _bundle={**b,'metadata':meta}
        return _bundle

def saved_metadata(session,version):
    row=session.get(ModelMetadata,version)
    return json.loads(row.metadata_json) if row else {'version':version,'selected_model':'Historical model'}

def model_for_analysis(session,run):
    current=get_model()
    meta=saved_metadata(session,run.model_version)
    digest=meta.get('artifact_sha256')
    if digest==current['metadata']['artifact_sha256']:return current
    if digest and len(digest)==64 and all(c in '0123456789abcdef' for c in digest):
        path=ARTIFACTS/'models'/f'{digest}.joblib'
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==digest:return load_bundle(path)
    raise HTTPException(409,'The original model for this saved analysis is unavailable. Its recorded results and exports remain accessible. Run a new analysis to inspect explanations.')
