#!/usr/bin/env python3
"""USDM -> P21 Workbench (local POC server).

Serves the workbench UI on http://127.0.0.1:<port> and proxies the read-only P21 Enterprise REST API
(https://help.pinnacle21.certara.net/en/articles/9718617) so the API key never reaches the browser:
    GET /api/standards                    list standards
    GET /api/standards/:id/export         export a standard (json)
    GET /api/terminologies                list terminologies
    GET /api/terminologies/:id/export     export a terminology (json)
    GET /api/metadata/forms               list library form specs
    GET /api/forms/:id/export             export a form spec (json)
Auth: "Authorization: Basic base64(<key>:<key>)".
With no API key configured the app runs OFFLINE from exports placed in ./p21_exports (same JSON as /export).

Python 3.8+ standard library only.  Usage:  python usdm_p21_app.py [--port 8765] [--no-browser]
"""
import argparse, base64, collections, json, os, sys, threading, time, urllib.error, urllib.parse, urllib.request, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC, DATA, EXPORTS, CACHE = (os.path.join(HERE, d) for d in ('static', 'data', 'p21_exports', 'cache'))
CONFIG_FILE = os.path.join(HERE, 'config.json')
os.makedirs(CACHE, exist_ok=True); os.makedirs(EXPORTS, exist_ok=True)

STATE = {'base_url': '', 'api_key': '', 'remember': False}
if os.path.exists(CONFIG_FILE):
    try: STATE.update(json.load(open(CONFIG_FILE)))
    except Exception: pass
CATALOGUE = json.load(open(os.path.join(DATA, 'cosmos_catalogue.json')))
_lock = threading.Lock()


# ----------------------------------------------------------------------------- P21 access
class P21Error(Exception):
    pass

def online():
    return bool(STATE['base_url'] and STATE['api_key'])

def p21_get(path, params=None, timeout=300):
    url = STATE['base_url'].rstrip('/') + path + ('?' + urllib.parse.urlencode(params) if params else '')
    tok = base64.b64encode(f"{STATE['api_key']}:{STATE['api_key']}".encode()).decode()
    req = urllib.request.Request(url, headers={'Authorization': 'Basic ' + tok, 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', 'replace')[:300]
        raise P21Error({401: 'Unauthorised - check the API key', 403: 'Forbidden - ID does not exist or no access',
                        404: 'Not found'}.get(e.code, f'HTTP {e.code}') + (f': {body}' if body else ''))
    except urllib.error.URLError as e:
        raise P21Error(f'Cannot reach {STATE["base_url"]}: {e.reason}')

def _first_list(obj):
    """P21 list endpoints: tolerate a bare list or an object wrapping a list."""
    if isinstance(obj, list): return obj
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, list) and (not v or isinstance(v[0], dict)): return v
    return []

def _norm(item):
    g = lambda *ks: next((item[k] for k in ks if k in item and item[k] not in (None, '')), '')
    return {'id': str(g('specId', 'id', 'spec_id')), 'name': g('name', 'title'), 'version': str(g('version')), 'type': g('type', 'standardType'),
            'status': g('status'), 'publisher': g('publisher'), 'description': g('description'), 'lastModified': g('lastModified')}

_offline_index = {}
def offline_index():
    """Read headers of every JSON export in ./p21_exports (cached by mtime)."""
    out = {'standards': [], 'terminologies': [], 'forms': []}
    for fn in sorted(os.listdir(EXPORTS)):
        if not fn.lower().endswith('.json'): continue
        p = os.path.join(EXPORTS, fn); key = (p, os.path.getmtime(p))
        if key not in _offline_index:
            try:
                with open(p, encoding='utf-8') as fh: head = fh.read(4000)
                kind = 'standards' if '"standard"' in head[:1500] else 'terminologies' if '"terminology"' in head[:1500] else 'forms' if '"forms"' in head else None
                d = json.load(open(p, encoding='utf-8'))
                hdr = d.get('standard') or d.get('terminology') or (d.get('forms') if isinstance(d.get('forms'), dict) else {}) or {}
                if kind == 'forms' and not hdr: hdr = {'name': fn[:-5]}
                _offline_index[key] = (kind, dict(_norm(hdr), file=fn, id=str(hdr.get('specId') or fn)))
            except Exception as e:
                _offline_index[key] = (None, {'file': fn, 'error': str(e)})
        kind, rec = _offline_index[key]
        if kind: out[kind].append(rec)
    return out

def list_specs(kind):
    if online():
        path = {'standards': '/api/standards', 'terminologies': '/api/terminologies', 'forms': '/api/metadata/forms'}[kind]
        return {'mode': 'online', 'items': [_norm(x) for x in _first_list(p21_get(path))]}
    return {'mode': 'offline', 'items': offline_index()[kind]}

def export_spec(kind, sid, published=False, refresh=False):
    if not online():
        rec = next((r for r in offline_index()[kind] if r['id'] == str(sid)), None)
        if not rec: raise P21Error(f'{kind[:-1]} {sid} not found in p21_exports')
        return json.load(open(os.path.join(EXPORTS, rec['file']), encoding='utf-8'))
    cp = os.path.join(CACHE, f'{kind}_{sid}{"_pub" if published else ""}.json')
    if os.path.exists(cp) and not refresh and time.time() - os.path.getmtime(cp) < 24 * 3600:
        return json.load(open(cp, encoding='utf-8'))
    path = {'standards': f'/api/standards/{sid}/export', 'terminologies': f'/api/terminologies/{sid}/export', 'forms': f'/api/forms/{sid}/export'}[kind]
    params = {'format': 'json'}
    if published: params['usePublished'] = 'true'
    d = p21_get(path, params)
    json.dump(d, open(cp, 'w', encoding='utf-8'))
    return d


# ----------------------------------------------------------------------------- master subset for the engine
def build_master(std, term):
    """Compact the selected standard + terminology to what the browser engine needs (all P21 internalIds kept)."""
    sdtm, crf = CATALOGUE['sdtm'], CATALOGUE['crf']
    S = CATALOGUE['SCOLS']; C = CATALOGUE['CCOLS']
    iCL, iAV, iVL = S.index('codelist_submission_value'), S.index('assigned_value'), S.index('value_list')
    jCL, jVL, jPP = C.index('codelist_submission_value'), C.index('value_list'), C.index('prepopulated_term')
    sh = std.get('standard', {}); th = term.get('terminology', {})
    std_doms = {d['dataset'] for d in std.get('datasets', [])}
    doms = ({v['d'] for v in sdtm.values()} | {v['d'] for v in crf.values()} | {'TA', 'TE', 'TV', 'TI', 'TS'}) & std_doms
    dsets = {d['dataset']: {'id': d.get('internalId'), 'label': d.get('label'), 'class': d.get('class'), 'structure': d.get('structure'),
                            'keys': d.get('keyVariables'), 'repeating': d.get('repeating'), 'ref': d.get('referenceData')}
             for d in std.get('datasets', []) if d['dataset'] in doms}
    VC = ['variable', 'internalId', 'order', 'label', 'dataType', 'length', 'core', 'codelist', 'origin', 'role']
    vars_ = collections.defaultdict(list)
    for v in std.get('variables', []):
        if v.get('dataset') in dsets: vars_[v['dataset']].append([v.get(c) for c in VC])
    referenced = collections.defaultdict(set)
    for s in sdtm.values():
        for r in s['rows']:
            if r[iCL]:
                for x in ([r[iAV]] if r[iAV] else r[iVL].split(';')): referenced[r[iCL]].add(x)
    for c in crf.values():
        for i in c['items']:
            if i[jCL]:
                for x in (i[jVL].split(';') if i[jVL] else [i[jPP]]): referenced[i[jCL]].add(x)
    used = set(referenced) | {v[7] for vs in vars_.values() for v in vs if v[7]} | {
        'TSPARMCD', 'TSPARM', 'UNIT', 'ROUTE', 'FRM', 'FREQ', 'TPHASE', 'STYPE', 'INTMODEL', 'TBLIND', 'TTYPE', 'TINDTP', 'INTTYPE', 'SEXPOP', 'NY', 'TCNTRL', 'IECAT', 'EPOCH'}
    tby = collections.defaultdict(list)
    for t in term.get('terms', []): tby[t.get('codelist')].append(t)
    cls, terms = {}, {}
    for c in term.get('codelists', []):
        if c.get('id') not in used: continue
        allt = tby[c['id']]
        cls[c['id']] = {'id': c.get('internalId'), 'name': c.get('name'), 'nci': c.get('nciCode'), 'ext': c.get('extensible') or 'Yes',
                        'type': c.get('dataType'), 'n': len(allt), 'partial': len(allt) > 1000}
        keep = allt if len(allt) <= 1000 else [t for t in allt if t.get('term') in referenced[c['id']]]
        terms[c['id']] = [[t.get('internalId'), t.get('term'), t.get('decodedValue'), t.get('nciCode')] for t in keep]
    return {'std': {'specId': sh.get('specId'), 'name': sh.get('name'), 'version': sh.get('version'), 'type': sh.get('type')},
            'ct': {'specId': th.get('specId'), 'name': th.get('name'), 'version': th.get('version')},
            'datasets': dsets, 'vars': vars_, 'VC': VC, 'codelists': cls, 'terms': terms, 'ctTotalTerms': len(term.get('terms', []))}

def compact_forms(fx):
    """Keep the parts of a P21 form spec export the workbench uses. The export uses 'forms' both for the spec header
    (object) and the forms tab (array), so locate the forms array structurally if needed."""
    hdr = fx.get('forms') if isinstance(fx.get('forms'), dict) else {}
    pick = lambda k: fx.get(k) if isinstance(fx.get(k), list) else []
    forms = fx['forms'] if isinstance(fx.get('forms'), list) else []
    if not forms:
        for k, v in fx.items():
            if isinstance(v, list) and v and isinstance(v[0], dict) and 'id' in v[0] and 'isRepeating' in v[0] and 'forms' not in v[0] and 'form' not in v[0]:
                forms = v; break
    questions = pick('questions')
    if not forms:
        seen = []
        for q in questions:
            if q.get('form') and q['form'] not in seen: seen.append(q['form'])
        forms = [{'id': f, 'name': f} for f in seen]
    return {'header': hdr, 'forms': forms, 'events': pick('events'), 'sections': pick('sections'), 'questions': questions,
            'codelists': pick('codelists'), 'terms': pick('terms'), 'units': pick('units')}


# ----------------------------------------------------------------------------- HTTP
class H(BaseHTTPRequestHandler):
    server_version = 'USDM-P21-Workbench/0.2'
    def log_message(self, fmt, *a): sys.stderr.write('[%s] %s\n' % (time.strftime('%H:%M:%S'), fmt % a))
    def _send(self, code, body, ctype='application/json'):
        b = body if isinstance(body, bytes) else (json.dumps(body) if ctype == 'application/json' else body).encode('utf-8')
        self.send_response(code); self.send_header('Content-Type', ctype + ('; charset=utf-8' if 'json' in ctype or 'html' in ctype or 'javascript' in ctype else ''))
        self.send_header('Content-Length', str(len(b))); self.send_header('Cache-Control', 'no-store'); self.end_headers(); self.wfile.write(b)
    def _err(self, code, msg): self._send(code, {'error': msg})
    def _body(self):
        n = int(self.headers.get('Content-Length') or 0); return json.loads(self.rfile.read(n) or b'{}')

    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = dict(urllib.parse.parse_qsl(u.query)); p = u.path
        try:
            if p in ('/', '/index.html'): return self._send(200, open(os.path.join(STATIC, 'index.html'), 'rb').read(), 'text/html')
            if p == '/engine.js': return self._send(200, open(os.path.join(STATIC, 'engine.js'), 'rb').read(), 'application/javascript')
            if p == '/app/config':
                return self._send(200, {'base_url': STATE['base_url'], 'has_key': bool(STATE['api_key']), 'remember': STATE['remember'], 'mode': 'online' if online() else 'offline'})
            if p == '/app/catalogue': return self._send(200, open(os.path.join(DATA, 'cosmos_catalogue.json'), 'rb').read())
            if p == '/app/sample': return self._send(200, open(os.path.join(DATA, 'sample_usdm_no_extensions.json'), 'rb').read())
            if p in ('/app/standards', '/app/terminologies', '/app/forms'): return self._send(200, list_specs(p.split('/')[-1]))
            if p == '/app/test':
                if not online(): return self._send(200, {'ok': False, 'mode': 'offline', 'message': 'No API key configured - using local exports'})
                n = len(_first_list(p21_get('/api/standards', timeout=30)))
                return self._send(200, {'ok': True, 'mode': 'online', 'message': f'Connected - {n} standards visible'})
            return self._err(404, 'not found')
        except P21Error as e: return self._err(502, str(e))
        except Exception as e: return self._err(500, f'{type(e).__name__}: {e}')

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        try:
            b = self._body()
            if p == '/app/config':
                with _lock:
                    STATE['base_url'] = (b.get('base_url') or '').strip().rstrip('/')
                    if b.get('api_key'): STATE['api_key'] = b['api_key'].strip()
                    if b.get('clear_key'): STATE['api_key'] = ''
                    STATE['remember'] = bool(b.get('remember'))
                    if STATE['remember']: json.dump(STATE, open(CONFIG_FILE, 'w'))
                    elif os.path.exists(CONFIG_FILE): os.remove(CONFIG_FILE)
                return self._send(200, {'ok': True, 'mode': 'online' if online() else 'offline'})
            if p == '/app/master':
                t0 = time.time()
                std = export_spec('standards', b['standardId'], b.get('published'), b.get('refresh'))
                term = export_spec('terminologies', b['terminologyId'], b.get('published'), b.get('refresh'))
                m = build_master(std, term); m['elapsed'] = round(time.time() - t0, 1); m['mode'] = 'online' if online() else 'offline'
                return self._send(200, m)
            if p == '/app/formlib':
                return self._send(200, compact_forms(export_spec('forms', b['formId'], b.get('published'), b.get('refresh'))))
            return self._err(404, 'not found')
        except P21Error as e: return self._err(502, str(e))
        except KeyError as e: return self._err(400, f'missing {e}')
        except Exception as e: return self._err(500, f'{type(e).__name__}: {e}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--port', type=int, default=8765); ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--base-url', help='P21E root URL, e.g. https://my-company.pinnacle21.com')
    a = ap.parse_args()
    if a.base_url: STATE['base_url'] = a.base_url.rstrip('/')
    if os.environ.get('P21_API_KEY'): STATE['api_key'] = os.environ['P21_API_KEY']
    srv = ThreadingHTTPServer(('127.0.0.1', a.port), H)
    url = f'http://127.0.0.1:{a.port}/'
    print(f'USDM -> P21 Workbench running at {url}  (mode: {"online" if online() else "offline - ./p21_exports"})  Ctrl+C to stop')
    if not a.no_browser: threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: print('\nstopped')

if __name__ == '__main__':
    main()
