"""Equipment histories, persistent ingestion, replay, and human investigation."""
from datetime import datetime,timezone,timedelta
import csv
import hashlib
import io
import json
import threading
import time
from uuid import uuid4
import pandas as pd
from fastapi import APIRouter,HTTPException,Query
from fastapi.responses import Response
from pydantic import BaseModel,Field,field_validator,model_validator
from typing import Literal
from backend.app.database import Session,Machine,Reading,Replay,Dataset,Analysis,Investigation
from backend.app.model_store import get_model,model_for_analysis
from backend.ml.schema import FEATURES,validate_frame
from backend.ml.context import machine_id as validate_machine_id,timestamp

router=APIRouter(prefix='/api')
def now():return datetime.now(timezone.utc).isoformat()
def uid():return str(uuid4())

def ensure_machine(session,id,name=None,location=''):
    item=session.get(Machine,id)
    if not item:
        item=Machine(id=id,name=name or id,location=location,created_at=now());session.add(item);session.flush()
    return item

def reading_dict(r):
    return {'id':r.id,'machine_id':r.machine_id,'observed_at':r.observed_at,**json.loads(r.measurements_json),'probability':r.probability,'risk':r.risk,'model_version':r.model_version,'source':r.source,'analysis_id':r.analysis_id,'record_id':r.record_id}

ingestion_lock=threading.RLock()
def save_reading(session,record,machine,observed_at,source,model_version,analysis_id=None,external_id=None):
    ensure_machine(session,machine)
    values={c:record[c] for c in FEATURES}
    identity=f'{machine}|{source}|{external_id}' if external_id else json.dumps([machine,observed_at,source,values],sort_keys=True)
    key=hashlib.sha256(identity.encode()).hexdigest()
    existing=session.query(Reading).filter_by(input_key=key).first()
    if existing:
        if json.loads(existing.measurements_json)!=values or existing.observed_at!=observed_at:
            raise HTTPException(409,'This external observation ID was already used for different measurements.')
        return existing
    row=Reading(id=uid(),machine_id=machine,observed_at=observed_at,measurements_json=json.dumps(values),probability=record['probability'],risk=record['risk'],model_version=model_version,source=source,analysis_id=analysis_id,record_id=record.get('record_id'),input_key=key)
    session.add(row);session.flush();return row

class MachineInput(BaseModel):
    id:str
    name:str=Field(min_length=1,max_length=120)
    location:str=Field('',max_length=160)
    @field_validator('id')
    @classmethod
    def valid_id(cls,value):return validate_machine_id(value)

@router.post('/machines')
def register_machine(body:MachineInput):
    with Session() as session:
        item=ensure_machine(session,body.id,body.name,body.location);item.name=body.name.strip();item.location=body.location.strip();session.commit()
        return {'id':item.id,'name':item.name,'location':item.location,'created_at':item.created_at}

@router.get('/machines')
def machines():
    with Session() as session:
        result=[]
        for m in session.query(Machine).order_by(Machine.created_at.desc()):
            latest=session.query(Reading).filter_by(machine_id=m.id).order_by(Reading.observed_at.desc(),Reading.id.desc()).first()
            result.append({'id':m.id,'name':m.name,'location':m.location,'created_at':m.created_at,'reading_count':session.query(Reading).filter_by(machine_id=m.id).count(),'open_investigations':session.query(Investigation).filter(Investigation.machine_id==m.id,Investigation.status!='resolved').count(),'latest':reading_dict(latest) if latest else None})
        return result

@router.get('/machines/{id}/readings')
def machine_readings(id:str,limit:int=Query(200,ge=1,le=1000),source:Literal['all','csv','connector','replay']='all'):
    with Session() as session:
        if not session.get(Machine,id):raise HTTPException(404,'Machine not found.')
        query=session.query(Reading).filter_by(machine_id=id)
        if source!='all':query=query.filter_by(source=source)
        total=query.count();rows=query.order_by(Reading.observed_at.desc(),Reading.id.desc()).limit(limit).all()
        return {'total':total,'readings':[reading_dict(r) for r in reversed(rows)]}

class MeasurementInput(BaseModel):
    machine_id:str
    observed_at:str
    type:Literal['L','M','H']
    air_temperature:float=Field(ge=150,le=500,allow_inf_nan=False)
    process_temperature:float=Field(ge=150,le=700,allow_inf_nan=False)
    rotational_speed:float=Field(ge=1,le=100000,allow_inf_nan=False)
    torque:float=Field(ge=0,le=10000,allow_inf_nan=False)
    tool_wear:float=Field(ge=0,le=100000,allow_inf_nan=False)
    external_id:str|None=Field(None,max_length=120)
    @field_validator('machine_id')
    @classmethod
    def machine(cls,value):return validate_machine_id(value)
    @field_validator('observed_at')
    @classmethod
    def time(cls,value):return timestamp(value)
    @model_validator(mode='after')
    def temperatures(self):
        if self.process_temperature<self.air_temperature:raise ValueError('Process temperature must be at least air temperature.')
        return self

@router.get('/readings/{id}')
def reading_detail(id:str):
    from backend.app.main import explain
    with Session() as session:
        row=session.get(Reading,id)
        if not row:raise HTTPException(404,'Reading not found.')
        bundle=model_for_analysis(session,row);meta=bundle['metadata'];record=reading_dict(row)
        run=session.get(Analysis,row.analysis_id) if row.analysis_id else None
        return {**record,'record_id':row.record_id or row.id,'predicted_at':row.observed_at,'explanation':explain(record,bundle),'watch_threshold':float(run.watch) if run else meta['watch_threshold'],'high_threshold':float(run.high) if run else meta['threshold']}

@router.post('/ingestion/readings')
def ingest(body:MeasurementInput):
    from backend.app.main import infer
    try:frame,_=validate_frame(pd.DataFrame([body.model_dump()]))
    except ValueError as exc:raise HTTPException(422,str(exc))
    b=get_model();record=infer(frame,model_bundle=b)[0]
    with ingestion_lock,Session() as session:
        row=save_reading(session,record,body.machine_id,body.observed_at,'connector',b['metadata']['version'],external_id=body.external_id)
        session.commit();return reading_dict(row)

class ReplayInput(BaseModel):dataset_id:str
class ReplayControl(BaseModel):
    action:Literal['start','pause','step']
    speed:float=Field(1,ge=.25,le=10)

replay_locks={};workers={};worker_events={};worker_lock=threading.RLock()
def replay_lock(id):
    with worker_lock:return replay_locks.setdefault(id,threading.RLock())

def replay_dict(run,session):
    ds=session.get(Dataset,run.dataset_id)
    return {'id':run.id,'dataset_id':run.dataset_id,'dataset_name':ds.name,'machine_id':run.machine_id,'cursor':run.cursor,'total':len(json.loads(ds.records_json)),'status':run.status,'speed':run.speed,'started_at':run.started_at,'model_version':run.model_version,'error':run.error or '', 'clock_note':'Demonstration replay: original measurements, isolated demo machine, simulated one-minute observation intervals. No live sensor connection.'}

@router.post('/replays')
def create_replay(body:ReplayInput):
    with Session() as session:
        if not session.get(Dataset,body.dataset_id):raise HTTPException(404,'Dataset not found.')
        id=uid();machine='REPLAY-'+id[:8]
        ensure_machine(session,machine,'Replay demonstration '+id[:8],'Simulated clock / recorded data')
        run=Replay(id=id,dataset_id=body.dataset_id,machine_id=machine,cursor=0,status='paused',speed=1,started_at=now(),model_version=get_model()['metadata']['version'],error='')
        session.add(run);session.commit();return replay_dict(run,session)

@router.get('/replays')
def replays():
    with Session() as session:return [replay_dict(r,session) for r in session.query(Replay).order_by(Replay.started_at.desc()).limit(30)]

@router.get('/replays/{id}')
def replay_status(id:str):
    with Session() as session:
        run=session.get(Replay,id)
        if not run:raise HTTPException(404,'Replay not found.')
        return replay_dict(run,session)

def advance_replay(id,require_running=False):
    from backend.app.main import infer
    with replay_lock(id),Session() as session:
        run=session.get(Replay,id)
        if not run:raise HTTPException(404,'Replay not found.')
        if require_running and run.status!='running':return False
        ds=session.get(Dataset,run.dataset_id);rows=json.loads(ds.records_json)
        if run.cursor>=len(rows):run.status='completed';session.commit();return False
        if run.status=='error':raise HTTPException(409,run.error)
        b=model_for_analysis(session,run)
        record=infer(pd.DataFrame([{c:rows[run.cursor][c] for c in FEATURES}]),model_bundle=b)[0]
        observed=(datetime.fromisoformat(run.started_at)+timedelta(minutes=run.cursor)).isoformat()
        save_reading(session,record,run.machine_id,observed,'replay',run.model_version,external_id=f'{run.id}:{run.cursor}')
        run.cursor+=1
        if run.cursor>=len(rows):run.status='completed'
        session.commit();return run.status=='running'

def replay_worker(id):
    try:
        while True:
            with Session() as session:
                run=session.get(Replay,id)
                if not run or run.status!='running':break
                speed=run.speed
            if not advance_replay(id,True):break
            event=worker_events.setdefault(id,threading.Event());event.wait(1/speed);event.clear()
    except Exception as exc:
        with Session() as session:
            run=session.get(Replay,id)
            if run:run.status='error';run.error=getattr(exc,'detail',str(exc))[:500];session.commit()
    finally:
        with worker_lock:workers.pop(id,None)

@router.post('/replays/{id}/control')
def replay_control(id:str,body:ReplayControl):
    with replay_lock(id),Session() as session:
        run=session.get(Replay,id)
        if not run:raise HTTPException(404,'Replay not found.')
        run.speed=body.speed
        if body.action=='pause':run.status='paused' if run.status!='completed' else 'completed'
        elif body.action=='start':
            if run.status=='completed':raise HTTPException(409,'This replay has finished. Create a new replay to start again.')
            if run.status=='error':raise HTTPException(409,run.error)
            run.status='running'
        elif run.status=='running':raise HTTPException(409,'Pause the replay before stepping through a reading.')
        session.commit()
    if body.action=='step':advance_replay(id)
    if body.action=='pause':
        with worker_lock:
            thread=workers.get(id);event=worker_events.get(id)
            if event:event.set()
        if thread:thread.join(timeout=5)
    if body.action=='start':
        with worker_lock:
            if id not in workers or not workers[id].is_alive():
                worker_events.setdefault(id,threading.Event()).clear()
                thread=threading.Thread(target=replay_worker,args=(id,),daemon=True);workers[id]=thread;thread.start()
    return replay_status(id)

Status=Literal['open','in_progress','resolved']
Outcome=Literal['unconfirmed','confirmed_failure','no_fault_found','maintenance_performed','inconclusive']
class InvestigationInput(BaseModel):
    analysis_id:str|None=None
    record_id:str|None=None
    reading_id:str|None=None
    title:str=Field('Inspect operating observation',min_length=3,max_length=160)
    note:str=Field('',max_length=4000)
class InvestigationUpdate(BaseModel):
    status:Status
    outcome:Outcome='unconfirmed'
    note:str=Field('',max_length=4000)
    @model_validator(mode='after')
    def resolution(self):
        if self.status=='resolved' and (self.outcome=='unconfirmed' or len(self.note.strip())<3):raise ValueError('To resolve an investigation, choose an outcome and add an inspection or maintenance note.')
        return self

def investigation_dict(row):
    return {'id':row.id,'reading_id':row.reading_id,'analysis_id':row.analysis_id,'record_id':row.record_id,'machine_id':row.machine_id,'title':row.title,'status':row.status,'outcome':row.outcome,'created_at':row.created_at,'updated_at':row.updated_at,'resolved_at':row.resolved_at,'snapshot':json.loads(row.snapshot_json),'notes':json.loads(row.notes_json)}

@router.post('/maintenance')
def open_investigation(body:InvestigationInput):
    with Session() as session:
        if body.reading_id:
            reading=session.get(Reading,body.reading_id)
            if not reading:raise HTTPException(404,'Reading not found.')
            snapshot=reading_dict(reading)
        elif body.analysis_id and body.record_id:
            run=session.get(Analysis,body.analysis_id)
            if not run:raise HTTPException(404,'Analysis not found.')
            snapshot=next((r for r in json.loads(run.predictions_json) if r['record_id']==body.record_id),None)
            if not snapshot:raise HTTPException(404,'Observation not found.')
            snapshot={**snapshot,'model_version':run.model_version,'source':'csv'}
        else:raise HTTPException(422,'Select a saved observation or a machine reading to investigate.')
        existing=session.query(Investigation).filter(Investigation.status!='resolved')
        existing=existing.filter_by(reading_id=body.reading_id) if body.reading_id else existing.filter_by(analysis_id=body.analysis_id,record_id=body.record_id)
        found=existing.first()
        if found:return investigation_dict(found)
        at=now();notes=[{'at':at,'text':body.note.strip(),'status':'open','outcome':'unconfirmed'}] if body.note.strip() else []
        row=Investigation(id=uid(),reading_id=body.reading_id,analysis_id=body.analysis_id,record_id=body.record_id,machine_id=snapshot.get('machine_id'),title=body.title.strip(),status='open',outcome='unconfirmed',created_at=at,updated_at=at,snapshot_json=json.dumps(snapshot),notes_json=json.dumps(notes))
        session.add(row);session.commit();return investigation_dict(row)

@router.get('/maintenance')
def investigations(status:Literal['all','open','in_progress','resolved']='all'):
    with Session() as session:
        query=session.query(Investigation)
        if status!='all':query=query.filter_by(status=status)
        return [investigation_dict(r) for r in query.order_by(Investigation.updated_at.desc()).limit(300)]

@router.patch('/maintenance/{id}')
def update_investigation(id:str,body:InvestigationUpdate):
    with Session() as session:
        row=session.get(Investigation,id)
        if not row:raise HTTPException(404,'Investigation not found.')
        at=now();notes=json.loads(row.notes_json)
        notes.append({'at':at,'text':body.note.strip() or 'Status updated.','status':body.status,'outcome':body.outcome})
        row.status=body.status;row.outcome=body.outcome;row.updated_at=at;row.resolved_at=at if body.status=='resolved' else None;row.notes_json=json.dumps(notes)
        session.commit();return investigation_dict(row)

@router.get('/maintenance/export')
def export_confirmed_outcomes():
    with Session() as session:
        data=[]
        for row in session.query(Investigation).filter(Investigation.status=='resolved',Investigation.outcome.in_(['confirmed_failure','no_fault_found'])):
            snap=json.loads(row.snapshot_json)
            if snap.get('source')=='replay':continue
            data.append({**{c:snap[c] for c in FEATURES},'machine_id':snap.get('machine_id',''),'observed_at':snap.get('observed_at',''),'Machine failure':int(row.outcome=='confirmed_failure')})
        if not data:raise HTTPException(409,'No confirmed non-replay outcomes are available. Resolve investigations with confirmed failure or no fault found first.')
        out=io.StringIO();writer=csv.DictWriter(out,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
        return Response(out.getvalue(),media_type='text/csv',headers={'Content-Disposition':'attachment; filename="mechora-confirmed-outcomes.csv"'})

def pause_interrupted_work():
    with Session() as session:
        for run in session.query(Replay).filter_by(status='running'):run.status='paused'
        from backend.app.database import TrainingRun
        for run in session.query(TrainingRun).filter(TrainingRun.status.in_(['queued','running'])):
            run.status='failed';run.error='Training was interrupted by a backend restart. Start a new run.'
        session.commit()
