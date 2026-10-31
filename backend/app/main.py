from datetime import datetime, timezone
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4
import csv
import io
import json
import threading
import numpy as np
import pandas as pd
from threadpoolctl import threadpool_limits
from fastapi import FastAPI, File, HTTPException, UploadFile, Query, Request
from fastapi.responses import Response, JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy import text
from pydantic import BaseModel, Field, model_validator


from backend.app.database import Session, Dataset, Analysis, Report, ModelMetadata
from backend.ml.schema import FEATURES, NUMERIC, ALIASES, validate_frame, risk_level
from backend.ml.context import extract_context
from backend.app.model_store import get_model, model_for_analysis, saved_metadata

ROOT=Path(__file__).resolve().parents[2]
# Small tabular batches are faster and more predictable without nested BLAS/OpenMP pools.
threadpool_limits(limits=1)
inference_lock=threading.Lock()

def now(): return datetime.now(timezone.utc).isoformat()
def ident(): return str(uuid4())

@asynccontextmanager
async def lifespan(app):
    from backend.app.operations import pause_interrupted_work
    pause_interrupted_work()
    yield

app=FastAPI(title='Mechora AI',version='1.1.0',lifespan=lifespan,description='Predictive-maintenance showcase: batch and timestamped observations, recorded-data replay, maintenance investigations, and equipment-data training.')

@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    return JSONResponse({'detail':[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()]},status_code=422)

@app.middleware('http')
async def local_origin(request:Request,call_next):
    origin=request.headers.get('origin','')
    if request.method in ('POST','PUT','PATCH','DELETE') and origin and origin not in ('http://localhost:3000','http://127.0.0.1:3000','http://localhost:8001','http://127.0.0.1:8001'):
        return Response('Origin not allowed',status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    return response

def get_dataset(session,id):
    ds=session.get(Dataset,id)
    if not ds: raise HTTPException(404,'Dataset not found.')
    return ds
def get_analysis(session,id):
    run=session.get(Analysis,id)
    if not run: raise HTTPException(404,'Analysis not found.')
    return run
def ds_info(ds): return {'id':ds.id,'name':ds.name,'created_at':ds.created_at,**json.loads(ds.summary_json)}
def run_info(run,session):
    records=json.loads(run.predictions_json)
    return {'id':run.id,'dataset_id':run.dataset_id,'dataset_name':get_dataset(session,run.dataset_id).name,'created_at':run.created_at,'model_version':run.model_version,'model_name':saved_metadata(session,run.model_version).get('selected_model','Historical model'),'watch_threshold':float(run.watch),'high_threshold':float(run.high),'total':len(records),'high_risk':sum(r['risk']=='High' for r in records),'average_probability':sum(r['probability'] for r in records)/len(records)}

class Thresholds(BaseModel):
    watch:float|None=Field(None,ge=0,le=1)
    high:float|None=Field(None,gt=0,le=1)
    @model_validator(mode='after')
    def ordered(self):
        meta=get_model()['metadata']
        w=self.watch if self.watch is not None else meta['watch_threshold']
        h=self.high if self.high is not None else meta['threshold']
        if w>=h: raise ValueError('Watch threshold must be below the high-risk threshold.')
        return self
class BatchRequest(Thresholds): dataset_id:str
class SingleRequest(BaseModel):
    type:Literal['L','M','H']
    air_temperature:float=Field(ge=150,le=500,allow_inf_nan=False)
    process_temperature:float=Field(ge=150,le=700,allow_inf_nan=False)
    rotational_speed:float=Field(ge=1,le=100000,allow_inf_nan=False)
    torque:float=Field(ge=0,le=10000,allow_inf_nan=False)
    tool_wear:float=Field(ge=0,le=100000,allow_inf_nan=False)
class ReportRequest(BaseModel): analysis_id:str

def infer(frame,watch=None,high=None,model_bundle=None):
    b=model_bundle or get_model();meta=b['metadata']
    watch=meta['watch_threshold'] if watch is None else watch;high=meta['threshold'] if high is None else high
    with inference_lock, threadpool_limits(limits=1): probabilities=b['model'].predict_proba(frame[FEATURES])[:,1]
    return [{**row,'record_id':f'OBS-{i+1:05d}','probability':float(p),'risk':risk_level(float(p),watch,high)} for i,(row,p) in enumerate(zip(frame.to_dict('records'),probabilities))]

def explain(record,model_bundle=None):
    with inference_lock, threadpool_limits(limits=1):
        return explain_unlocked(record,model_bundle)

def explain_unlocked(record,model_bundle=None):
    b=model_bundle or get_model();frame=pd.DataFrame([{c:record[c] for c in FEATURES}]);p=float(b['model'].predict_proba(frame)[0,1]);effects=[]
    for c in NUMERIC:
        replaced=frame.copy();replaced[c]=b['reference'][c]
        reference_probability=float(b['model'].predict_proba(replaced)[0,1])
        effects.append({'feature':c,'value':float(record[c]),'reference_value':b['reference'][c],'contribution':p-reference_probability,**b['metadata']['training_distribution'][c]})
    variants=[]
    for kind in ['L','M','H']:
        changed=frame.copy();changed['Type']=kind
        estimate=float(b['model'].predict_proba(changed)[0,1])
        variants.append({'type':kind,'probability':estimate,'difference':estimate-p,'observed':kind==record['Type'],'seen_in_training':kind in b['model']['preprocess'].named_transformers_['type'].categories_[0]})
    return {'method':'Median replacement sensitivity','description':'Each numeric feature is replaced with its training median while other inputs stay fixed. Changes are sensitivities, not causal effects, and are not additive. The product-type comparison separately changes L/M/H while holding all five measurements fixed.','features':sorted(effects,key=lambda x:abs(x['contribution']),reverse=True),'type_comparison':variants}

@app.get('/api/health')
def health():
    try:
        get_model()
        with Session() as session:session.execute(text('SELECT 1'))
        return {'status':'ok','model_ready':True,'storage_ready':True}
    except Exception:
        return JSONResponse({'status':'unavailable','model_ready':False,'detail':'The model or saved-workspace database is unavailable.'},status_code=503)

@app.post('/api/datasets/upload')
async def upload(file:UploadFile=File(...)):
    if not file.filename or not file.filename.lower().endswith('.csv'): raise HTTPException(422,'Choose a UTF-8 CSV file.')
    content=await file.read(5*1024*1024+1)
    if len(content)>5*1024*1024: raise HTTPException(413,'CSV files must be 5 MB or smaller.')
    try:
        decoded=content.decode('utf-8-sig')
        reader=csv.reader(io.StringIO(decoded),strict=True)
        headers=next(reader)
        if any(len(row)!=len(headers) for row in reader if row and any(c.strip() for c in row)):
            raise ValueError('Each CSV row must have the same number of fields as the header. Check delimiters and quoted values.')
        normalized=[ALIASES.get(c.strip(),c.strip()) for c in headers]
        if len(set(normalized))!=len(normalized): raise ValueError('Duplicate column names are not allowed.')
        raw=pd.read_csv(io.StringIO(decoded))
        clean,summary=validate_frame(raw)
        context=extract_context(raw)
        summary['has_machine_context']=any(context)
        summary['ignored_columns']=[c for c in summary['ignored_columns'] if c not in ('machine_id','observed_at','Machine ID','Timestamp','timestamp')]
        stored=[{**r,**c} for r,c in zip(clean.to_dict('records'),context)]
    except (ValueError,UnicodeError,StopIteration,csv.Error,pd.errors.ParserError) as exc:
        raise HTTPException(422,str(exc) or 'The CSV is empty or malformed.')
    with Session() as session:
        ds=Dataset(id=ident(),name=Path(file.filename.replace('\\','/')).name[:160],created_at=now(),records_json=json.dumps(stored),summary_json=json.dumps(summary))
        session.add(ds);session.commit()
        return {**ds_info(ds),'preview':stored[:8]}

@app.get('/api/datasets')
def datasets():
    with Session() as session: return [ds_info(d) for d in session.query(Dataset).order_by(Dataset.created_at.desc()).all()]
@app.get('/api/datasets/{id}')
def dataset(id:str):
    with Session() as session:
        ds=get_dataset(session,id);return {**ds_info(ds),'preview':json.loads(ds.records_json)[:8]}
@app.post('/api/predictions/batch')
def batch(body:BatchRequest):
    with Session() as session:
        ds=get_dataset(session,body.dataset_id);b=get_model();meta=b['metadata']
        records=infer(pd.DataFrame(json.loads(ds.records_json)),body.watch,body.high,model_bundle=b)
        run=Analysis(id=ident(),dataset_id=ds.id,created_at=now(),model_version=meta['version'],watch=str(body.watch if body.watch is not None else meta['watch_threshold']),high=str(body.high if body.high is not None else meta['threshold']),predictions_json=json.dumps(records))
        session.add(run);session.merge(ModelMetadata(id=meta['version'],metadata_json=json.dumps(meta)));session.flush()
        from backend.app.operations import save_reading
        for record in records:
            if record.get('machine_id'):
                save_reading(session,record,record['machine_id'],record['observed_at'],'csv',meta['version'],analysis_id=run.id)
        session.commit()
        return run_info(run,session)
@app.post('/api/predictions/single')
def single(body:SingleRequest):
    try: frame,_=validate_frame(pd.DataFrame([body.model_dump()]))
    except ValueError as exc: raise HTTPException(422,str(exc))
    b=get_model();record=infer(frame,model_bundle=b)[0]
    meta=b['metadata']
    return {**record,'explanation':explain(record,b),'model_version':meta['version'],'watch_threshold':meta['watch_threshold'],'high_threshold':meta['threshold'],'predicted_at':now()}
@app.get('/api/analyses')
def analyses():
    with Session() as session: return [run_info(r,session) for r in session.query(Analysis).order_by(Analysis.created_at.desc()).all()]
@app.get('/api/analyses/{id}')
def analysis(id:str):
    with Session() as session:return run_info(get_analysis(session,id),session)
@app.get('/api/analyses/{id}/records')
def records(id:str,q:str='',risk:Literal['All','Low','Watch','High']='All',type:Literal['All','L','M','H']='All',sort:Literal['record_id','probability','Torque [Nm]','Rotational speed [rpm]']='probability',direction:Literal['asc','desc']='desc',page:int=Query(1,ge=1),page_size:int=Query(12,ge=1,le=100)):
    with Session() as session:
        data=json.loads(get_analysis(session,id).predictions_json)
        filtered=[r for r in data if (risk=='All' or r['risk']==risk) and (type=='All' or r['Type']==type) and q.lower() in (r['record_id']+' '+r['Type']+' '+r.get('machine_id','')).lower()]
        filtered.sort(key=lambda r:r[sort],reverse=direction=='desc')
        return {'total':len(filtered),'page':page,'records':filtered[(page-1)*page_size:page*page_size]}
@app.get('/api/analyses/{id}/records/{record_id}')
def record_detail(id:str,record_id:str):
    with Session() as session:
        run=get_analysis(session,id);record=next((r for r in json.loads(run.predictions_json) if r['record_id']==record_id),None)
        if record is None: raise HTTPException(404,'Observation not found.')
        return {**record,'explanation':explain(record,model_for_analysis(session,run)),'model_version':run.model_version,'watch_threshold':float(run.watch),'high_threshold':float(run.high),'predicted_at':run.created_at}

def overview_data(session,analysis_id=None):
    run=get_analysis(session,analysis_id) if analysis_id else session.query(Analysis).order_by(Analysis.created_at.desc()).first()
    if not run:return {'analysis':None,'distribution':[],'records':[],'history':[]}
    data=json.loads(run.predictions_json)
    temperature=np.histogram([r['Process temperature [K]']-273.15 for r in data],bins=8)
    histogram=np.histogram([r['probability']*100 for r in data],bins=[0,10,20,30,40,50,60,70,80,90,100])
    history=[run_info(r,session) for r in session.query(Analysis).order_by(Analysis.created_at.desc()).limit(20)]
    if not any(h['id']==run.id for h in history):history.append(run_info(run,session))
    return {'analysis':run_info(run,session),'distribution':[{'name':risk,'value':sum(r['risk']==risk for r in data)} for risk in ['Low','Watch','High']],'temperature':[{'name':f'{temperature[1][i]:.1f}','value':int(v)} for i,v in enumerate(temperature[0])],'histogram':[{'name':f'{i*10}–{i*10+10}%','value':int(v)} for i,v in enumerate(histogram[0])],'scatter':[{'speed':r['Rotational speed [rpm]'],'torque':r['Torque [Nm]'],'risk':r['risk']} for r in data[::max(1,len(data)//300)]],'by_type':[{'name':t,'value':float(np.mean([r['probability']*100 for r in data if r['Type']==t])) if any(r['Type']==t for r in data) else 0} for t in ['L','M','H']],'records':sorted(data,key=lambda r:r['probability'],reverse=True)[:5],'history':history}
@app.get('/api/analytics/overview')
def overview(analysis_id:str|None=None):
    with Session() as session:return overview_data(session,analysis_id)
@app.get('/api/analytics/risk-distribution')
def distribution(analysis_id:str|None=None):
    with Session() as session:return overview_data(session,analysis_id)['distribution']
@app.get('/api/models')
@app.get('/api/models/metrics')
def models():return get_model()['metadata']
@app.get('/api/models/feature-importance')
def importance():return get_model()['metadata']['feature_importance']

def make_pdf(run,session):
    from backend.app.reporting import analysis_pdf
    return analysis_pdf(run,session,get_dataset(session,run.dataset_id).name)
@app.post('/api/reports/generate')
def generate_report(body:ReportRequest):
    with Session() as session:
        run=get_analysis(session,body.analysis_id);report=Report(id=ident(),analysis_id=run.id,created_at=now(),name='Mechora analysis report');session.add(report);session.commit();return {'id':report.id,'url':f'/api/reports/{report.id}'}
@app.get('/api/reports')
def reports():
    with Session() as session:return [{'id':r.id,'analysis_id':r.analysis_id,'created_at':r.created_at,'name':r.name} for r in session.query(Report).order_by(Report.created_at.desc())]
@app.get('/api/reports/{id}')
def report(id:str):
    with Session() as session:
        item=session.get(Report,id)
        if not item:raise HTTPException(404,'Report not found.')
        return Response(make_pdf(get_analysis(session,item.analysis_id),session),media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="mechora-analysis.pdf"'})
@app.get('/api/analyses/{id}/export')
def export(id:str):
    with Session() as session:
        data=json.loads(get_analysis(session,id).predictions_json);out=io.StringIO();writer=csv.DictWriter(out,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
        return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="mechora-predictions.csv"'})

from backend.app.operations import router as operations_router,pause_interrupted_work
app.include_router(operations_router)
from backend.app.training import router as training_router
app.include_router(training_router)
