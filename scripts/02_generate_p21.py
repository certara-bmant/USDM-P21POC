"""USDM -> P21 study artefact generation (Framing Pitch 2 POC).

Reads the USDM JSON, follows Activity.biomedicalConceptIds -> BC.extensionAttributes (SoA Workbench
specialization extensions) -> local COSMoS specialization tables, then:
  Flow 2  SDTM study define  : subset of master standard (sdtm34) + terminology (term34)
  Flow 1  CRF form spec      : Events / Forms / SoA / Questions / Codelists from CRF specializations
  Flow 3  Trial design       : TA, TE, TV, TI, TS rows from USDM
  + Study Object / Data Packages, coverage report, and a P21-linked copy of the USDM
    (Certara extension carrying P21 internalIds + natural keys on every BC).

usage: python 02_generate_p21.py <usdm.json> <reference_dir> <sdtm34.json> <term34.json> <out_dir> [--all-variables] [--no-vlm]
"""
import json, csv, sys, re, os, copy, collections, datetime

USDM, REF, STD, TERM, OUT = sys.argv[1:6]
MANDATORY_ONLY = '--all-variables' not in sys.argv
VLM_ON = '--no-vlm' not in sys.argv
NOW = datetime.datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
os.makedirs(OUT, exist_ok=True)

usdm = json.load(open(USDM)); std = json.load(open(STD)); term = json.load(open(TERM))
hdr = json.load(open(f'{REF}/cosmos_headers.json'))
sdtm_items = collections.defaultdict(list)
for r in csv.DictReader(open(f'{REF}/cosmos_sdtm_item.csv')): sdtm_items[r['vlm_group_id']].append(r)
crf_items = collections.defaultdict(list)
for r in csv.DictReader(open(f'{REF}/cosmos_crf_item.csv')): crf_items[r['crf_specialization_id']].append(r)
for v in crf_items.values(): v.sort(key=lambda r: int(r['order_number'] or 0))

STD_ID, CT_ID = std['standard']['specId'], term['terminology']['specId']
m_ds = {d['dataset']: d for d in std['datasets']}
m_var = collections.defaultdict(dict)
for v in std['variables']: m_var[v['dataset']][v['variable']] = v
m_cl = {c['id']: c for c in term['codelists']}
m_terms = collections.defaultdict(list)
for t in term['terms']: m_terms[t['codelist']].append(t)
m_term = {(t['codelist'], t['term']): t for t in term['terms']}
m_term_code = {(t['codelist'], t['nciCode']): t for t in term['terms']}
def sub(cl, c):
    """USDM Code -> SDTM submission value via NCI code (USDM decodes are NCI preferred terms, not submission values)."""
    t = m_term_code.get((cl, c['code'] if isinstance(c, dict) else c))
    return t['term'] if t else (c['decode'] if isinstance(c, dict) else c)
DICTIONARIES = {'MedDRA', 'WHODD', 'LOINC', 'SNOMED', 'UNII', 'ISO3166', 'ISO 3166', 'ISO 8601'}

report = collections.defaultdict(list)
def prov(**kw): return dict(generatedBy='USDM-P21 POC', generatedAt=NOW, usdmStudy=study['name'], **kw)

# ------------------------------------------------------------------ USDM navigation
study = usdm['study']; sv = study['versions'][0]; design = sv['studyDesigns'][0]
bc_by_id = {b['id']: b for b in sv['biomedicalConcepts']}
sur_by_id = {s['id']: s for s in sv['bcSurrogates']}
SDTM_URL = 'http://www.cdisc.org/usdm/extensions/specializations/sdtm'
CRF_URL = 'http://www.cdisc.org/usdm/extensions/specializations/crf'
def ext_val(obj, url):
    for e in obj.get('extensionAttributes', []):
        if e['url'] == url: return e.get('valueString', '').rstrip('/').split('/')[-1]
    return None

selected = []  # (activity, bc, sdtm spec id, crf spec id)
for act in design['activities']:
    for bid in act['biomedicalConceptIds']:
        bc = bc_by_id[bid]; s, c = ext_val(bc, SDTM_URL), ext_val(bc, CRF_URL)
        if s and s not in sdtm_items:
            report['specialization_not_in_local_table'].append({'bc': bc['name'], 'sdtmSpecialization': s}); s = None
        if c and c not in crf_items:
            report['specialization_not_in_local_table'].append({'bc': bc['name'], 'crfSpecialization': c}); c = None
        selected.append((act, bc, s, c))
        if not s: report['bc_without_sdtm_specialization'].append({'activity': act['name'], 'bc': bc['name']})
        if not c: report['bc_without_crf_specialization'].append({'activity': act['name'], 'bc': bc['name'], 'bcCode': bc['code']['standardCode']['code'], 'sdtmSpecialization': s})
    for sid in act.get('bcSurrogateIds', []):
        report['bc_surrogates_excluded'].append({'activity': act['name'], 'surrogate': sur_by_id[sid]['name'], 'description': sur_by_id[sid].get('description')})
for s in {x[2] for x in selected if x[2]}:
    if 'RETIRED' in hdr['sdtm'][s]['shortName']: report['retired_specializations_used'].append(s)

# ------------------------------------------------------------------ Flow 3: trial design domains (built first; feeds TS/TA codelist cut)
def dec(c): return c['decode'] if c else ''
def code_of(c): return c['code'] if c else ''
studyid = next(i['text'] for i in sv['studyIdentifiers'] if any(o['id'] == i['scopeId'] and o['type']['code'] == 'C54149' for o in sv['organizations']))
epochs = {e['id']: e for e in design['epochs']}
elements = {e['id']: e for e in design['elements']}
TA, TE, TV, TI, TS = [], [], [], [], []
ep_order = [e['id'] for e in design['epochs']]
for arm in design['arms']:
    cells = sorted([c for c in design['studyCells'] if c['armId'] == arm['id']], key=lambda c: ep_order.index(c['epochId']))
    n = 0
    for c in cells:
        for eid in c['elementIds']:
            n += 1; el = elements[eid]; ep = epochs[c['epochId']]
            branch = f"Randomized to {arm['label']}" if ep['type']['code'] == 'C202487' else ''
            TA.append(dict(STUDYID=studyid, DOMAIN='TA', ARMCD=arm['name'], ARM=arm['label'], TAETORD=n, ETCD=el['name'], ELEMENT=el['label'],
                           TABRANCH=branch, TATRANS='', EPOCH=ep['name'], _usdm=f"StudyCell[{arm['name']}x{ep['name']}].elementIds -> StudyElement {el['id']}"))
for el in design['elements']:
    TE.append(dict(STUDYID=studyid, DOMAIN='TE', ETCD=el['name'], ELEMENT=el['label'], TESTRL=(el.get('transitionStartRule') or {}).get('text', ''),
                   TEENRL=(el.get('transitionEndRule') or {}).get('text', ''), TEDUR='', _usdm=f"StudyElement {el['id']}"))
    report['trial_design_blank_fields'].append({'domain': 'TE', 'field': 'TEDUR', 'element': el['name'], 'reason': 'No element duration in USDM'})
tl = next(t for t in design['scheduleTimelines'] if t['mainTimeline'])
timing_by = {t['id']: t for t in tl['timings']}
encs = design['encounters']
def study_day(t):
    n = int(re.sub(r'\D', '', t['value']) or 0)
    return {'C201357': -n, 'C201356': n + 1, 'C201358': 1}[t['type']['code']]
for i, e in enumerate(encs, 1):
    t = timing_by.get(e.get('scheduledAtId'))
    TV.append(dict(STUDYID=studyid, DOMAIN='TV', VISITNUM=i, VISIT=e['name'], VISITDY=study_day(t) if t else '', ARMCD='',
                   TVSTRL=(f"{t['valueLabel']}" + (f" ({t['windowLabel']})" if t.get('windowLabel') else '')) if t else '',
                   TVENRL='', _usdm=f"Encounter {e['id']} / Timing {t['id'] if t else ''}"))
items = {i['id']: i for i in sv['eligibilityCriterionItems']}
for c in design['eligibilityCriteria']:
    txt = items[c['criterionItemId']]['text']
    TI.append(dict(STUDYID=studyid, DOMAIN='TI', IETESTCD=c['name'], IETEST=txt[:200], IECAT=sub('IECAT', c['category']), IESCAT='', TIRL='', TIVERS=sv['versionIdentifier'],
                   _usdm=f"EligibilityCriterion {c['id']}"))
    if len(txt) > 200: report['trial_design_blank_fields'].append({'domain': 'TI', 'field': 'IETEST', 'criterion': c['name'], 'reason': 'Text > 200 chars truncated; full text belongs in TI supplemental/protocol'})

# TS
tsparm = {t['term']: t for t in m_terms['TSPARMCD']}
def ts(parm, val, valcd='', ref='', ver='', src=''):
    seq = sum(1 for r in TS if r['TSPARMCD'] == parm) + 1
    TS.append(dict(STUDYID=studyid, DOMAIN='TS', TSSEQ=seq, TSPARMCD=parm, TSPARM=tsparm[parm]['decodedValue'] if parm in tsparm else '',
                   TSVAL=str(val)[:200], TSVALCD=valcd, TSVCDREF=ref, TSVCDVER=ver, _usdm=src))
CTV = term['terminology']['version']
def ct(cl, sv_):  # resolve submission value in a SDTM codelist
    t = m_term.get((cl, sv_)); return (t['nciCode'], 'CDISC CT', CTV) if t else ('', '', '')
title = next((t['text'] for t in sv['titles'] if t['type']['code'] == 'C207616'), '')
ts('TITLE', title, src='StudyVersion.titles[Official Study Title]')
def tsc(parm, cl, c, src):
    v = sub(cl, c); ts(parm, v, *ct(cl, v), src=src)
ph = design.get('studyPhase'); tsc('TPHASE', 'TPHASE', ph['standardCode'], 'StudyDesign.studyPhase')
tsc('STYPE', 'STYPE', design['studyType'], 'StudyDesign.studyType')
tsc('INTMODEL', 'INTMODEL', design['model'], 'StudyDesign.model')
bl = design.get('blindingSchema'); tsc('TBLIND', 'TBLIND', bl['standardCode'], 'StudyDesign.blindingSchema')
chars = [c['code'] for c in design['characteristics']]
ts('RANDOM', 'Y' if 'C46079' in chars else 'N', *ct('NY', 'Y' if 'C46079' in chars else 'N'), src='StudyDesign.characteristics (Randomized)')
ts('ADAPT', 'Y' if 'C98704' in chars else 'N', *ct('NY', 'Y' if 'C98704' in chars else 'N'), src='StudyDesign.characteristics (Adaptive)')
for st_ in design['subTypes']: tsc('TTYPE', 'TTYPE', st_, 'StudyDesign.subTypes')
for it in design['intentTypes']: tsc('TINDTP', 'TINDTP', it, 'StudyDesign.intentTypes')
pop = design['population']
ts('PLANSUB', int(pop['plannedEnrollmentNumber']['value']), src='StudyDesignPopulation.plannedEnrollmentNumber')
if pop.get('plannedAge'):
    ts('AGEMIN', f"P{int(pop['plannedAge']['minValue']['value'])}Y", src='StudyDesignPopulation.plannedAge.minValue')
    ts('AGEMAX', f"P{int(pop['plannedAge']['maxValue']['value'])}Y", src='StudyDesignPopulation.plannedAge.maxValue')
sexes = {c['code'] for c in pop['plannedSex']}
sexpop = 'BOTH' if sexes >= {'C16576', 'C20197'} else ('F' if 'C16576' in sexes else 'M')
ts('SEXPOP', sexpop, *ct('SEXPOP', sexpop), src='StudyDesignPopulation.plannedSex')
ts('HLTSUBJI', 'Y' if pop['includesHealthySubjects'] else 'N', *ct('NY', 'Y' if pop['includesHealthySubjects'] else 'N'), src='StudyDesignPopulation.includesHealthySubjects')
if pop.get('cohorts'): ts('NCOHORT', len(pop['cohorts']), src='StudyDesignPopulation.cohorts')
ts('NARMS', len(design['arms']), src='StudyDesign.arms')
ints = {i['id']: i for i in sv['studyInterventions']}
prods = {p['id']: p for p in sv['administrableProducts']}
for iid in design['studyInterventionIds']:
    si = ints[iid]
    if si['role']['code'] == 'C41161':
        ts('TRT', si['name'], src=f'StudyIntervention {iid} (Experimental Intervention)')
        tsc('INTTYPE', 'INTTYPE', si['type'], 'StudyIntervention.type')
        for a in si['administrations']:
            if a.get('dose'): ts('DOSE', a['dose']['value'] if a['dose']['value'] % 1 else int(a['dose']['value']), src=f"Administration {a['id']}")
        a0 = si['administrations'][0]
        if a0.get('dose') and a0['dose'].get('unit'): tsc('DOSU', 'UNIT', a0['dose']['unit']['standardCode'], 'Administration.dose.unit')
        if a0.get('frequency'): tsc('DOSFRQ', 'FREQ', a0['frequency']['standardCode'], 'Administration.frequency')
        if a0.get('route'): tsc('ROUTE', 'ROUTE', a0['route']['standardCode'], 'Administration.route')
        p = prods.get(a0.get('administrableProductId'))
        if p: tsc('DOSFRM', 'FRM', p['administrableDoseForm']['standardCode'], 'AdministrableProduct.administrableDoseForm')
    if si['role']['code'] == 'C753':
        ts('COMPTRT', si['label'] or si['name'], src=f'StudyIntervention {iid} (Placebo)')
if any(a['type']['code'] == 'C174268' for a in design['arms']): ts('TCNTRL', 'PLACEBO', *ct('TCNTRL', 'PLACEBO'), src='StudyArm.type = Placebo Comparator Arm')
for o in design['objectives']:
    parm = {'C85826': 'OBJPRIM', 'C85827': 'OBJSEC', 'C163559': 'OBJEXP'}[o['level']['code']]
    ts(parm, o['text'], src=f"Objective {o['id']}")
    for e in o['endpoints']:
        ep = {'C94496': 'OUTMSPRI', 'C139173': 'OUTMSSEC', 'C170559': 'OUTMSEXP'}[e['level']['code']]
        ts(ep, e['text'], src=f"Endpoint {e['id']}")
orgs = {o['id']: o for o in sv['organizations']}
for i in sv['studyIdentifiers']:
    o = orgs[i['scopeId']]
    if o['type']['code'] == 'C93453': ts('REGID', i['text'], src='StudyIdentifier scoped to registry organization')
    if o['type']['code'] == 'C54149': ts('SPONSOR', o['name'], src='Organization (Pharmaceutical Company)')
dur = tl.get('plannedDuration')
if dur and dur.get('quantity'): ts('LENGTH', f"P{int(dur['quantity']['value'])}D", src='ScheduleTimeline.plannedDuration')
for ta_ in design['therapeuticAreas']: ts('THERAREA', ta_['decode'], src='StudyDesign.therapeuticAreas')
for ind in design['indications']: ts('INDIC', ind['name'], src='StudyDesign.indications')
TS_EXPECTED = ['ADDON', 'AGEMAX', 'AGEMIN', 'LENGTH', 'PLANSUB', 'RANDOM', 'SEXPOP', 'STOPRULE', 'TBLIND', 'TCNTRL', 'TDIGRP', 'TINDTP', 'TITLE', 'TPHASE', 'TTYPE',
               'CURTRT', 'OBJPRIM', 'OBJSEC', 'SPONSOR', 'COMPTRT', 'INDIC', 'TRT', 'RANDQT', 'STRATFCT', 'REGID', 'OUTMSPRI', 'OUTMSSEC', 'PCLAS', 'FCNTRY',
               'ADAPT', 'DCUTDTC', 'DCUTDESC', 'INTMODEL', 'NARMS', 'STYPE', 'INTTYPE', 'SSTDTC', 'SENDTC', 'ACTSUB', 'HLTSUBJI', 'SDMDUR', 'CRMDUR',
               'EXTTIND', 'PDPSTIND', 'PDSTIND', 'PIPIND', 'RDIND', 'ONGOSIND', 'THERAREA', 'DOSE', 'DOSU', 'DOSFRQ', 'ROUTE', 'NCOHORT']
have = {r['TSPARMCD'] for r in TS}
for p in TS_EXPECTED:
    if p not in have: report['ts_parameters_not_derivable_from_usdm'].append({'TSPARMCD': p, 'TSPARM': tsparm.get(p, {}).get('decodedValue', '')})
trial_design = {'TA': TA, 'TE': TE, 'TV': TV, 'TI': TI, 'TS': TS}

# ------------------------------------------------------------------ Flow 2: SDTM study define
spec_ids = []
for _, _, s, _ in selected:
    if s and s not in spec_ids: spec_ids.append(s)
domains = []
for s in spec_ids:
    d = hdr['sdtm'][s]['domain']
    if d not in domains: domains.append(d)
TDM = ['TA', 'TE', 'TV', 'TI', 'TS']
all_domains = domains + [d for d in TDM if d not in domains]

def map_type(t):
    return {'decimal': 'float', 'float': 'float', 'integer': 'integer', 'text': 'text', 'string': 'text', 'datetime': 'datetime', 'date': 'date', 'boolean': 'text'}.get(t, t or None)
def where_of(spec):
    parts = [(r['sdtm_variable'], r['assigned_value']) for r in sdtm_items[spec]
             if r['comparator'] == 'EQ' and r['assigned_value'] and (r['mandatory_variable'] == 'Y' or not MANDATORY_ONLY)]
    return ' AND '.join(f'{v} EQ "{a}"' for v, a in parts)

# codelist demand: codelist id -> {'terms': ordered set, 'full': bool, 'by': [...]}
demand = collections.OrderedDict()
def want(cl, values, by, full=False, spec_full=False):
    """full=True: usage with no value constraint. spec_full=True: a selected specialization itself references the whole codelist."""
    d = demand.setdefault(cl, {'terms': [], 'full': False, 'unconstrained': [], 'by': []})
    d['full'] = d['full'] or spec_full
    for v in values:
        if v and v not in d['terms']: d['terms'].append(v)
    if full: d['unconstrained'].append(by)
    d['by'].append(by)

# USDM-derived constraints for exposure variables (assigned from protocol rather than COSMoS)
usdm_assigned = {}
for iid in design['studyInterventionIds']:
    for a in ints[iid]['administrations']:
        if a.get('dose') and a['dose'].get('unit'): usdm_assigned.setdefault('DOSU', set()).add(sub('UNIT', a['dose']['unit']['standardCode']))
        if a.get('route'): usdm_assigned.setdefault('ROUTE', set()).add(sub('ROUTE', a['route']['standardCode']))
        if a.get('frequency'): usdm_assigned.setdefault('DOSFRQ', set()).add(sub('FREQ', a['frequency']['standardCode']))
        p = prods.get(a.get('administrableProductId'))
        if p: usdm_assigned.setdefault('DOSFRM', set()).add(sub('FRM', p['administrableDoseForm']['standardCode']))

datasets, variables, value_level = [], [], []
hdr_cl_ids = {r['codelist_submission_value'] for rows in sdtm_items.values() for r in rows if r['codelist_submission_value']}
for dom in all_domains:
    if dom not in m_ds:
        report['domain_not_in_master_standard'].append(dom); continue
    md = m_ds[dom]
    ds = copy.deepcopy(md); ds['internalId'] = None
    ds['customAttribute'] = prov(sourceSpecId=STD_ID, sourceInternalId=md['internalId'],
                                 specializations=[s for s in spec_ids if hdr['sdtm'][s]['domain'] == dom])
    datasets.append(ds)
    dom_specs = [s for s in spec_ids if hdr['sdtm'][s]['domain'] == dom]
    rows_by_var = collections.defaultdict(list)
    for s in dom_specs:
        for r in sdtm_items[s]:
            if r['mandatory_variable'] == 'Y' or not MANDATORY_ONLY: rows_by_var[r['sdtm_variable']].append((s, r))
    shell = [v for v, mv in m_var[dom].items() if mv['core'] in ('Required', 'Expected')]
    in_scope = list(dict.fromkeys(shell + list(rows_by_var)))
    for vn in in_scope:
        mv = m_var[dom].get(vn)
        if not mv:
            report['specialization_variable_not_in_master'].append({'domain': dom, 'variable': vn, 'specializations': sorted({s for s, _ in rows_by_var[vn]}),
                                                                     'nsv': any(r['nsv_flag'] == 'Y' for _, r in rows_by_var[vn])})
            continue
        v = copy.deepcopy(mv); v['internalId'] = None; v['datasetId'] = None
        rs = rows_by_var.get(vn, [])
        v['customAttribute'] = prov(sourceSpecId=STD_ID, sourceInternalId=mv['internalId'], inclusion='domain shell (' + mv['core'] + ')' if vn in shell else 'specialization',
                                    specializations=sorted({s for s, _ in rs}))
        # codelist cut ---------------------------------------------------------
        groups = collections.OrderedDict()  # codelist -> [values], unconstrained flag (a variable may use different codelists per specialization)
        for _, r in rs:
            if not r['codelist_submission_value']: continue
            g = groups.setdefault(r['codelist_submission_value'], [[], False])
            if r['assigned_value']: g[0].append(r['assigned_value'])
            elif r['value_list']: g[0].extend(r['value_list'].split(';'))
            else: g[1] = True
        if not groups and mv['codelist']:
            groups[mv['codelist']] = [[], True]
        sfx = vn[len(dom):] if vn.startswith(dom) else vn
        # a codelist that only some specializations attach (e.g. NORMABNM for EGINTP on EGORRES) and that the standard does not
        # assign to the variable belongs at value level only - when VLM is on and every such row is a VLM target with a where clause
        vlm_only = bool(VLM_ON and groups and mv['codelist'] not in groups
                        and (len(groups) > 1 or any(not r['codelist_submission_value'] for _, r in rs))
                        and all(r['vlm_target'] == 'Y' and where_of(s_) for s_, r in rs if r['codelist_submission_value']))
        for cl, (vals, unconstrained) in ([] if vlm_only else groups.items()):
            if dom in ('EC', 'EX') and sfx in usdm_assigned:   # protocol-assigned from USDM administrations
                vals, unconstrained = sorted(usdm_assigned[sfx]), False
            if dom in TDM:  # trial design codelists cut to values actually generated from USDM
                vals = sorted({str(row[vn]) for row in trial_design[dom] if row.get(vn) not in (None, '')}); unconstrained = not vals
            if cl in DICTIONARIES or (mv['codelist'] == cl and cl not in m_cl and cl[:1].isupper() and cl not in hdr_cl_ids):
                report['external_dictionaries'].append({'variable': f'{dom}.{vn}', 'dictionary': cl}); continue
            want(cl, vals, f'{dom}.{vn}', full=unconstrained, spec_full=unconstrained and bool(rs) and dom not in TDM)
        v['codelist'] = None if vlm_only else (mv['codelist'] if mv['codelist'] in groups else (next(iter(groups)) if len(groups) == 1 else None)) if groups else None
        if vlm_only: v['customAttribute']['note'] = f'codelist {", ".join(groups)} applies to specific tests only - carried at value level'
        elif len(groups) > 1: v['customAttribute']['note'] = f'codelists differ by specialization ({", ".join(groups)}); carried at value level'
        # VLM -------------------------------------------------------------------
        if VLM_ON:
            for s, r in rs:
                if r['vlm_target'] != 'Y': continue
                wc = where_of(s)
                if not wc: continue
                vlm_cl = r['codelist_submission_value'] or None   # unconstrained -> full parent codelist
                if vlm_cl and not (r['assigned_value'] or r['value_list']): want(vlm_cl, [], f'{dom}.{vn} [{s}]', full=True, spec_full=True)
                if r['codelist_submission_value'] and (r['assigned_value'] or r['value_list']):
                    vlm_cl = f"{dom}_{s}_{r['codelist_submission_value']}"
                    want(vlm_cl, [r['assigned_value']] if r['assigned_value'] else r['value_list'].split(';'), f'{dom}.{vn} [{s}]')
                    demand[vlm_cl]['parent'] = r['codelist_submission_value']
                value_level.append(dict(internalId=None, order=str(len(value_level) + 1), datasetId=None, dataset=dom, variable=vn, whereClause=wc,
                    label=hdr['sdtm'][s]['shortName'], dataType=map_type(r['data_type']) or mv['dataType'], length=r['length'].split('.')[0] or mv['length'],
                    significantDigits=r['significant_digits'].split('.')[0] or None, mandatory='Yes' if r['mandatory_value'] == 'Y' else 'No',
                    assignedValue=r['assigned_value'] or None, codeListId=None, codelist=vlm_cl, decodedVariable=None, codelistExpected=None,
                    expectedCodelistId=None, expectedCodelistName=None, origin=r['origin_type'] or None, source=r['origin_source'] or None, predecessor=None,
                    methodId=None, method=None, commentId=None, comment=None, rawVariables=None, developerNotes=None,
                    customAttribute=prov(bcId=r['bc_id'], specialization=s, decId=r['dec_id'] or None)))
        variables.append(v)

# resolve codelist demand against master terminology (3 rules) -----------------------
def shell_role(usage):
    dom, var = usage.split(' ')[0].split('.')
    return (m_var.get(dom, {}).get(var) or {}).get('role')
codelists, terms = [], []
for cl, d in demand.items():
    parent = d.get('parent', cl)
    mc = m_cl.get(parent)
    if not mc:
        report['codelist_not_in_terminology'].append({'codelist': cl, 'usedBy': d['by']}); continue
    if d['terms'] and not d['full']:
        rule = 'assigned/value list'
        if d['unconstrained'] and cl == parent:
            report['codelist_unconstrained_usage_limited_to_resolved_terms'].append({'codelist': cl, 'terms': len(d['terms']), 'masterTerms': len(m_terms[cl]), 'unconstrainedVariables': d['unconstrained']})
        chosen = []
        for val in d['terms']:
            t = m_term.get((parent, val))
            if t: chosen.append((t, False))
            elif mc['extensible'] == 'Yes':
                chosen.append(({'internalId': None, 'codelist': parent, 'term': val, 'decodedValue': val, 'nciCode': None, 'synonyms': None, 'description': None, 'nciPreferredTerm': None}, True))
                report['sponsor_extended_terms'].append({'codelist': cl, 'term': val})
            else:
                report['term_not_in_nonextensible_codelist'].append({'codelist': cl, 'term': val})
    elif d['full'] or mc['extensible'] == 'No' or not all(shell_role(u) == 'Record Qualifier' for u in d['unconstrained']):
        # rule 3: full codelist when
        #  - a selected specialization itself references the codelist with no value constraint, or
        #  - the codelist is closed (non-extensible) so the full list is the only valid subset (e.g. Y, ACN), or
        #  - the shell variable is not a Record Qualifier: Variable/Result Qualifiers interpret a result whose
        #    permissible values are standard-defined (e.g. LBNRIND -> NRIND), not chosen per study/lab.
        #  Extensible codelists used only by Record Qualifiers (how/why context: --METHOD, ARMNRS) are deferred.
        rule = 'full codelist'; chosen = [(t, False) for t in m_terms[parent]]
        report['full_codelists_included'].append({'codelist': cl, 'terms': len(chosen), 'usedBy': d['unconstrained']})
    else:
        # only domain-shell (Required/Expected) variables use it and nothing constrains it -> keep the reference, no terms
        rule = 'deferred - to be populated (lab/sponsor-specific)'; chosen = []
        report['codelists_deferred_to_be_populated'].append({'codelist': cl, 'masterTerms': len(m_terms[parent]), 'usedBy': d['unconstrained'],
                                                             'reason': 'Extensible codelist referenced only by domain-shell Record Qualifier variables not covered by any selected specialization'})
    c = copy.deepcopy(mc); c['internalId'] = None; c['id'] = cl
    if cl != parent: c['name'] = f"{mc['name']} ({cl})"
    c['customAttribute'] = prov(sourceSpecId=CT_ID, sourceInternalId=mc['internalId'], parentCodelist=parent, subsetRule=rule, usedBy=d['by'])
    codelists.append(c)
    for i, (t, extended) in enumerate(chosen, 1):
        nt = copy.deepcopy(t); nt['internalId'] = None; nt['order'] = str(i); nt['codelistId'] = None; nt['codelist'] = cl
        nt['customAttribute'] = prov(sourceSpecId=CT_ID, sourceInternalId=t['internalId'], extended=extended)
        terms.append(nt)

# ------------------------------------------------------------------ ordering
# Datasets: SDTMIG class order, then alphabetical. Variables: the master standard's order; variables the P21 export
# leaves without an order are placed by location - next to the same variable's neighbour in other domains of the
# same class (e.g. LBORRES after LBBODSYS because VSORRES follows VSBODSYS) - with fixed anchors for STUDYID/DOMAIN/USUBJID.
CLASS_ORDER = ['TRIAL DESIGN', 'SPECIAL PURPOSE', 'INTERVENTIONS', 'EVENTS', 'FINDINGS', 'FINDINGS ABOUT', 'RELATIONSHIP', 'STUDY REFERENCE']
ANCHORS = {'STUDYID': 1.0, 'DOMAIN': 2.0, 'USUBJID': 3.0}
_cls = {d['dataset']: d['class'] for d in std['datasets']}
def _gen(dom, n): return '--' + n[len(dom):] if n.startswith(dom) and len(n) > len(dom) else n
_known_cache = {}
def _known(dom):
    if dom not in _known_cache:
        k = {_gen(dom, v['variable']): float(v['order']) for v in m_var[dom].values() if v['order']}
        for a_, o_ in ANCHORS.items():
            if a_ in m_var[dom] and a_ not in k: k[a_] = o_
        _known_cache[dom] = k
    return _known_cache[dom]
def effective_order(dom, vn):
    k = _known(dom); sfx = _gen(dom, vn)
    if sfx in k: return k[sfx], 'standard' if (m_var[dom].get(vn) or {}).get('order') else 'anchor'
    c = []
    for d2 in m_var:
        if d2 == dom or _cls.get(d2) != _cls.get(dom): continue
        lst = sorted(_known(d2).items(), key=lambda x: x[1]); idx = next((i for i, x in enumerate(lst) if x[0] == sfx), None)
        if idx is None: continue
        got = next((k[lst[j][0]] + 0.5 for j in range(idx - 1, -1, -1) if lst[j][0] in k), None)
        if got is None: got = next((k[lst[j][0]] - 0.5 for j in range(idx + 1, len(lst)) if lst[j][0] in k), None)
        if got is not None: c.append(got)
    if c: c.sort(); return c[len(c) // 2], 'inferred from location in same-class domains'
    return (9000.0 if 'Timing' in ((m_var[dom].get(vn) or {}).get('role') or '') else 5000.0), 'appended'
datasets.sort(key=lambda d: (CLASS_ORDER.index(d['class']) if d['class'] in CLASS_ORDER else 99, d['dataset']))
ds_rank = {d['dataset']: i for i, d in enumerate(datasets)}
for v in variables:
    o, how = effective_order(v['dataset'], v['variable']); v['_o'] = o
    v['customAttribute'].update(sourceOrder=v['order'], orderSource=how)
variables.sort(key=lambda v: (ds_rank.get(v['dataset'], 99), v['_o']))
var_rank, n_in = {}, collections.Counter()
for v in variables:
    n_in[v['dataset']] += 1; v['order'] = str(n_in[v['dataset']]); var_rank[(v['dataset'], v['variable'])] = n_in[v['dataset']]; del v['_o']
value_level = [x for _, x in sorted(enumerate(value_level), key=lambda t: (ds_rank.get(t[1]['dataset'], 99), var_rank.get((t[1]['dataset'], t[1]['variable']), 999), t[0]))]
for i, x in enumerate(value_level, 1): x['order'] = str(i)
codelists.sort(key=lambda c: c['id'])
cl_rank = {c['id']: i for i, c in enumerate(codelists)}
_mt_rank = {(t['codelist'], t['term']): i for i, t in enumerate(term['terms'])}
terms = [t for _, t in sorted(enumerate(terms), key=lambda x: (cl_rank.get(x[1]['codelist'], 9999),
                                                             _mt_rank.get((codelists[cl_rank[x[1]['codelist']]]['customAttribute']['parentCodelist'], x[1]['term']), 10**9), x[0]))]
_c = collections.Counter()
for t in terms: _c[t['codelist']] += 1; t['order'] = str(_c[t['codelist']])

define = {
    'message': 'generated', 'datetime': NOW,
    'standard': {'specId': None, 'name': f'{studyid} SDTM', 'version': sv['versionIdentifier'], 'description': f'Study SDTM define for {studyid} generated from USDM',
                 'type': 'SDTM', 'publisher': 'Example Biopharma Ltd', 'baseName': std['standard']['name'], 'baseVersion': std['standard']['version'],
                 'status': 'Draft', 'customAttribute': prov(sourceStandardSpecId=STD_ID, sourceTerminologySpecId=CT_ID, terminologyVersion=term['terminology']['version'],
                                                            options={'mandatoryVariablesOnly': MANDATORY_ONLY, 'valueLevelMetadata': VLM_ON})},
    'datasets': datasets, 'variables': variables, 'value_level': value_level, 'methods': [], 'comments': [], 'documents': [],
    'codelists': codelists, 'terms': terms,
}
json.dump(define, open(f'{OUT}/p21_sdtm_study_define.json', 'w'), indent=1)
json.dump(trial_design, open(f'{OUT}/p21_trial_design_domains.json', 'w'), indent=1)

# ------------------------------------------------------------------ Flow 1: CRF form spec
REPEATING = {'AE', 'CM', 'MH'}
events = [dict(Order=i, ID=e['name'], Name=e['label'], Type='Scheduled', Mandatory='', Repeating='No', DeveloperNotes='', _usdmId=e['id']) for i, e in enumerate(encs, 1)]
forms, questions, soa, crf_cls, crf_terms = [], [], [], {}, []
act_forms = {}
for act in design['activities']:
    sel = [(bc, s, c) for a, bc, s, c in selected if a['id'] == act['id'] and c]
    if not sel: continue
    doms = sorted({hdr['crf'][c]['domain'] for _, _, c in sel})
    fid = act['name']; act_forms[act['id']] = fid
    forms.append(dict(Order=len(forms) + 1, ID=fid, Name=act.get('label') or act['name'], Description='', Class='', Repeating='Yes' if set(doms) & REPEATING else 'No',
                      Condition='', SourceDatasetName=','.join(doms), SDTMTargetDomains=','.join(doms), DeveloperNotes='', _usdmActivityId=act['id']))
    order = 0
    for bc, s, c in sel:
        crf_sdtm = hdr['crf'][c].get('sdtmDatasetSpecializationId')
        cross = bool(s and crf_sdtm and crf_sdtm != s)   # user picked a same-BC CRF specialization for a different SDTM specialization
        spec_rows = {r['sdtm_variable']: r for r in sdtm_items.get(s, [])} if cross else {}
        native_vars = {r['sdtm_variable'] for r in sdtm_items.get(crf_sdtm, [])} if cross else set()
        overrides, review = [], []
        for r in crf_items[c]:
            r = dict(r); order += 1; note = ''
            base = re.sub(r'_(DENORMALIZED|NORMALIZED)$', '', c)
            if cross:
                # reconcile the CRF item with the SDTM specialization the define is built from (SDTM side is authoritative)
                tgt = (r['sdtm_target_variables'].split(';') or [''])[0]
                sr = spec_rows.get(tgt)
                if sr:
                    if sr['assigned_value'] and r['prepopulated_term'] and r['prepopulated_term'] != sr['assigned_value']:
                        overrides.append({'item': r['crf_item'], 'field': 'prepopulated value', 'from': r['prepopulated_term'], 'to': sr['assigned_value']})
                        r['sdtm_annotation'] = r['sdtm_annotation'].replace(r['prepopulated_term'], sr['assigned_value'])
                        r['prepopulated_term'] = sr['assigned_value']; r['codelist_submission_value'] = sr['codelist_submission_value'] or r['codelist_submission_value']
                    if sr['value_list'] and set(sr['value_list'].split(';')) != set(filter(None, r['value_list'].split(';'))):
                        overrides.append({'item': r['crf_item'], 'field': 'value list', 'from': r['value_list'] or '(none)', 'to': sr['value_list']})
                        r['value_list'] = sr['value_list']; r['value_list_display'] = ''
                        r['codelist_submission_value'] = sr['codelist_submission_value'] or r['codelist_submission_value']
                        r['selection_type'] = r['selection_type'] or 'Single'
                    st = map_type(sr['data_type']) if sr['data_type'] else None
                    if st and r['data_type'] and st != map_type(r['data_type']) and not (st == 'float' and r['data_type'] in ('decimal', 'float')):
                        overrides.append({'item': r['crf_item'], 'field': 'data type', 'from': r['data_type'], 'to': st}); r['data_type'] = st
                    base = s  # reconciled codelists are named after the SDTM specialization they now follow
                elif tgt in native_vars:   # part of the CRF's own SDTM specialization but not of the selected one -> semantic difference
                    review.append(r['crf_item'])
                    note = f'Review: {tgt} is not part of SDTM specialization {s} (item comes from CRF specialization {c})'
            cl = None
            if r['value_list'] or r['prepopulated_term']:
                cl = f"{r['domain']}_{base}_{r['codelist_submission_value'] or r['variable_name']}"
                if cl not in crf_cls:
                    crf_cls[cl] = dict(ID=cl, Name=f"{r['prompt'] or r['question_text'] or r['variable_name']} ({base})", DataType='text',
                                       Terminology=r['codelist_submission_value'] or '', _source=c)
                    vals = r['value_list'].split(';') if r['value_list'] else [r['prepopulated_term']]
                    disp = r['value_list_display'].split(';') if r['value_list_display'] else [''] * len(vals)
                    for j, (val, dv) in enumerate(zip(vals, disp), 1):
                        t = m_term.get((r['codelist_submission_value'], val))
                        crf_terms.append(dict(Codelist=cl, Order=j, Term=val, DecodedValue=dv or (t['decodedValue'] if t else val), NCICode=t['nciCode'] if t else '',
                                              _p21TermInternalId=t['internalId'] if t else None))
            questions.append(dict(Form=fid, Section=r['crf_group_id'], Order=order, ID=r['crf_item'], SourceVariableName=r['variable_name'],
                                  QuestionText=r['question_text'], Prompt=r['prompt'], Description=r['dec_id'], DataType=r['data_type'], Length=r['length'],
                                  Digits=r['significant_digits'], Mandatory='Yes' if r['mandatory_variable'] == 'Y' else 'No', Codelist=cl or '',
                                  DefaultValue=r['prepopulated_term'], Hidden='Yes' if r['display_hidden'] == 'Y' else 'No', ControlType=r['selection_type'],
                                  SDTMTarget=';'.join(f"{r['domain']}.{x}" for x in r['sdtm_target_variables'].split(';') if x),
                                  MappingInstructions=r['sdtm_annotation'], Core='', CompletionInstructions='', ImplementationNotes='', DeveloperNotes=note,
                                  _bc=bc['name'], _crfSpecialization=c, _sdtmSpecialization=s, _crossMatched=cross))
        if cross:
            report['crf_specialization_user_selected_cross_match'].append({'activity': act['name'], 'bc': bc['name'], 'bcCode': bc['code']['standardCode']['code'],
                'sdtmSpecialization': s, 'crfSpecialization': c, 'crfNativeSdtmSpecialization': crf_sdtm, 'overrides': overrides, 'itemsToReview': review})
for sai in tl['instances']:
    if sai.get('instanceType') != 'ScheduledActivityInstance': continue
    enc = next(e for e in encs if e['id'] == sai['encounterId'])
    o = 0
    for aid in sai['activityIds']:
        if aid in act_forms:
            o += 1; soa.append(dict(Order=o, Event=enc['name'], Form=act_forms[aid], Mandatory='Yes'))
crf = {'events': events, 'forms': forms, 'scheduleOfActivities': soa, 'questions': questions, 'codelists': list(crf_cls.values()), 'terms': crf_terms,
       'meta': prov(standard='CDASHIG (latest, hardcoded per pitch)', note='Direct specialization route (Flow 1); one form per USDM Activity')}
json.dump(crf, open(f'{OUT}/p21_crf_form_spec.json', 'w'), indent=1)

# ------------------------------------------------------------------ Study object + data packages (Step 1 / 1b)
off = next((t['text'] for t in sv['titles'] if t['type']['code'] == 'C207616'), study['name'])
study_obj = {
    'studyObject': {'ProtocolTitle': off, 'ClinicalTrialsGovId': next((i['text'] for i in sv['studyIdentifiers'] if orgs[i['scopeId']]['name'] == 'ClinicalTrials.gov'), ''),
                    'EudraCTNumber': '', 'ProtocolId': studyid, 'Phase': sub('TPHASE', ph['standardCode']) if ph else '',
                    'TrialType': [x['decode'] for x in design['intentTypes'] + design['subTypes']],
                    'Indication': [c['decode'] for i in design['indications'] for c in i.get('codes', [])],
                    'TherapeuticArea': [x['decode'] for x in design['therapeuticAreas']] or [x['decode'] for x in sv['businessTherapeuticAreas']],
                    'Project': '<user-selected existing P21 project>', 'usdmVersion': usdm['usdmVersion'], 'customAttribute': prov()},
    'dataPackages': [
        {'Name': f'{studyid} Form Spec', 'Project': '<same>', 'Study': studyid, 'Standard': 'CDASHIG (latest)', 'ControlledTerminology': 'inherited from CDASH', 'Engine': None},
        {'Name': 'SDTM', 'Project': '<same>', 'Study': studyid, 'Standard': f"{std['standard']['name']} {std['standard']['version']} (specId {STD_ID})",
         'ControlledTerminology': f"{term['terminology']['name']} {term['terminology']['version']} (specId {CT_ID})", 'Engine': 'default'}]}
if not design['therapeuticAreas']: report['usdm_blank_fields'].append({'field': 'StudyDesign.therapeuticAreas', 'fallback': 'StudyVersion.businessTherapeuticAreas'})
if not design['indications']: report['usdm_blank_fields'].append({'field': 'StudyDesign.indications', 'note': 'Healthy-volunteer study'})
if not design['intentTypes']: report['usdm_blank_fields'].append({'field': 'StudyDesign.intentTypes', 'note': 'TINDTP not derivable'})
json.dump(study_obj, open(f'{OUT}/p21_study_object.json', 'w'), indent=1)

# ------------------------------------------------------------------ P21-linked USDM (persist the resolution as hidden extensions)
P21 = 'https://www.certara.com/usdm/extensions/p21'
cnt = [0]
def xa(url, **val):
    cnt[0] += 1
    d = {'id': f'P21ExtensionAttribute_{cnt[0]}', 'url': url, 'instanceType': 'ExtensionAttribute', 'extensionAttributes': []}
    d.update(val); return d
linked = copy.deepcopy(usdm); lsv = linked['study']['versions'][0]
lsv['extensionAttributes'] = [e for e in lsv.get('extensionAttributes', []) if not e['url'].startswith(P21)] + [xa(f'{P21}/study-link', extensionAttributes=[
    xa(f'{P21}/sdtmStandard', valueString=f"{STD_ID}|{std['standard']['name']} {std['standard']['version']}"),
    xa(f'{P21}/terminology', valueString=f"{CT_ID}|{term['terminology']['name']} {term['terminology']['version']}"),
    xa(f'{P21}/cosmosPackages', valueString=';'.join(sorted({str(hdr['sdtm'][s]['packageDate']) for s in spec_ids}))),
    xa(f'{P21}/generatedAt', valueString=NOW)])]
for bc in lsv['biomedicalConcepts']:
    s = ext_val(bc, SDTM_URL)
    if not s or s not in sdtm_items: continue
    dom = hdr['sdtm'][s]['domain']; links = [xa(f'{P21}/dataset', valueString=f"{m_ds[dom]['internalId']}|{dom}")]
    topic = next((r for r in sdtm_items[s] if r['role'] == 'Topic'), None)
    if topic and topic['sdtm_variable'] in m_var[dom]:
        links.append(xa(f'{P21}/topicVariable', valueString=f"{m_var[dom][topic['sdtm_variable']]['internalId']}|{dom}.{topic['sdtm_variable']}"))
        t = m_term.get((topic['codelist_submission_value'], topic['assigned_value']))
        if t: links.append(xa(f'{P21}/topicTerm', valueString=f"{t['internalId']}|{t['codelist']}|{t['term']}|{t['nciCode']}"))
    wc = where_of(s)
    if wc: links.append(xa(f'{P21}/whereClause', valueString=wc))
    bc['extensionAttributes'] = [e for e in bc['extensionAttributes'] if not e['url'].startswith(P21)] + [xa(f'{P21}/sdtm-link', extensionAttributes=links)]
from usdm_model.wrapper import Wrapper
Wrapper.model_validate(linked)
json.dump(linked, open(f'{OUT}/{os.path.basename(USDM).replace(".json", "")}_P21-linked.json', 'w'), indent=2)

# ------------------------------------------------------------------ coverage report
summary = dict(bcSelected=len(selected), sdtmSpecializations=len(spec_ids), domains=domains, defineDatasets=len(datasets), defineVariables=len(variables),
               vlmRows=len(value_level), codelists=len(codelists), terms=len(terms), crfForms=len(forms), crfQuestions=len(questions), crfCodelists=len(crf_cls),
               soaRows=len(soa), TA=len(TA), TE=len(TE), TV=len(TV), TI=len(TI), TS=len(TS),
               masterTerminologyTerms=len(term['terms']), masterVariables=len(std['variables']),
               bcWithoutCrfSpecialization=len(report['bc_without_crf_specialization']), crfCrossMatched=len(report['crf_specialization_user_selected_cross_match']), surrogatesExcluded=len(report['bc_surrogates_excluded']))
json.dump({'summary': summary, **report}, open(f'{OUT}/coverage_report.json', 'w'), indent=1)
print(json.dumps(summary, indent=1))
