"""Integration tests use a dedicated SQLite file; user analyses are never modified."""
import os
from pathlib import Path
from uuid import uuid4
import io
import json
import pytest
import pandas as pd
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[2]
TEST_DB=ROOT/'backend'/'data'/f'test-{uuid4()}.db'
os.environ['MECHORA_DATABASE_URL']=f'sqlite:///{TEST_DB}'
from backend.app.main import app, get_model
from backend.app.database import Session, Analysis, engine
from backend.ml.schema import FEATURES, validate_frame, risk_level

@pytest.fixture(scope='module')
def client():
    with TestClient(app) as c:yield c
    engine.dispose()
    TEST_DB.unlink(missing_ok=True)

@pytest.fixture
def source():return pd.read_csv(ROOT/'public'/'sample-observations.csv').head(35)

def upload(client,df):return client.post('/api/datasets/upload',files={'file':('test.csv',df.to_csv(index=False).encode(),'text/csv')})

def test_model_features_and_split():
    b=get_model();m=b['metadata']
    assert list(b['model'].feature_names_in_)==FEATURES
    assert m['train_rows']==6000 and m['test_rows']==2000 and m['validation_rows']==2000
    assert len(m['comparisons'])==3
    assert m['selected_model']==max(m['comparisons'],key=lambda c:c['pr_auc'])['name']
    assert sum(map(sum,m['test_metrics']['confusion_matrix']))==2000

def test_schema_leakage_and_aliases(source):
    df=source.copy();df['Machine failure']=1;df['PWF']=1;df['Product ID']='fake'
    cleaned,summary=validate_frame(df)
    assert list(cleaned.columns)==FEATURES
    assert summary['ignored_columns']==['Machine failure','PWF','Product ID']
    aliases=['type','air_temperature','process_temperature','rotational_speed','torque','tool_wear']
    assert list(validate_frame(source.rename(columns=dict(zip(FEATURES,aliases))))[0])==FEATURES

@pytest.mark.parametrize('p,expected',[(0,'Low'),(.19,'Low'),(.2,'Watch'),(.59,'Watch'),(.6,'High'),(1,'High')])
def test_boundaries(p,expected):assert risk_level(p,.2,.6)==expected

@pytest.mark.parametrize('change', ['missing','invalid_type','infinite','nonnumeric','range','thermal','empty'])
def test_invalid_schema(source,change):
    df=source.copy()
    if change=='missing':df=df.drop(columns=FEATURES[2])
    elif change=='invalid_type':df.loc[0,'Type']='X'
    elif change=='infinite':df[FEATURES[3]]=df[FEATURES[3]].astype(float);df.loc[0,FEATURES[3]]=float('inf')
    elif change=='nonnumeric':df[FEATURES[3]]=df[FEATURES[3]].astype(str);df.loc[0,FEATURES[3]]='bad'
    elif change=='range':df.loc[0,FEATURES[3]]=-1
    elif change=='thermal':df.loc[0,FEATURES[2]]=200
    elif change=='empty':df=df.iloc[:0]
    with pytest.raises(ValueError):validate_frame(df)

def test_end_to_end(client,source):
    assert client.get('/api/health').json()['model_ready']
    imported=upload(client,source);assert imported.status_code==200,imported.text
    ds=imported.json();assert ds['row_count']==35
    r=client.post('/api/predictions/batch',json={'dataset_id':ds['id']});assert r.status_code==200,r.text
    a=r.json();assert a['total']==35
    # Fresh SQLAlchemy session proves committed persistence.
    with Session() as s:assert s.get(Analysis,a['id']) is not None
    assert client.get(f'/api/datasets/{ds["id"]}').json()['row_count']==35
    rows=client.get(f'/api/analyses/{a["id"]}/records').json();assert rows['total']==35
    assert len(rows['records'])==12
    rec=rows['records'][0]
    detail=client.get(f'/api/analyses/{a["id"]}/records/{rec["record_id"]}').json()
    assert len(detail['explanation']['features'])==5
    assert detail['probability']==rec['probability']
    view=client.get(f'/api/analytics/overview?analysis_id={a["id"]}').json()
    assert sum(v['value'] for v in view['distribution'])==35
    assert sum(v['value'] for v in view['histogram'])==35
    assert len(view['history'])>=1
    second=client.post('/api/predictions/batch',json={'dataset_id':ds['id']}).json()
    rows2=client.get(f'/api/analyses/{second["id"]}/records').json()
    assert rows2['records']==rows['records']
    selected=client.get(f'/api/analyses/{a["id"]}/records?risk=High').json()
    assert all(row['risk']=='High' for row in selected['records'])
    csv=client.get(f'/api/analyses/{a["id"]}/export');assert csv.status_code==200
    assert len(pd.read_csv(io.StringIO(csv.text)))==35
    generated=client.post('/api/reports/generate',json={'analysis_id':a['id']}).json()
    pdf=client.get(generated['url']);assert pdf.content.startswith(b'%PDF')
    assert len(pdf.content)>1500
    assert client.get('/api/reports').json()[0]['id']==generated['id']

def test_single_and_validation(client):
    data={'type':'M','air_temperature':298.1,'process_temperature':308.6,'rotational_speed':1551,'torque':42.8,'tool_wear':0}
    first=client.post('/api/predictions/single',json=data);assert first.status_code==200,first.text
    assert first.json()['probability']==client.post('/api/predictions/single',json=data).json()['probability']
    assert client.post('/api/predictions/single',json={**data,'torque':-1}).status_code==422
    assert client.post('/api/predictions/single',json={**data,'process_temperature':200}).status_code==422

def test_upload_failures(client,source):
    for name,data in [('bad.txt',b'hello'),('empty.csv',b''),('bad.csv',b'hello\n1'),('invalid.csv',b'\xff')]:
        assert client.post('/api/datasets/upload',files={'file':(name,data)}).status_code==422
    assert client.post('/api/datasets/upload',files={'file':('huge.csv',b'a'*(5*1024*1024+1))}).status_code==413
    assert client.post('/api/datasets/upload',files={'file':('duplicate.csv',b'Type,Type\nL,L')}).status_code==422
    too_many=pd.concat([source]*300,ignore_index=True)
    assert upload(client,too_many).status_code==422

def test_threshold_and_origin_guard(client,source):
    ds=upload(client,source).json()
    assert client.post('/api/predictions/batch',json={'dataset_id':ds['id'],'watch':.8,'high':.5}).status_code==422
    r=client.post('/api/predictions/batch',json={'dataset_id':ds['id'],'watch':0,'high':1}).json()
    assert r['high_threshold']==1
    assert client.post('/api/predictions/batch',json={'dataset_id':ds['id']},headers={'Origin':'https://untrusted.example'}).status_code==403
    assert client.get('/api/analyses/does-not-exist').status_code==404
    assert client.get('/api/reports/does-not-exist').status_code==404

@pytest.mark.parametrize('tail',['\nM,298,308,1500,40,0,unexpected','\nM,298,308,1500,40','\n"M,298,308,1500,40,0'])
def test_ragged_csv_is_rejected(client,tail):
    result=client.post('/api/datasets/upload',files={'file':('ragged.csv',(','.join(FEATURES)+tail).encode())})
    assert result.status_code==422,result.text

@pytest.mark.parametrize('value',['NaN','Infinity','-Infinity'])
def test_nonfinite_single_inputs_are_validation_errors(client,value):
    body='{"type":"M","air_temperature":298.1,"process_temperature":308.6,"rotational_speed":1551,"torque":'+value+',"tool_wear":0}'
    result=client.post('/api/predictions/single',content=body,headers={'Content-Type':'application/json'})
    assert result.status_code==422,result.text

def test_sort_filter_pagination_and_threshold_consistency(client,source):
    ds=upload(client,source).json()
    first=client.post('/api/predictions/batch',json={'dataset_id':ds['id']}).json()
    second=client.post('/api/predictions/batch',json={'dataset_id':ds['id'],'watch':0,'high':1}).json()
    def all_records(id):return client.get(f'/api/analyses/{id}/records?page_size=100&sort=record_id&direction=asc').json()['records']
    old,new=all_records(first['id']),all_records(second['id'])
    assert [r['probability'] for r in old]==[r['probability'] for r in new]
    assert all(r['risk']==('High' if r['probability']>=1 else 'Watch') for r in new)
    ordered=client.get(f'/api/analyses/{first["id"]}/records?page_size=100&direction=asc').json()['records']
    assert [r['probability'] for r in ordered]==sorted(r['probability'] for r in old)
    page=client.get(f'/api/analyses/{first["id"]}/records?page=2&page_size=7&sort=record_id&direction=asc').json()
    assert page['records']==old[7:14]
    filtered=client.get(f'/api/analyses/{first["id"]}/records?type=M&q=OBS-00001').json()
    assert all(r['Type']=='M' and r['record_id']=='OBS-00001' for r in filtered['records'])

def test_selected_old_analysis_is_in_batch_selector(client,source):
    ds=upload(client,source.head(1)).json()
    original=client.post('/api/predictions/batch',json={'dataset_id':ds['id']}).json()
    for _ in range(21):assert client.post('/api/predictions/batch',json={'dataset_id':ds['id']}).status_code==200
    view=client.get(f'/api/analytics/overview?analysis_id={original["id"]}').json()
    assert view['analysis']['id']==original['id']
    assert original['id'] in [row['id'] for row in view['history']]

def test_saved_diagnostics_keep_the_original_model(client,source,monkeypatch):
    import backend.app.model_store as store
    original_bundle=store.get_model()
    ds=upload(client,source).json()
    run=client.post('/api/predictions/batch',json={'dataset_id':ds['id']}).json()
    record=client.get(f'/api/analyses/{run["id"]}/records').json()['records'][0]
    url=f'/api/analyses/{run["id"]}/records/{record["record_id"]}'
    before=client.get(url).json()
    changed={**original_bundle,'metadata':{**original_bundle['metadata'],'artifact_sha256':'0'*64,'selected_model':'Different future model'}}
    monkeypatch.setattr(store,'_bundle',changed)
    after=client.get(url).json()
    assert after==before
    meta=client.get(f'/api/analyses/{run["id"]}').json()
    assert meta['model_name']==original_bundle['metadata']['selected_model']
    report=client.post('/api/reports/generate',json={'analysis_id':run['id']}).json()
    pdf=client.get(report['url'])
    assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')

def test_independent_metric_reproduction():
    from scripts.verify_model import verify
    assert verify()['status']=='passed'

def test_type_comparison_uses_the_trained_model(client):
    body={'type':'M','air_temperature':302,'process_temperature':310,'rotational_speed':1400,'torque':65,'tool_wear':190}
    result=client.post('/api/predictions/single',json=body).json()
    comparisons=result['explanation']['type_comparison']
    assert [r['type'] for r in comparisons]==['L','M','H']
    for row in comparisons:
        alternative=client.post('/api/predictions/single',json={**body,'type':row['type']}).json()
        assert row['probability']==alternative['probability']
        assert row['difference']==pytest.approx(row['probability']-result['probability'])

def test_timestamped_csv_creates_machine_history_without_leakage(client,source):
    frame=source.head(3).copy();frame['machine_id']='TEST-CNC-01';frame['observed_at']=['2026-10-31T09:00:00Z','2026-10-31T09:01:00Z','2026-10-31T09:02:00Z']
    ds=upload(client,frame).json();assert ds['has_machine_context']
    result=client.post('/api/predictions/batch',json={'dataset_id':ds['id']}).json()
    history=client.get('/api/machines/TEST-CNC-01/readings').json()
    assert history['total']==3
    assert all(r['source']=='csv' for r in history['readings'])
    assert history['readings'][0]['observed_at']=='2026-10-31T09:00:00+00:00'
    detail=client.get('/api/readings/'+history['readings'][0]['id']).json()
    assert detail['machine_id']=='TEST-CNC-01' and len(detail['explanation']['type_comparison'])==3
    client.post('/api/predictions/batch',json={'dataset_id':ds['id']})
    assert client.get('/api/machines/TEST-CNC-01/readings').json()['total']==3
    assert client.get(f'/api/analyses/{result["id"]}/records?q=TEST-CNC-01').json()['total']==3
    assert upload(client,frame.drop(columns='observed_at')).status_code==422
    frame.loc[0,'observed_at']='2026-10-31 09:00:00'
    assert upload(client,frame).status_code==422

def test_connector_reading_is_saved_and_idempotent(client):
    body={'machine_id':'TEST-CONNECTOR','observed_at':'2026-10-31T10:00:00Z','type':'H','air_temperature':300,'process_temperature':310,'rotational_speed':1500,'torque':40,'tool_wear':100,'external_id':'sample-1'}
    first=client.post('/api/ingestion/readings',json=body);assert first.status_code==200,first.text
    again=client.post('/api/ingestion/readings',json=body).json();assert first.json()['id']==again['id']
    assert client.get('/api/machines/TEST-CONNECTOR/readings').json()['total']==1
    assert client.post('/api/ingestion/readings',json={**body,'torque':41}).status_code==409
    assert client.post('/api/ingestion/readings',json={**body,'observed_at':'not-a-time'}).status_code==422

def test_replay_steps_pause_and_completion(client,source):
    import time
    ds=upload(client,source.head(4)).json()
    replay=client.post('/api/replays',json={'dataset_id':ds['id']}).json()
    id=replay['id'];assert replay['status']=='paused' and replay['cursor']==0
    step=client.post(f'/api/replays/{id}/control',json={'action':'step','speed':10}).json()
    assert step['cursor']==1 and step['status']=='paused'
    assert client.post(f'/api/replays/{id}/control',json={'action':'start','speed':10}).status_code==200
    deadline=time.monotonic()+5
    while time.monotonic()<deadline:
        state=client.get(f'/api/replays/{id}').json()
        if state['status']=='completed':break
        time.sleep(.05)
    assert state['status']=='completed' and state['cursor']==4
    readings=client.get(f'/api/machines/{replay["machine_id"]}/readings').json()['readings']
    assert len(readings)==4 and all(r['source']=='replay' for r in readings)
    assert 'simulated' in state['clock_note']
    assert client.post(f'/api/replays/{id}/control',json={'action':'start'}).status_code==409

def test_replay_pause_and_resume_preserve_the_cursor(client,source):
    import time
    ds=upload(client,source.head(5)).json();run=client.post('/api/replays',json={'dataset_id':ds['id']}).json();id=run['id']
    assert client.post(f'/api/replays/{id}/control',json={'action':'start','speed':.25}).status_code==200
    time.sleep(.08)
    paused=client.post(f'/api/replays/{id}/control',json={'action':'pause','speed':.25}).json()
    assert paused['status']=='paused'
    time.sleep(.1)
    assert client.get(f'/api/replays/{id}').json()['cursor']==paused['cursor']
    resumed=client.post(f'/api/replays/{id}/control',json={'action':'start','speed':10})
    assert resumed.status_code==200
    deadline=time.monotonic()+4
    while time.monotonic()<deadline:
        status=client.get(f'/api/replays/{id}').json()
        if status['status']=='completed':break
        time.sleep(.05)
    assert status['cursor']==5 and status['status']=='completed'

def test_maintenance_resolution_history_and_confirmed_export(client):
    reading=client.get('/api/machines/TEST-CONNECTOR/readings').json()['readings'][0]
    body={'reading_id':reading['id'],'title':'Check tool condition','note':'Flagged for an inspection.'}
    opened=client.post('/api/maintenance',json=body).json();id=opened['id']
    assert client.post('/api/maintenance',json=body).json()['id']==id
    assert client.patch(f'/api/maintenance/{id}',json={'status':'resolved','outcome':'unconfirmed','note':'Checked'}).status_code==422
    active=client.patch(f'/api/maintenance/{id}',json={'status':'in_progress','note':'Technician inspecting the tool.'}).json()
    assert active['status']=='in_progress'
    resolved=client.patch(f'/api/maintenance/{id}',json={'status':'resolved','outcome':'no_fault_found','note':'Inspection found normal operation.'}).json()
    assert resolved['resolved_at'] and len(resolved['notes'])==3
    exported=client.get('/api/maintenance/export');assert exported.status_code==200
    labeled=pd.read_csv(io.StringIO(exported.text));assert 'Machine failure' in labeled
    assert labeled.iloc[0]['Machine failure']==0
    assert labeled.iloc[0]['machine_id']=='TEST-CONNECTOR'

def test_training_splits_and_candidate_activation(client,tmp_path,monkeypatch):
    import time
    import shutil
    from backend.ml.equipment_training import validate_training,split_indices
    from backend.app import model_store,training
    raw=pd.read_csv(ROOT/'datasets'/'ai4i2020.csv')
    frame=pd.concat([raw[raw['Machine failure']==1].sample(80,random_state=42),raw[raw['Machine failure']==0].sample(160,random_state=42)]).sample(frac=1,random_state=42).reset_index(drop=True)
    frame['machine_id']=['TRAIN-'+str(i%6) for i in range(len(frame))]
    frame['observed_at']=pd.date_range('2026-01-01',periods=len(frame),freq='min',tz='UTC').astype(str)
    X,y,context,_=validate_training(frame)
    for strategy in ['random','temporal','machine']:
        train,val,test=split_indices(X,y,context,strategy)
        assert set(train).isdisjoint(test) and set(val).isdisjoint(test) and set(train).isdisjoint(val)
        if strategy=='temporal':assert max(train)<min(val)<min(test)
        if strategy=='machine':assert set(frame.iloc[train].machine_id).isdisjoint(frame.iloc[test].machine_id)
    artifact_dir=tmp_path/'artifacts';artifact_dir.mkdir()
    shutil.copyfile(ROOT/'artifacts'/'model.joblib',artifact_dir/'model.joblib')
    shutil.copyfile(ROOT/'artifacts'/'metrics.json',artifact_dir/'metrics.json')
    monkeypatch.setattr(model_store,'ARTIFACTS',artifact_dir);monkeypatch.setattr(model_store,'_bundle',None);monkeypatch.setattr(training,'ARTIFACTS',artifact_dir)
    original=model_store.get_model()['metadata']['version']
    result=client.post('/api/training/runs',files={'file':('confirmed-test-data.csv',frame.to_csv(index=False).encode())},data={'strategy':'temporal'})
    assert result.status_code==200,result.text
    id=result.json()['id'];deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        run=client.get('/api/training/runs/'+id).json()
        if run['status'] in ('completed','failed'):break
        time.sleep(.1)
    assert run['status']=='completed',run
    assert len(run['metrics']['comparisons'])==3
    assert run['metrics']['split_audit']['strategy']=='temporal'
    activated=client.post(f'/api/training/runs/{id}/activate',json={})
    assert activated.status_code==200,activated.text
    assert activated.json()['model']['dataset']=='confirmed-test-data.csv'
    assert client.get('/api/training/versions').status_code==200
    restored=client.post(f'/api/training/versions/{original}/activate',json={})
    assert restored.status_code==200,restored.text
    assert restored.json()['model']['version']==original

def test_connector_unit_normalization():
    from scripts.connector import normalize
    row={'machine_id':'CNC-1','observed_at':'2026-10-31T10:00:00Z','type':'m','air_temperature':25,'process_temperature':35,'rotational_speed':1500,'torque':40,'tool_wear':10}
    result=normalize(row,'C')
    assert result['air_temperature']==298.15 and result['process_temperature']==308.15 and result['type']=='M'
    with pytest.raises(ValueError):normalize({**row,'Air temperature [K]':300},'C')
