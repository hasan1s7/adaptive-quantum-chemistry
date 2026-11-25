from pathlib import Path
import csv,io,threading,http.server,functools
from playwright.sync_api import sync_playwright
server=http.server.ThreadingHTTPServer(('127.0.0.1',0),functools.partial(http.server.SimpleHTTPRequestHandler,directory=str(Path(__file__).parent)))
threading.Thread(target=server.serve_forever,daemon=True).start()
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox','--disable-dev-shm-usage']);page=browser.new_page(viewport={'width':1360,'height':900},accept_downloads=True);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 html=(Path(__file__).parent/'index.html').read_text();import re;html=re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>','',html).replace('<link rel="stylesheet" href="style.css">','<style>'+Path('style.css').read_text()+'</style>').replace('<script defer src="data.js"></script>','').replace('<script defer src="app.js"></script>','');page.set_content(html);page.add_script_tag(content=Path('data.js').read_text());page.add_script_tag(content=Path('app.js').read_text());assert page.locator('#realStats').inner_text().startswith('95.19%');assert '670' in page.locator('#pilotRows').inner_text();page.screenshot(path='../pages-desktop.png',full_page=True)
 for t,n in [('0.02','802'),('0.05','571'),('0.1','503')]:
  page.select_option('#realPenalty',t);assert n in page.locator('#realStats').inner_text()
 for t in ('0.02','0.05','0.1'):
  page.select_option('#pilotPenalty',t)
  for r in ('0','.001','.01','0.8755314022957967','1','5'):
   page.fill('#ratio',r);assert page.locator('#pilotRows tr').count()==5;assert 'NaN' not in page.locator('#pilotRows').inner_text()
 page.fill('#ratio','-1');assert page.locator('#export').is_disabled();page.click('#measured');assert page.locator('#export').is_enabled();page.click('#free');assert float(page.input_value('#ratio'))==0;page.click('#measured');assert abs(float(page.input_value('#ratio'))-.8755314022957967)<1e-10
 page.select_option('#pilotPenalty','0.05');
 with page.expect_download() as d:page.click('#export')
 content=Path(d.value.path()).read_text();rows=list(csv.DictReader(io.StringIO(content)));assert len(rows)==5 and rows[2]['reference_calls']=='670' and rows[2]['success_n']=='331';Path('../pages-export.csv').write_text(content)
 for a in ('0.05','0.1','0.2'):
  page.select_option('#pairAmp',a)
  for m in ('spectral','mac'):
   page.select_option('#pairMetric',m);assert page.locator('#paired .barrow').count()==4
 for a in ('0.05','0.1','0.2'):
  page.select_option('#amp',a)
  for m in ('linear','circular'):
   page.select_option('#method',m)
   for k in (0,8,16):
    page.locator('#position').evaluate('(el,v)=>{el.value=v;el.dispatchEvent(new Event("input",{bubbles:true}))}',k);assert page.locator('#curve polyline').count()==2;assert page.locator('#shapeStats > div').count()==4;assert page.locator('#positionLabel').inner_text()==f'{[0,64,127][[0,8,16].index(k)]} / 127'
 before=page.locator('#mol').evaluate('c=>c.toDataURL()');page.locator('#mol').focus();page.keyboard.press('ArrowRight');after=page.locator('#mol').evaluate('c=>c.toDataURL()');assert before!=after
 page.click('#resetView');page.locator('#surface').screenshot(path='../pages-molecular.png')
 for width in (320,390,430):
  page.set_viewport_size({'width':width,'height':820});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
  page.select_option('#realPenalty','0.02');assert '802' in page.locator('#realStats').inner_text()
  page.select_option('#amp','0.2');page.select_option('#method','circular');assert page.locator('#curve polyline').count()==2
 page.set_viewport_size({'width':390,'height':820});page.screenshot(path='../pages-mobile.png',full_page=True)
 assert not errors,errors;print('PASS: exact asset bodies in Chromium set_content (HTTP navigation administrator-blocked; CSP not exercised), 3 real thresholds, 18 pilot penalty/cost settings, invalid input, measured/free reset, actual CSV download, 6 paired conditions, 18 surface combinations, keyboard rotation, 320/390/430 widths; no JS errors')
 browser.close()
server.shutdown()
