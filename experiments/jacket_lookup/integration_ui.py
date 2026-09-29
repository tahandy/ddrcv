"""Headless Edge checks against the real desktop/workbench HTTP surfaces."""
from copy import deepcopy
import json
import logging
from pathlib import Path
import tempfile
import threading

from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

from ddrcv.desktop.controller import Desk
from ddrcv.desktop.app import create_app as desk_app
from ddrcv.workbench.controller import Workbench
from ddrcv.workbench.app import create_app as workbench_app

ROOT=Path.cwd()
OUT=ROOT/'experiments/jacket_lookup/artifacts/integration'
snapshot=next(e['snapshot'] for e in json.loads((OUT/'paced-3.json').read_text(encoding='utf-8'))['episodes']
              if any(c and c['max_ex'] for c in e['snapshot']['song']['charts'].values()))
logging.getLogger('werkzeug').setLevel(logging.ERROR)


def serve(app):
    server=make_server('127.0.0.1',0,app,threaded=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    return server,'http://127.0.0.1:'+str(server.server_port)


def main():
    reports=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel='msedge',headless=True)
        with tempfile.TemporaryDirectory() as tmp:
            desk=Desk(Path(tmp)/'desk')
            original=desk.status
            def status():
                data=original()
                data['published'].update(deepcopy(snapshot))
                return data
            desk.status=status
            server,url=serve(desk_app(desk,'ui-validation'))
            context=browser.new_context(viewport={'width':1280,'height':1000})
            page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.add_init_script("window.pywebview={api:{session:async()=>({token:'ui-validation'}),pick:async(action)=>{if(action!=='catalog')throw Error(action);return " + json.dumps(str(OUT/'dia_del_ritmo_26.ddrcatalog')) + ";}}}")
            try:
                page.goto(url)
                page.evaluate("window.dispatchEvent(new Event('pywebviewready'))")
                page.wait_for_function("document.querySelector('[data-path=\"song_lookup.event\"]').value==='dia_del_ritmo_26'")
                page.locator('#tab-song').click()
                assert not page.locator('[data-path="song_lookup.enabled"]').is_checked()
                assert page.locator('#panel-session').is_hidden()
                event = page.locator('#song-event').input_value()
                page.locator('#song-mode').select_option('full')
                assert page.locator('#song-event').is_disabled()
                assert float(page.locator('#song-event-field').evaluate('(e) => getComputedStyle(e).opacity')) < 1
                page.locator('#song-mode').select_option('event')
                assert page.locator('#song-event').is_enabled()
                assert page.locator('#song-event').input_value() == event
                page.locator('#song-settings details > summary').click()
                assert page.locator('[data-path="song_lookup.high_qos"]').is_checked()
                page.locator('#song-browse').click()
                page.wait_for_function("document.getElementById('song-assets').value.endsWith('.ddrcatalog')")
                page.locator('#song-check').click()
                page.wait_for_function("document.getElementById('song-readiness').textContent.startsWith('Ready')",timeout=20000)
                page.wait_for_function("document.getElementById('song-catalog-version').textContent.startsWith('c62053fa')",timeout=20000)
                assert '2026' in page.locator('#song-catalog-updated').inner_text()
                assert '31d166b19367' in page.locator('#song-gallery-version').inner_text()
                assert '.ddrcatalog' in page.locator('#song-storage-path').inner_text()
                page.locator('.catalog-sharing > summary').click()
                assert 'No extraction' in page.locator('.catalog-sharing').inner_text()
                page.locator('[data-path="song_lookup.difficulty_method"]').select_option('ocr')
                page.wait_for_timeout(500)
                assert desk.draft['song_lookup']['difficulty_method']=='ocr'
                page.locator('[data-path="song_lookup.difficulty_method"]').select_option('template')
                assert '1881' in page.locator('#song-charts').inner_text()
                assert snapshot['song']['title'] in page.locator('#song-title').inner_text()
                page.screenshot(path=str(OUT/'desktop.png'),full_page=True)
                assert not errors,errors
                reports.append(dict(surface='desktop',ok=True,checks=['song-tab','full-mode-disables-event','catalog-version-and-date','storage-and-sharing','catalog-file-browse','opt-in','default-event','high-qos','readiness','difficulty-toggle','song-and-max-ex-rendering']))
            finally:
                context.close();server.shutdown();desk.close()
            wb=Workbench(Path(tmp)/'workbench',start_publisher=False)
            original=wb.status
            def wb_status():
                data=original()
                data['published'].update(deepcopy(snapshot))
                return data
            wb.status=wb_status
            def browse(directory=False, catalog=False):
                assert catalog and not directory
                return str(OUT/'dia_del_ritmo_26.ddrcatalog')
            wb.browse_path=browse
            server,url=serve(workbench_app(wb))
            context=browser.new_context(viewport={'width':1440,'height':1100})
            page=context.new_page();errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            try:
                page.goto(url)
                page.wait_for_function("document.getElementById('song-event').value==='dia_del_ritmo_26'")
                page.locator('#tab-song').click()
                assert not page.locator('#song-enabled').is_checked()
                assert page.locator('#panel-playback').is_hidden()
                event = page.locator('#song-event').input_value()
                page.locator('#song-mode').select_option('full')
                assert page.locator('#song-event').is_disabled()
                page.locator('#song-mode').select_option('event')
                assert page.locator('#song-event').is_enabled()
                assert page.locator('#song-event').input_value() == event
                page.locator('#song-settings details > summary').click()
                page.locator('#song-browse').click()
                page.wait_for_function("document.getElementById('song-assets').value.endsWith('.ddrcatalog')")
                page.locator('#song-check').click()
                page.wait_for_function("document.getElementById('song-readiness').textContent.startsWith('Ready')",timeout=20000)
                page.wait_for_function("document.getElementById('song-catalog-version').textContent.startsWith('c62053fa')",timeout=20000)
                assert '2026' in page.locator('#song-catalog-updated').inner_text()
                assert '31d166b19367' in page.locator('#song-gallery-version').inner_text()
                assert '.ddrcatalog' in page.locator('#song-storage-path').inner_text()
                page.locator('.catalog-sharing > summary').click()
                assert 'No extraction' in page.locator('.catalog-sharing').inner_text()
                page.locator('#song-enabled').check()
                page.locator('#song-apply').click()
                page.wait_for_function("document.getElementById('song-active-version').textContent.includes('c62053fa')",timeout=20000)
                assert wb.settings['song_lookup']['enabled']
                assert wb.splash.status()['phase']=='ready',wb.splash.status()
                page.wait_for_function("document.getElementById('song-active-version').textContent.includes('c62053fa')")
                assert '1881' in page.locator('#song-charts').inner_text()
                page.screenshot(path=str(OUT/'workbench.png'),full_page=True)
                assert not errors,errors
                reports.append(dict(surface='workbench',ok=True,checks=['song-tab','full-mode-disables-event','catalog-version-and-date','storage-and-sharing','catalog-file-browse','active-version','opt-in','readiness','apply','song-and-max-ex-rendering']))
            finally:
                context.close();server.shutdown();wb.close()
        browser.close()
    (OUT/'browser.json').write_text(json.dumps(reports,indent=2))
    print(reports)


if __name__=='__main__':main()
