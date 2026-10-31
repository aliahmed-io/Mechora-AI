"""Additional presentation checks: honest state, failure recovery, and every route."""
from pathlib import Path
import json
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output'/'qa';OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,channel='chrome')
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:3000/dashboard');page.wait_for_load_state('networkidle')
    analyses=page.request.get('http://127.0.0.1:3000/api/analyses').json()
    assert analyses,'Run the regular e2e demonstration first.'
    analysis=analyses[0]
    records=page.request.get(f'http://127.0.0.1:3000/api/analyses/{analysis["id"]}/records').json()['records']
    record=records[0]
    page.goto(f'http://127.0.0.1:3000/diagnostics?analysis={analysis["id"]}&record={record["record_id"]}')
    expect(page.get_by_text('What changes the estimate?')).to_be_visible(timeout=30000)
    saved_value=page.locator('.diagnosis-dial strong').inner_text()
    page.get_by_role('button',name='Single observation',exact=True).click()
    page.evaluate('''() => {
      const original=window.fetch.bind(window);
      window.fetch=async (...args) => {
        if(String(args[0]).endsWith('/predictions/single')) await new Promise(resolve=>setTimeout(resolve,1500));
        return original(...args);
      };
    }''')
    page.get_by_role('button',name='Estimate failure risk',exact=True).click()
    expect(page.get_by_role('button',name='Saved observation',exact=False)).to_be_disabled()
    expect(page.get_by_role('button',name='Single observation',exact=True)).to_be_disabled()
    expect(page.locator('.prediction-form input').first).to_be_disabled()
    expect(page.get_by_text('What changes the estimate?')).to_be_visible(timeout=15000)
    page.locator('.prediction-form input').first.fill('302.6')
    expect(page.get_by_text('What changes the estimate?')).not_to_be_visible()
    page.locator('.prediction-form input').nth(1).fill('200')
    page.get_by_role('button',name='Estimate failure risk',exact=True).click()
    expect(page.locator('.validation-error')).to_contain_text('Process temperature',timeout=15000)
    expect(page.locator('.diagnosis-result')).to_have_count(0)
    page.get_by_role('button',name='Saved observation',exact=False).click()
    expect(page.locator('.diagnosis-dial strong')).to_have_text(saved_value)
    expect(page.locator('.detail-machine')).to_contain_text(record['record_id'])
    # A missing batch must not leave the last successful batch on screen.
    page.goto('http://127.0.0.1:3000/dashboard?analysis=not-a-real-analysis')
    expect(page.locator('.error-box')).to_contain_text('Analysis not found',timeout=15000)
    expect(page.locator('.stat-card')).to_have_count(0)
    # A temporary service failure can be retried without a reload.
    page.route('**/api/models/metrics',lambda route:route.fulfill(status=503,content_type='application/json',body='{"detail":"The model is temporarily unavailable."}'))
    page.goto('http://127.0.0.1:3000/models')
    expect(page.locator('.error-box')).to_contain_text('temporarily unavailable',timeout=15000)
    page.unroute('**/api/models/metrics')
    page.get_by_role('button',name='Retry',exact=True).click()
    expect(page.get_by_text('Confusion matrix',exact=True)).to_be_visible(timeout=15000)
    # The file picker and drag-and-drop accept the same genuine CSV schema.
    page.goto('http://127.0.0.1:3000/import');page.wait_for_load_state('networkidle')
    csv=','.join(['Type','Air temperature [K]','Process temperature [K]','Rotational speed [rpm]','Torque [Nm]','Tool wear [min]'])+'\nM,298.1,308.6,1551,42.8,0\n'
    transfer=page.evaluate_handle('(csv)=>{const dt=new DataTransfer();dt.items.add(new File([csv],"presentation.csv",{type:"text/csv"}));return dt}',csv)
    page.locator('.upload-zone').dispatch_event('drop',{'dataTransfer':transfer})
    expect(page.get_by_text('Schema verified')).to_be_visible(timeout=15000)
    page.get_by_role('button',name='Run analysis',exact=True).click()
    page.wait_for_url('**/dashboard?analysis=*',timeout=30000)
    expect(page.locator('.stat-card').first).to_contain_text('1')
    # Every application route remains usable at laptop, tablet and mobile sizes.
    for width in (1440,768,390):
        page.set_viewport_size({'width':width,'height':900})
        for route in ('dashboard','import','records','diagnostics','risk-analysis','models','reports'):
            page.goto('http://127.0.0.1:3000/'+route);page.wait_for_load_state('networkidle')
            if page.evaluate('document.documentElement.scrollWidth > innerWidth'):
                page.screenshot(path=str(OUT/f'overflow-{width}-{route}.png'),full_page=True)
                print(page.evaluate('Array.from(document.querySelectorAll("body *")).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right,width:e.getBoundingClientRect().width})).filter(e=>e.right>innerWidth+1).slice(0,25)'))
                raise AssertionError((width,route))
            assert not page.locator('.error-box').count(),(width,route)
            if width==1440 and route in ('dashboard','diagnostics','reports'):page.screenshot(path=str(OUT/f'verified-{route}.png'),full_page=True)
    page.goto('http://127.0.0.1:3000/this-page-does-not-exist')
    expect(page.get_by_role('heading',name='A different direction.')).to_be_visible()
    expect(page.get_by_role('link',name='Open the workspace')).to_be_visible()
    assert not errors,errors
    print(json.dumps({'status':'passed','checks':['in-flight prediction state','changed-input result clearing','invalid-input recovery','saved-result restoration','missing-batch handling','service retry','CSV drag and drop','all seven routes at three viewport widths','404 recovery'],'javascript_errors':errors}))
    browser.close()
