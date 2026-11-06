"""Build the single-file demo (USDM_P21_Workbench_Demo.html) from the local app, so both share one UI and engine.

The app's index.html + engine.js are inlined; demo/standalone_shim.js routes the app's /app/* server calls to embedded data
(COSMoS catalogue, sample USDM, and the master standard + terminology cut built exactly as the server does) and to P21
export files the user loads in the browser.

usage: python 05_build_demo_html.py <app_dir> <sdtm_export.json> <term_export.json> <out.html>
"""
import json, os, sys, importlib.util

app_dir, std_path, term_path, out = sys.argv[1:5]
spec = importlib.util.spec_from_file_location('usdm_p21_app', os.path.join(app_dir, 'usdm_p21_app.py'))
srv = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)   # reuse build_master() / catalogue loading
master = srv.build_master(json.load(open(std_path, encoding='utf-8')), json.load(open(term_path, encoding='utf-8')))
embed = {'catalogue': srv.CATALOGUE, 'sample': json.load(open(os.path.join(app_dir, 'data', 'sample_usdm_no_extensions.json'), encoding='utf-8')),
         'master': master}
safe = lambda s: s.replace('</', '<\\/')            # JSON data
code = lambda s: s.replace('</script', '<\\/script')  # JS source (keep regex literals intact)
html = open(os.path.join(app_dir, 'static', 'index.html'), encoding='utf-8').read()
engine = open(os.path.join(app_dir, 'static', 'engine.js'), encoding='utf-8').read()
shim = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'demo', 'standalone_shim.js'), encoding='utf-8').read()
tag = '<script src="engine.js"></script>'
assert tag in html, 'engine script tag not found in index.html'
html = html.replace(tag, '<script>window.__EMBED = ' + safe(json.dumps(embed, separators=(',', ':'))) + ';</script>\n'
                    '<script>' + code(engine) + '</script>\n<script>' + code(shim) + '</script>')
html = html.replace('<title>USDM → P21 Workbench (POC)</title>', '<title>USDM → P21 Workbench (standalone demo)</title>')
html = html.replace('P21 MDR · USDM Workbench · local POC', 'P21 MDR · USDM Workbench · standalone demo')
open(out, 'w', encoding='utf-8').write(html)
print(out, os.path.getsize(out) // 1024, 'KB')
