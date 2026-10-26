"""Build (1) a USDM with NO specialization extensions (generic COSMoS BC names, specimen-agnostic properties)
and (2) the compact data blob embedded in the demo HTML: local specialization catalogue (SDTM + CRF),
master SDTMIG subset and CT subset with P21 internalIds.
usage: python 04_build_demo_data.py <ref_dir> <usdm_with_ext.json> <sdtm34.json> <term34.json> <out_dir>"""
import json, csv, sys, copy, collections
REF, USDM, STD, TERM, OUT = sys.argv[1:6]
hdr = json.load(open(f'{REF}/cosmos_headers.json')); std = json.load(open(STD)); term = json.load(open(TERM))
SD = 'http://www.cdisc.org/usdm/extensions/specializations/sdtm'

# ---------- 1. USDM without extensions ----------
u = json.load(open(USDM)); sv = u['study']['versions'][0]
FIX_CODE = {'UROBILURINPRES': ('C64816', 'Urobilinogen Measurement')}   # COSMoS tags UROBILURINPRES with the nitrite BC (C64810)
for bc in sv['biomedicalConcepts']:
    spec = next((e['valueString'].split('/')[-1] for e in bc['extensionAttributes'] if e['url'] == SD), None)
    code = bc['code']['standardCode']['code']; name = None
    if spec in FIX_CODE: code, name = FIX_CODE[spec]; bc['code']['standardCode']['code'] = code
    bh = hdr['bc'].get(code, {})
    name = name or bh.get('shortName') or bc['name']
    bc['name'] = name; bc['label'] = name; bc['code']['standardCode']['decode'] = name
    bc['reference'] = f'/mdr/bc/biomedicalconcepts/{code}'
    bc['synonyms'] = bh.get('synonyms') or []
    # generic BC properties (all DECs, no specialization-derived response codes)
    props = []
    for i, dec in enumerate(bh.get('dataElementConcepts', []), 1):
        props.append({'id': f"{bc['id']}_P{i}", 'name': dec['shortName'], 'label': dec['shortName'], 'isRequired': False, 'isEnabled': True,
                      'datatype': dec.get('dataType', ''), 'responseCodes': [], 'notes': [], 'extensionAttributes': [], 'instanceType': 'BiomedicalConceptProperty',
                      'code': {'id': f"{bc['id']}_P{i}_AC", 'instanceType': 'AliasCode', 'standardCodeAliases': [], 'extensionAttributes': [],
                               'standardCode': {'id': f"{bc['id']}_P{i}_C", 'instanceType': 'Code', 'code': dec['conceptId'], 'codeSystem': 'http://www.cdisc.org',
                                                'codeSystemVersion': term['terminology']['version'], 'decode': dec['shortName'], 'extensionAttributes': []}}})
    if props: bc['properties'] = props
    bc['extensionAttributes'] = []
from usdm_model.wrapper import Wrapper
Wrapper.model_validate(u)
json.dump(u, open(f'{OUT}/CTX101-001_USDM_v4_no-extensions.json', 'w'), indent=2)

# ---------- 2. catalogue ----------
sd = collections.defaultdict(list)
for r in csv.DictReader(open(f'{REF}/cosmos_sdtm_item.csv')): sd[r['vlm_group_id']].append(r)
SCOLS = ['sdtm_variable', 'dec_id', 'codelist_submission_value', 'assigned_value', 'value_list', 'role', 'data_type', 'length', 'significant_digits',
         'mandatory_variable', 'mandatory_value', 'origin_type', 'origin_source', 'comparator', 'vlm_target', 'nsv_flag']
sdtm = {k: {'d': hdr['sdtm'][k]['domain'], 'bc': hdr['sdtm'][k].get('biomedicalConceptId'), 'name': hdr['sdtm'][k]['shortName'],
            'pkg': str(hdr['sdtm'][k]['packageDate']), 'rows': [[r[c] for c in SCOLS] for r in rows]} for k, rows in sd.items()}
cr = collections.defaultdict(list)
for r in csv.DictReader(open(f'{REF}/cosmos_crf_item.csv')): cr[r['crf_specialization_id']].append(r)
CCOLS = ['crf_item', 'variable_name', 'dec_id', 'question_text', 'prompt', 'order_number', 'mandatory_variable', 'data_type', 'length', 'significant_digits',
         'display_hidden', 'codelist_submission_value', 'value_list', 'value_list_display', 'prepopulated_term', 'selection_type', 'sdtm_annotation', 'sdtm_target_variables']
crf = {k: {'d': hdr['crf'][k]['domain'], 'bc': hdr['crf'][k].get('biomedicalConceptId'), 'sdtm': hdr['crf'][k].get('sdtmDatasetSpecializationId'),
           'name': hdr['crf'][k]['shortName'], 'impl': hdr['crf'][k].get('implementationOption', ''), 'pkg': str(hdr['crf'][k]['packageDate']),
           'items': [[r[c] for c in CCOLS] for r in sorted(rows, key=lambda r: int(r['order_number'] or 0))]} for k, rows in cr.items()}

# ---------- 3. master standard + CT subsets ----------
doms = sorted({v['d'] for v in sdtm.values()} | {v['d'] for v in crf.values()} | {'TA', 'TE', 'TV', 'TI', 'TS'})
dsets = {d['dataset']: {'id': d['internalId'], 'label': d['label'], 'class': d['class'], 'structure': d['structure'], 'keys': d['keyVariables'],
                        'repeating': d['repeating'], 'ref': d['referenceData']} for d in std['datasets'] if d['dataset'] in doms}
VC = ['variable', 'internalId', 'order', 'label', 'dataType', 'length', 'core', 'codelist', 'origin', 'role']
vars_ = collections.defaultdict(list)
for v in std['variables']: vars_[v['dataset']].append([v[c] for c in VC])   # all domains (order inference)
classes = {d['dataset']: d['class'] for d in std['datasets']}
used_cl = {r[2] for s in sdtm.values() for r in s['rows'] if r[2]} | {v[7] for d_, vs in vars_.items() if d_ in dsets for v in vs if v[7]} | \
          {i[11] for c in crf.values() for i in c['items'] if i[11]} | {'TSPARMCD', 'TSPARM', 'UNIT', 'ROUTE', 'FRM', 'FREQ', 'TPHASE', 'STYPE', 'INTMODEL', 'TBLIND',
                                                                     'TTYPE', 'TINDTP', 'INTTYPE', 'SEXPOP', 'NY', 'TCNTRL', 'IECAT', 'EPOCH', 'ARMNULRS'}
referenced = collections.defaultdict(set)
for s in sdtm.values():
    for r in s['rows']:
        if r[2]:
            for x in ([r[3]] if r[3] else r[4].split(';')): referenced[r[2]].add(x)
for c in crf.values():
    for i in c['items']:
        if i[11]:
            for x in (i[12].split(';') if i[12] else [i[14]]): referenced[i[11]].add(x)
cls, terms = {}, {}
tby = collections.defaultdict(list)
for t in term['terms']: tby[t['codelist']].append(t)
for c in term['codelists']:
    if c['id'] not in used_cl: continue
    allt = tby[c['id']]
    cls[c['id']] = {'id': c['internalId'], 'name': c['name'], 'nci': c['nciCode'], 'ext': c['extensible'], 'type': c['dataType'], 'n': len(allt),
                    'partial': len(allt) > 1000}
    keep = allt if len(allt) <= 1000 else [t for t in allt if t['term'] in referenced[c['id']]]
    terms[c['id']] = [[t['internalId'], t['term'], t['decodedValue'], t['nciCode']] for t in keep]
data = {'std': {'specId': std['standard']['specId'], 'name': std['standard']['name'], 'version': std['standard']['version']},
        'ct': {'specId': term['terminology']['specId'], 'name': term['terminology']['name'], 'version': term['terminology']['version']},
        'SCOLS': SCOLS, 'CCOLS': CCOLS, 'VC': VC, 'sdtm': sdtm, 'crf': crf, 'datasets': dsets, 'classes': classes, 'vars': vars_, 'codelists': cls, 'terms': terms}
s = json.dumps(data, separators=(',', ':'))
open(f'{OUT}/demo_data.json', 'w').write(s)
print('no-ext USDM written; data blob', len(s) // 1024, 'KB;', len(sdtm), 'sdtm specs', len(crf), 'crf specs', len(cls), 'codelists', sum(map(len, terms.values())), 'terms')
