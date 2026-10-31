"""Browser verification for equipment context, replay, investigations, and training."""
from pathlib import Path
import json
from uuid import uuid4
import pandas as pd
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'output'/'qa';OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,channel='chrome');page=browser.new_page(viewport={'width':1440,'height':1000},accept_downloads=True)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    base='http://127.0.0.1:3000';original=page.request.get(base+'/api/models/metrics').json()['version']
    machine='BROWSER-DEMO-'+uuid4().hex[:6]
    page.request.post(base+'/api/machines',data={'id':machine,'name':'Browser demonstration machine','location':'Simulated context / original benchmark measurements'})
    frame=pd.read_csv(ROOT/'public'/'sample-observations.csv').head(8)
    frame['machine_id']=machine;frame['observed_at']=pd.date_range('2026-10-31T12:00:00Z',periods=8,freq='min').astype(str)
    page.goto(base+'/import');page.wait_for_load_state('networkidle')
    page.locator('input[type=file]').set_input_files({'name':'timestamped-equipment-demo.csv','mimeType':'text/csv','buffer':frame.to_csv(index=False).encode()})
    expect(page.get_by_text('Schema verified')).to_be_visible(timeout=15000)
    expect(page.get_by_text('machine_id',exact=True)).to_be_visible()
    page.get_by_role('button',name='Run analysis',exact=True).click();page.wait_for_url('**/dashboard?analysis=*')
    page.get_by_role('link',name='Machines & replay',exact=True).click()
    expect(page.locator('.machine-list button').filter(has_text=machine)).to_be_visible(timeout=15000)
    page.locator('.machine-list button').filter(has_text=machine).click()
    expect(page.locator('.observations-table tbody tr')).to_have_count(8,timeout=15000)
    page.screenshot(path=str(OUT/'machine-history.png'),full_page=True)
    page.get_by_role('link',name='Inspect reading',exact=False).first.click()
    expect(page.locator('.type-comparison>div')).to_have_count(3,timeout=15000)
    expect(page.locator('.machine-context-note')).to_contain_text(machine)
    page.get_by_role('link',name='Flag for inspection').click()
    page.get_by_label('Inspection title').fill('Inspect demonstration tool')
    page.get_by_label('Initial note').fill('A course demonstration of a documented inspection.')
    page.get_by_role('button',name='Open investigation',exact=True).click()
    expect(page.get_by_text('Inspection timeline',exact=True)).to_be_visible(timeout=15000)
    expect(page.locator('.investigation-update').locator('..')).to_contain_text(machine,timeout=15000)
    page.locator('.investigation-update select').nth(0).select_option('resolved')
    page.locator('.investigation-update select').nth(1).select_option('no_fault_found')
    page.get_by_label('Inspection or maintenance note').fill('Demonstration inspection completed; no fault found.')
    page.get_by_role('button',name='Save investigation',exact=True).click()
    expect(page.locator('.investigation-save')).to_contain_text('Saved',timeout=15000)
    page.screenshot(path=str(OUT/'maintenance-investigation.png'),full_page=True)
    with page.expect_download() as download:page.get_by_role('button',name='Export confirmed outcomes').click()
    download.value.save_as(OUT/'confirmed-outcomes.csv')
    assert machine in (OUT/'confirmed-outcomes.csv').read_text()
    page.get_by_role('link',name='Machines & replay',exact=True).click()
    expect(page.get_by_label('Replay source dataset')).to_be_visible()
    datasets=page.request.get(base+'/api/datasets').json();ds=next(d for d in datasets if d['name']=='timestamped-equipment-demo.csv')
    page.get_by_label('Replay source dataset').select_option(ds['id'])
    page.get_by_role('button',name='New replay',exact=False).click()
    expect(page.locator('.replay-progress-heading')).to_contain_text('0 / 8',timeout=15000)
    page.get_by_role('button',name='Advance one observation').click()
    expect(page.locator('.replay-progress-heading')).to_contain_text('1 / 8',timeout=15000)
    page.get_by_label('Replay speed').select_option('10')
    page.get_by_role('button',name='Start replay',exact=True).click()
    expect(page.locator('.replay-progress-heading')).to_contain_text('completed',timeout=15000)
    expect(page.locator('.replay-progress-heading')).to_contain_text('8 / 8')
    page.screenshot(path=str(OUT/'recorded-data-replay.png'),full_page=True)
    # The complete browser training cycle uses explicitly synthetic demonstration labels.
    raw=pd.read_csv(ROOT/'datasets'/'ai4i2020.csv')
    training=pd.concat([raw[raw['Machine failure']==1].sample(80,random_state=42),raw[raw['Machine failure']==0].sample(160,random_state=42)]).sample(frac=1,random_state=42).reset_index(drop=True)
    training['machine_id']=['DEMO-TRAIN-'+str(i%6) for i in range(len(training))]
    training['observed_at']=pd.date_range('2026-01-01',periods=len(training),freq='min',tz='UTC').astype(str)
    page.goto(base+'/models');expect(page.get_by_text('Train with labeled equipment data',exact=True)).to_be_visible(timeout=15000)
    page.locator('.training-studio input[type=file]').set_input_files({'name':'browser-training-demo.csv','mimeType':'text/csv','buffer':training.to_csv(index=False).encode()})
    page.get_by_label('Training split strategy').select_option('temporal')
    page.get_by_role('button',name='Train & evaluate three models').click()
    expect(page.get_by_role('button',name='Use this trained model',exact=True)).to_be_visible(timeout=45000)
    expect(page.locator('.training-candidate-table tbody tr')).to_have_count(3)
    try:
        page.get_by_role('button',name='Use this trained model',exact=True).click()
        expect(page.locator('.dataset-strip')).to_contain_text('browser-training-demo.csv',timeout=15000)
        page.get_by_label('Previously used model').select_option(original)
        page.get_by_role('button',name='Use selected model',exact=True).click()
        expect(page.locator('.dataset-strip')).to_contain_text('UCI AI4I 2020',timeout=15000)
    finally:
        restored=page.request.post(base+f'/api/training/versions/{original}/activate',data={})
        assert restored.ok,restored.text()
    for width in [1440,768,390]:
        page.set_viewport_size({'width':width,'height':900})
        for route in ['machines','maintenance','models']:
            page.goto(base+'/'+route);expect(page.locator('.workspace-page-heading')).to_be_visible();page.wait_for_timeout(700)
            if page.evaluate('document.documentElement.scrollWidth > innerWidth'):
                page.screenshot(path=str(OUT/f'integration-overflow-{width}-{route}.png'),full_page=True)
                raise AssertionError(f'Horizontal overflow: {width} / {route}')
    assert not errors,errors
    print(json.dumps({'status':'passed','checks':['timestamped CSV import','machine timeline','product-type comparison','inspection creation and resolution','confirmed-outcome CSV','replay step and completion','three-model temporal training','candidate activation','original-model restoration','desktop tablet mobile layouts'],'javascript_errors':errors}))
    browser.close()
