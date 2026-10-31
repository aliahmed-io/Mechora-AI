"""Persistent training jobs and explicit activation of evaluated candidate models."""
from pathlib import Path
import io
import csv
import json
import shutil
import threading
from uuid import uuid4
from datetime import datetime,timezone
import pandas as pd
from fastapi import APIRouter,UploadFile,File,Form,HTTPException
from backend.app.database import Session,TrainingRun
from backend.app.model_store import ARTIFACTS,load_bundle
from backend.ml.equipment_training import validate_training,split_indices,train_equipment

router=APIRouter(prefix='/api/training')
training_lock=threading.Lock()
def run_dict(row):return {'id':row.id,'name':row.name,'strategy':row.strategy,'status':row.status,'created_at':row.created_at,'summary':json.loads(row.summary_json),'metrics':json.loads(row.metrics_json) if row.metrics_json else None,'error':row.error or ''}

def execute_training(id):
    if not training_lock.acquire(blocking=False):
        with Session() as session:
            row=session.get(TrainingRun,id);row.status='failed';row.error='Another training run is active. Try again after it finishes.';session.commit()
        return
    try:
        folder=ARTIFACTS/'experiments'/id
        with Session() as session:
            row=session.get(TrainingRun,id);row.status='running';session.commit();strategy=row.strategy;name=row.name
        def progress(message):
            with Session() as session:
                row=session.get(TrainingRun,id);summary=json.loads(row.summary_json);summary['progress']=message;row.summary_json=json.dumps(summary);session.commit()
        meta=train_equipment(pd.read_csv(folder/'source.csv'),strategy,folder,name,progress)
        with Session() as session:
            row=session.get(TrainingRun,id);row.status='completed';row.metrics_json=json.dumps(meta);session.commit()
    except Exception as exc:
        with Session() as session:
            row=session.get(TrainingRun,id);row.status='failed';row.error=str(exc)[:1000];session.commit()
    finally:training_lock.release()

@router.post('/runs')
async def start_training(file:UploadFile=File(...),strategy:str=Form('temporal')):
    if not file.filename or not file.filename.lower().endswith('.csv'):raise HTTPException(422,'Choose a labeled CSV file.')
    data=await file.read(5*1024*1024+1)
    if len(data)>5*1024*1024:raise HTTPException(413,'Training CSV must be 5 MB or smaller.')
    try:
        decoded=data.decode('utf-8-sig');reader=csv.reader(io.StringIO(decoded),strict=True);headers=next(reader)
        if len(headers)!=len(set(headers)):raise ValueError('Duplicate training CSV columns are not allowed.')
        if any(len(row)!=len(headers) for row in reader if row and any(c.strip() for c in row)):raise ValueError('Every training CSV row must match the header field count.')
        frame=pd.read_csv(io.StringIO(decoded))
        X,y,context,summary=validate_training(frame);parts=split_indices(X,y,context,strategy)
    except (ValueError,UnicodeError,csv.Error,StopIteration) as exc:raise HTTPException(422,str(exc) or 'The training CSV is empty or malformed.')
    id=str(uuid4());folder=ARTIFACTS/'experiments'/id;folder.mkdir(parents=True)
    frame.to_csv(folder/'source.csv',index=False)
    summary={**summary,'failure_count':int(y.sum()),'splits':[len(p) for p in parts],'progress':'Queued'}
    with Session() as session:
        row=TrainingRun(id=id,name=Path(file.filename.replace('\\','/')).name[:160],strategy=strategy,status='queued',created_at=datetime.now(timezone.utc).isoformat(),summary_json=json.dumps(summary),error='')
        session.add(row);session.commit();result=run_dict(row)
    threading.Thread(target=execute_training,args=(id,),daemon=True).start();return result

@router.get('/runs')
def training_runs():
    with Session() as session:return [run_dict(r) for r in session.query(TrainingRun).order_by(TrainingRun.created_at.desc()).limit(30)]

@router.get('/runs/{id}')
def training_run(id:str):
    with Session() as session:
        row=session.get(TrainingRun,id)
        if not row:raise HTTPException(404,'Training run not found.')
        return run_dict(row)

@router.post('/runs/{id}/activate')
def activate(id:str):
    with Session() as session:
        row=session.get(TrainingRun,id)
        if not row or row.status!='completed':raise HTTPException(409,'Only a completed, evaluated training run can be activated.')
    from backend.app import model_store
    with model_store._lock:
        model_store.get_model()  # Archive the current model before replacing it.
        candidate=ARTIFACTS/'experiments'/row.id/'model.joblib';load_bundle(candidate)
        temporary=ARTIFACTS/'model.pending.joblib';shutil.copyfile(candidate,temporary);temporary.replace(ARTIFACTS/'model.joblib')
        shutil.copyfile(candidate.parent/'metrics.json',ARTIFACTS/'metrics.json')
        model_store._bundle=None
        return {'model':model_store.get_model()['metadata'],'message':'This trained model is now used for new predictions. Previous analyses retain their original models.'}

@router.get('/versions')
def versions():
    from backend.app.database import ModelMetadata
    from backend.app.model_store import get_model
    active=get_model()['metadata']['version']
    with Session() as session:
        result=[]
        for row in session.query(ModelMetadata):
            meta=json.loads(row.metadata_json);digest=meta.get('artifact_sha256')
            if digest and (ARTIFACTS/'models'/f'{digest}.joblib').exists():result.append({'version':row.id,'dataset':meta.get('dataset','Unknown'),'model':meta.get('selected_model','Unknown'),'active':row.id==active})
        return result

@router.post('/versions/{version}/activate')
def restore_version(version:str):
    from types import SimpleNamespace
    from backend.app import model_store
    from backend.app.database import ModelMetadata
    with model_store._lock,Session() as session:
        original=model_store.model_for_analysis(session,SimpleNamespace(model_version=version))
        row=session.get(ModelMetadata,version)
        if not row:raise HTTPException(404,'Model version not found.')
        digest=json.loads(row.metadata_json)['artifact_sha256'];source=ARTIFACTS/'models'/f'{digest}.joblib'
        pending=ARTIFACTS/'model.pending.joblib';shutil.copyfile(source,pending);pending.replace(ARTIFACTS/'model.joblib')
        (ARTIFACTS/'metrics.json').write_text(json.dumps(original['metadata'],indent=2),encoding='utf-8')
        model_store._bundle=None
        return {'model':model_store.get_model()['metadata']}
