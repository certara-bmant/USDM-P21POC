"""Build a USDM v4.0 JSON for a fictional Phase 1 SAD study (CTX101-001) with every assessment
expressed as a Biomedical Concept, each BC instance carrying the SoA-Workbench-style
specialization extensions:
    http://www.cdisc.org/usdm/extensions/specializations/sdtm -> /mdr/specializations/sdtm/datasetspecializations/<ID>
    http://www.cdisc.org/usdm/extensions/specializations/crf  -> /mdr/specializations/crf/specializations/<ID>
Assessments with no COSMoS specialization are modelled as BiomedicalConceptSurrogates.

usage: python 01_build_usdm.py <reference_dir> <term34.json> <out.json>
"""
import json, csv, sys, collections
from usdm_model.wrapper import Wrapper

REF, TERM, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
hdr = json.load(open(f'{REF}/cosmos_headers.json'))
sdtm_rows = collections.defaultdict(list)
for r in csv.DictReader(open(f'{REF}/cosmos_sdtm_item.csv')):
    sdtm_rows[r['vlm_group_id']].append(r)
term = json.load(open(TERM))
cl_by_sv = {c['id']: c for c in term['codelists']}
term_by = {(t['codelist'], t['term']): t for t in term['terms']}

DDF_CT_VER = '2025-09-26'
# preferred terms for DDF/USDM codelists (CDISC rules DDF00140 etc. check decode == NCI preferred term)
import yaml, os, usdm4
_lc = yaml.safe_load(open(os.path.join(os.path.dirname(usdm4.__file__), 'ct/cdisc/library_cache/library_cache_usdm.yaml')))
PREF = {}
for _cl in (_lc.values() if isinstance(_lc, dict) else _lc):
    for _t in (_cl.get('terms', []) if isinstance(_cl, dict) else []):
        PREF.setdefault(_t['conceptId'], _t.get('preferredTerm') or _t.get('submissionValue'))
counters = collections.Counter()
def nid(cls):
    counters[cls] += 1
    return f'{cls}_{counters[cls]}'
def code(c, decode, system='http://www.cdisc.org', ver=DDF_CT_VER, pt=True):
    if pt and system == 'http://www.cdisc.org' and c in PREF: decode = PREF[c]
    return {'id': nid('Code'), 'code': c, 'codeSystem': system, 'codeSystemVersion': ver, 'decode': decode, 'instanceType': 'Code', 'extensionAttributes': []}
def alias(c, decode, **kw):
    return {'id': nid('AliasCode'), 'standardCode': code(c, decode, **kw), 'standardCodeAliases': [], 'instanceType': 'AliasCode', 'extensionAttributes': []}
def obj(cls, **kw):
    d = {'id': nid(cls)}; d.update(kw); d['instanceType'] = cls; d.setdefault('extensionAttributes', []); return d
def ext(url, value):
    return {'id': nid('ExtensionAttribute'), 'url': url, 'valueString': value, 'instanceType': 'ExtensionAttribute', 'extensionAttributes': []}
def qty(v, unit=None):
    return obj('Quantity', value=v, unit=unit)

# ------------------------------------------------------------------ study design constants
ENCOUNTERS = [  # key, name, label, day, timing type, offset, window lower/upper, window label, epoch
    ('SCR', 'SCREENING', 'Screening', -28, 'Before', 'P28D', 'P0D', 'P26D', 'Day -28 to Day -2', 'SCREENING'),
    ('DM1', 'DAY -1', 'Day -1 (Admission)', -1, 'Before', 'P1D', None, None, None, 'TREATMENT'),
    ('D1', 'DAY 1', 'Day 1 (Dosing)', 1, 'Fixed Reference', 'P0D', None, None, None, 'TREATMENT'),
    ('D2', 'DAY 2', 'Day 2', 2, 'After', 'P1D', None, None, None, 'TREATMENT'),
    ('D3', 'DAY 3', 'Day 3', 3, 'After', 'P2D', None, None, None, 'TREATMENT'),
    ('D4', 'DAY 4', 'Day 4 (Discharge)', 4, 'After', 'P3D', None, None, None, 'TREATMENT'),
    ('D7', 'DAY 7', 'Day 7 (Follow-up)', 7, 'After', 'P6D', 'P1D', 'P1D', '+/- 1 day', 'FOLLOW-UP'),
    ('EOS', 'DAY 14 / EOS', 'Day 14 End of Study / Early Termination', 14, 'After', 'P13D', 'P2D', 'P2D', '+/- 2 days', 'FOLLOW-UP'),
]
ALL = [e[0] for e in ENCOUNTERS]
# activity name, label, category, [(sdtm spec, crf spec)], [surrogates], encounters
HEM = ['HGBBLD', 'HCTBLD', 'RBCBLD', 'WBCBLD', 'PLATBLD', 'NEUTBLD', 'LYMPHBLD', 'MONOBLD', 'EOSBLD', 'BASOBLD', 'MCV', 'MCH', 'MCHC']
COAG = ['PTPPP', 'INRPPP', 'APTTPPP']
CHEM = ['SODIUMSERPL', 'KSERPL', 'CLSERPL', 'CO2SERPL', 'UREANSERPL', 'CREATSERPL', 'GLUCSERPL', 'CASERPL', 'PHOSSERPL', 'PROTSERPL', 'ALBSERPL',
        'ALTSERPL', 'ASTSERPL', 'ALPSERPL', 'GGTSERPL', 'BILISERPL', 'BILDIRSERPL', 'LDHSERPL', 'CKSERPL', 'URATESERPL', 'CHOLSERPL', 'TRIGSERPL']
UA = ['PHURIN', 'SPGRAVURIN', 'COLORURIN', 'PROTURINPRES', 'GLUCURINPRES', 'KETONESURINPRES', 'BILIURINPRES', 'UROBILURINPRES', 'OCCBLDURINPRES', 'NITRITEURINPRES']
VS = ['SYSBP', 'DIABP', 'PULSE', 'RESP', 'TEMP']
EG = ['EGHRMN', 'PRAG', 'QRSAG', 'QTAG', 'QTCFAG', 'RRAG', 'EGINTP']
CRF_PREF = {'AE': 'AE_NORMALIZED', 'CMFREE': 'CMFREE_NORMALIZED', 'MEDHISTFREE': 'MEDHISTFREE_NORMALIZED', 'CONSENT': 'CONSENT',
            'INCL01': 'INCL01', 'EXCL01': 'EXCL01', 'SEX': 'SEX', 'BRTHDTC': 'BRTHDTC', 'ALCOHOLHX': 'ALCOHOLHX', 'CIGARETTEHX': 'CIGARETTEHX'}
# User-confirmed CRF specialization choices where COSMoS has no CRF specialization for the exact SDTM
# specialization but does for the same BC (different specimen / result scale). In the Workbench these are
# picked by the user from the same-BC candidates; the choice is persisted only via the CRF extension.
# Deliberately NOT selected: UROBILURINPRES (only candidate NITRITEURIN - COSMoS BC mis-tag) and
# WBCURINPRES (only candidate WBCBLD - wrong specimen).
USER_CRF_SELECTION = {
    'SODIUMSERPL': 'SODIUMBLD_DENORMALIZED', 'KSERPL': 'KBLD_DENORMALIZED', 'CLSERPL': 'CLBLD_DENORMALIZED',
    'CO2SERPL': 'CO2BLD_DENORMALIZED', 'GLUCSERPL': 'GLUCBLD_DENORMALIZED', 'CASERPL': 'CABLD_DENORMALIZED',
    'PROTURINPRES': 'PROTURIN_DENORMALIZED', 'GLUCURINPRES': 'GLUCURIN_DENORMALIZED',
    'KETONESURINPRES': 'KETONESURIN_DENORMALIZED', 'NITRITEURINPRES': 'NITRITEURIN_DENORMALIZED',
}
def crf_for(spec):
    if spec in CRF_PREF: return CRF_PREF[spec]
    if spec in USER_CRF_SELECTION: return USER_CRF_SELECTION[spec]
    cands = [k for k, v in hdr['crf'].items() if v.get('sdtmDatasetSpecializationId') == spec]
    for suffix in ('_DENORMALIZED', ''):
        for c in cands:
            if c == spec + suffix: return c
    return cands[0] if cands else None

ACTIVITIES = [
    ('INFORMED_CONSENT', 'Informed Consent', 'Disposition', ['CONSENT'], [], ['SCR']),
    ('ELIGIBILITY', 'Inclusion / Exclusion Criteria', 'Eligibility', ['INCL01', 'EXCL01'], [], ['SCR', 'DM1']),
    ('DEMOGRAPHICS', 'Demographics', 'Demographics', ['BRTHDTC', 'AGE', 'SEX', 'RACE', 'ETHNIC'], [], ['SCR']),
    ('MEDICAL_HISTORY', 'Medical History', 'Medical History', ['MEDHISTFREE'], [], ['SCR']),
    ('SUBSTANCE_USE', 'Alcohol and Tobacco Use History', 'Substance Use', ['ALCOHOLHX', 'CIGARETTEHX'], [], ['SCR']),
    ('HEIGHT_BMI', 'Height and BMI', 'Vital Signs', ['HEIGHT', 'BMI'], [], ['SCR']),
    ('BODY_WEIGHT', 'Body Weight', 'Vital Signs', ['WEIGHT'], [], ['SCR', 'DM1', 'EOS']),
    ('PHYSICAL_EXAM', 'Physical Examination', 'Physical Examination', [], ['PHYSICAL_EXAM'], ['SCR', 'DM1', 'D4', 'EOS']),
    ('VITAL_SIGNS', 'Vital Signs', 'Vital Signs', VS, [], ALL),
    ('ECG_12LEAD', '12-Lead ECG', 'ECG', EG, [], ['SCR', 'DM1', 'D1', 'D2', 'D4', 'EOS']),
    ('HEMATOLOGY', 'Hematology', 'Hematology', HEM, [], ['SCR', 'DM1', 'D2', 'D4', 'EOS']),
    ('COAGULATION', 'Coagulation', 'Coagulation', COAG, [], ['SCR', 'DM1', 'D4', 'EOS']),
    ('CHEMISTRY', 'Clinical Chemistry', 'Clinical Chemistry', CHEM, [], ['SCR', 'DM1', 'D2', 'D4', 'EOS']),
    ('URINALYSIS', 'Urinalysis', 'Urinalysis', UA, ['LEUKASE_URIN'], ['SCR', 'DM1', 'D4', 'EOS']),
    ('SEROLOGY', 'Virology Screen (HBsAg, HCV, HIV)', 'Serology', ['HBSAGSERPLPRES', 'HCRNASERPLPRES'], ['HIV12AB'], ['SCR']),
    ('PREG_SERUM', 'Serum Pregnancy Test (WOCBP)', 'Pregnancy Test', ['HCGSERPL'], [], ['SCR']),
    ('PREG_URINE', 'Urine Pregnancy Test (WOCBP)', 'Pregnancy Test', ['HCGURIN'], [], ['DM1', 'EOS']),
    ('DRUG_ALCOHOL_SCREEN', 'Urine Drug Screen and Alcohol Breath Test', 'Drug Screen', [], ['URINE_DRUG_SCREEN', 'ALCOHOL_BREATH'], ['SCR', 'DM1']),
    ('STUDY_DRUG_ADMIN', 'Study Drug Administration', 'Exposure', ['EXPOSCOLL'], [], ['D1']),
    ('PK_SAMPLING', 'PK Blood Sampling', 'Pharmacokinetics', [], ['PK_PLASMA'], ['D1', 'D2', 'D3', 'D4']),
    ('ADVERSE_EVENTS', 'Adverse Events', 'Adverse Events', ['AE'], [], ALL),
    ('CONMEDS', 'Prior and Concomitant Medications', 'Concomitant Medications', ['CMFREE'], [], ALL),
    ('DISP_TREATMENT', 'Study Treatment Disposition', 'Disposition', ['DSSTUDYTREATMENT'], [], ['D1']),
    ('DISP_STUDY', 'Study Participation Disposition', 'Disposition', ['DSSTUDYPARTICIPATION'], [], ['EOS']),
]
SURROGATES = {
    'PHYSICAL_EXAM': ('Physical Examination', 'Complete/symptom-directed physical examination by body system; no COSMoS specialization published (PE domain).'),
    'HIV12AB': ('HIV-1/2 Antibody Presence in Serum or Plasma', 'HIV-1/2 antibody/antigen combination screen; no COSMoS SDTM specialization published.'),
    'URINE_DRUG_SCREEN': ('Urine Drugs of Abuse Screen', 'Panel: amphetamines, barbiturates, benzodiazepines, cannabinoids, cocaine, opiates, methadone.'),
    'ALCOHOL_BREATH': ('Alcohol Breath Test', 'Breath ethanol screen.'),
    'LEUKASE_URIN': ('Leukocyte Esterase Presence in Urine', 'Dipstick leukocyte esterase (LBTESTCD LEUKASE, NCI C64856). No COSMoS BC or SDTM/CRF specialization published as of r18 / CRF draft 2026-07-31.'),
    'PK_PLASMA': ('CTX-101 Plasma Concentration', 'PK blood samples: predose, 0.5, 1, 2, 3, 4, 6, 8, 12, 24, 36, 48, 72 h post-dose (sub-timeline not modelled).'),
}

# ------------------------------------------------------------------ biomedical concepts
SDTM_URL = 'http://www.cdisc.org/usdm/extensions/specializations/sdtm'
CRF_URL = 'http://www.cdisc.org/usdm/extensions/specializations/crf'

def response_codes(row):
    """Resolve the specialization's assigned value / value list to NCI-coded ResponseCodes via term34."""
    out, sv = [], row['codelist_submission_value']
    vals = [row['assigned_value']] if row['assigned_value'] else [v for v in row['value_list'].split(';') if v]
    for v in vals:
        t = term_by.get((sv, v))
        c = t['nciCode'] if t else (row['assigned_term'] or 'SPONSOR')
        out.append(obj('ResponseCode', name=v, label=t['decodedValue'] if t else v, isEnabled=True,
                       code=code(c, v, ver=term['terminology']['version'], pt=False)))
    return out

bcs, bc_by_spec, bc_cats = [], {}, collections.OrderedDict()
def make_bc(spec_id, category):
    sh = hdr['sdtm'][spec_id]; bcid = sh['biomedicalConceptId']; bch = hdr['bc'].get(bcid, {})
    rows = sdtm_rows[spec_id]; by_dec = collections.defaultdict(list)
    for r in rows:
        if r['dec_id']: by_dec[r['dec_id']].append(r)
    props = []
    for dec in bch.get('dataElementConcepts', []):
        rs = by_dec.get(dec['conceptId'], [])
        if not rs: continue  # DEC not realised in this specialization -> not part of the study BC instance
        r = next((x for x in rs if x['role'] != 'Timing' or True), rs[0])
        rc = []
        for x in rs:
            if x['codelist_submission_value'] and (x['assigned_value'] or x['value_list']):
                rc = response_codes(x); break
        props.append(obj('BiomedicalConceptProperty', name=dec['shortName'], label=dec['shortName'],
                         isRequired=any(x['mandatory_variable'] == 'Y' for x in rs), isEnabled=True,
                         datatype=dec.get('dataType', '') or r['data_type'], responseCodes=rc,
                         code=alias(dec['conceptId'], dec['shortName'], ver=term['terminology']['version'], pt=False)))
    crf = crf_for(spec_id)
    exts = [ext(SDTM_URL, f'/mdr/specializations/sdtm/datasetspecializations/{spec_id}')]
    if crf: exts.append(ext(CRF_URL, f'/mdr/specializations/crf/specializations/{crf}'))
    bc = obj('BiomedicalConcept', name=sh['shortName'], label=bch.get('shortName', sh['shortName']),
             synonyms=bch.get('synonyms', []) or [], reference=f'/mdr/bc/biomedicalconcepts/{bcid}',
             properties=props, code=alias(bcid, bch.get('shortName', sh['shortName']), ver=term['terminology']['version'], pt=False),
             notes=[], extensionAttributes=exts)
    bcs.append(bc); bc_by_spec[spec_id] = bc['id']
    bc_cats.setdefault(category, []).append(bc['id'])
    return bc['id']

surrogates, sur_ids = [], {}
for k, (n, d) in SURROGATES.items():
    s = obj('BiomedicalConceptSurrogate', name=n, label=n, description=d, reference='Sponsor-defined', notes=[])
    surrogates.append(s); sur_ids[k] = s['id']

# ------------------------------------------------------------------ activities
activities = []
for name, label, cat, specs, surs, encs in ACTIVITIES:
    ids = [bc_by_spec.get(s) or make_bc(s, cat) for s in specs]
    activities.append(obj('Activity', name=name, label=label, description=label, childIds=[], definedProcedures=[],
                          biomedicalConceptIds=ids, bcCategoryIds=[], bcSurrogateIds=[sur_ids[s] for s in surs], notes=[]))
for i, a in enumerate(activities):
    a['previousId'] = activities[i - 1]['id'] if i else None
    a['nextId'] = activities[i + 1]['id'] if i + 1 < len(activities) else None
categories = [obj('BiomedicalConceptCategory', name=c, label=c, description=f'{c} biomedical concepts', childIds=[], memberIds=m, notes=[])
              for c, m in bc_cats.items()]

# ------------------------------------------------------------------ epochs, arms, elements, cells
EPOCH_CT = {'SCREENING': ('C202487', 'Screening'), 'TREATMENT': ('C101526', 'Treatment'), 'FOLLOW-UP': ('C202578', 'Follow-up')}
epochs = {k: obj('StudyEpoch', name=k, label=v[1], description=f'{v[1]} epoch', type=code(v[0], k), notes=[]) for k, v in EPOCH_CT.items()}
ep = list(epochs.values())
for i, e in enumerate(ep):
    e['previousId'] = ep[i - 1]['id'] if i else None; e['nextId'] = ep[i + 1]['id'] if i + 1 < len(ep) else None

ctx_int = obj('StudyIntervention', name='CTX-101', label='CTX-101', description='CTX-101 oral tablet (investigational, fictional compound)',
              role=code('C41161', 'Experimental Intervention'), type=code('C1909', 'DRUG'), codes=[], notes=[], administrations=[])
pbo_int = obj('StudyIntervention', name='PLACEBO', label='Placebo', description='Matching placebo tablet',
              role=code('C753', 'Placebo'), type=code('C1909', 'DRUG'), codes=[], notes=[], administrations=[])
ctx_prod = obj('AdministrableProduct', name='CTX-101 tablet', label='CTX-101 10 mg / 50 mg tablets', description='Immediate-release tablet',
               administrableDoseForm=alias('C42998', 'TABLET'), productDesignation=code('C202579', 'IMP'), sourcing=code('C215659', 'Centrally Sourced'),
               properties=[], identifiers=[], ingredients=[], notes=[])
pbo_prod = obj('AdministrableProduct', name='Placebo tablet', label='Placebo tablet', description='Matching placebo',
               administrableDoseForm=alias('C42998', 'TABLET'), productDesignation=code('C202579', 'IMP'), sourcing=code('C215659', 'Centrally Sourced'),
               properties=[], identifiers=[], ingredients=[], notes=[])
MG = alias('C28253', 'mg')
DOSES = [10, 30, 100, 300, 600]
for i, d in enumerate(DOSES, 1):
    ctx_int['administrations'].append(obj('Administration', name=f'CTX-101 {d} mg (Cohort {i})', label=f'Cohort {i}: {d} mg', description=f'Single oral dose of {d} mg CTX-101 on Day 1, fasted',
        duration=obj('Duration', text='Single dose', quantity=None, durationWillVary=False), dose=qty(d, MG), route=alias('C38288', 'ORAL'),
        frequency=alias('C64576', 'ONCE'), administrableProductId=ctx_prod['id'], notes=[]))
pbo_int['administrations'].append(obj('Administration', name='Placebo', label='Placebo', description='Single oral dose of matching placebo on Day 1, fasted',
    duration=obj('Duration', text='Single dose', quantity=None, durationWillVary=False), dose=None, route=alias('C38288', 'ORAL'),
    frequency=alias('C64576', 'ONCE'), administrableProductId=pbo_prod['id'], notes=[]))

def rule(name, text): return obj('TransitionRule', name=name, label=name, text=text)
elements = {
    'SCRN': obj('StudyElement', name='SCRN', label='Screening', description='Screening period',
                transitionStartRule=rule('SCRN_START', 'Informed consent'), transitionEndRule=rule('SCRN_END', 'Eligibility confirmed on Day -1'), studyInterventionIds=[], notes=[]),
    'CTX': obj('StudyElement', name='CTX', label='CTX-101', description='Single oral dose of CTX-101',
               transitionStartRule=rule('CTX_START', 'First dose of CTX-101 on Day 1'), transitionEndRule=rule('CTX_END', 'Discharge from clinical unit on Day 4'), studyInterventionIds=[ctx_int['id']], notes=[]),
    'PBO': obj('StudyElement', name='PBO', label='Placebo', description='Single oral dose of placebo',
               transitionStartRule=rule('PBO_START', 'First dose of placebo on Day 1'), transitionEndRule=rule('PBO_END', 'Discharge from clinical unit on Day 4'), studyInterventionIds=[pbo_int['id']], notes=[]),
    'FU': obj('StudyElement', name='FU', label='Follow-up', description='Safety follow-up',
              transitionStartRule=rule('FU_START', 'Discharge from clinical unit'), transitionEndRule=rule('FU_END', 'End of study visit (Day 14)'), studyInterventionIds=[], notes=[]),
}
arms = {
    'CTX101': obj('StudyArm', name='CTX101', label='CTX-101', description='CTX-101 single ascending dose (cohort-specific dose level)', type=code('C174266', 'Experimental Arm'),
                  dataOriginDescription='Data collected in study', dataOriginType=code('C188866', 'Data Generated Within Study'), populationIds=[], notes=[]),
    'PBO': obj('StudyArm', name='PBO', label='Placebo', description='Matching placebo', type=code('C174268', 'Placebo Comparator Arm'),
               dataOriginDescription='Data collected in study', dataOriginType=code('C188866', 'Data Generated Within Study'), populationIds=[], notes=[]),
}
cells = []
for a, trt in (('CTX101', 'CTX'), ('PBO', 'PBO')):
    for e, el in (('SCREENING', 'SCRN'), ('TREATMENT', trt), ('FOLLOW-UP', 'FU')):
        cells.append(obj('StudyCell', armId=arms[a]['id'], epochId=epochs[e]['id'], elementIds=[elements[el]['id']]))

# ------------------------------------------------------------------ encounters, timeline
TIMING_CT = {'Fixed Reference': 'C201358', 'After': 'C201356', 'Before': 'C201357'}
encs, sais, timings = {}, [], []
for key, name, label, day, ttype, val, wl, wu, wlab, epoch in ENCOUNTERS:
    encs[key] = obj('Encounter', name=name, label=label, description=f'{label} (Study Day {day})', type=code('C25716', 'Visit'),
                    environmentalSettings=[code('C211570', 'CLINIC')], contactModes=[code('C175574', 'IN PERSON')], notes=[],
                    transitionStartRule=rule(f'{key}_ADMIT', 'Admission to clinical unit') if key == 'DM1' else None,
                    transitionEndRule=rule(f'{key}_DISCH', 'Discharge from clinical unit') if key == 'D4' else None)
el = list(encs.values())
for i, e in enumerate(el):
    e['previousId'] = el[i - 1]['id'] if i else None; e['nextId'] = el[i + 1]['id'] if i + 1 < len(el) else None
exit_ = {'id': nid('ScheduleTimelineExit'), 'instanceType': 'ScheduleTimelineExit', 'extensionAttributes': []}
for key, name, label, day, ttype, val, wl, wu, wlab, epoch in ENCOUNTERS:
    acts = [a['id'] for a, spec in zip(activities, ACTIVITIES) if key in spec[5]]
    sais.append(obj('ScheduledActivityInstance', name=f'SAI_{key}', label=label, description=f'{label} activities', epochId=epochs[epoch]['id'],
                    activityIds=acts, encounterId=encs[key]['id'], defaultConditionId=None, timelineId=None,
                    timelineExitId=exit_['id'] if key == 'EOS' else None))
anchor = sais[ALL.index('D1')]['id']
for (key, name, label, day, ttype, val, wl, wu, wlab, epoch), s in zip(ENCOUNTERS, sais):
    t = obj('Timing', name=f'TIM_{key}', label=f'Study Day {day}', description=f'{label} relative to Day 1 dosing', type=code(TIMING_CT[ttype], ttype),
            value=val, valueLabel=f'Day {day}', relativeToFrom=code('C201355', 'Start to Start'),
            relativeFromScheduledInstanceId=s['id'], relativeToScheduledInstanceId=None if ttype == 'Fixed Reference' else anchor,
            windowLower=wl, windowUpper=wu, windowLabel=wlab)
    timings.append(t); encs[key]['scheduledAtId'] = t['id']
for i, s in enumerate(sais):
    s['defaultConditionId'] = sais[i + 1]['id'] if i + 1 < len(sais) else None
timeline = obj('ScheduleTimeline', name='MAIN', label='Main Timeline', description='Main schedule of activities', mainTimeline=True,
               entryCondition='Informed consent signed', entryId=sais[0]['id'], exits=[exit_], timings=timings, instances=sais,
               plannedDuration=obj('Duration', text='Up to 42 days (28-day screening + 14 days)', quantity=qty(42, alias('C25301', 'DAYS')), durationWillVary=True,
                                   reasonDurationWillVary='Screening window may be shorter than 28 days'))

# ------------------------------------------------------------------ Day 1 intensive sub-timeline (dosing, PK, safety)
SUB = [  # name, label, timing type, value, valueLabel, activities
    ('PREDOSE', 'Pre-dose', 'Before', 'PT1H', '-1 h', ['VITAL_SIGNS', 'ECG_12LEAD', 'PK_SAMPLING']),
    ('DOSE', 'Dose', 'Fixed Reference', 'PT0H', '0 h', ['STUDY_DRUG_ADMIN']),
    ('H0_5', '0.5 h', 'After', 'PT30M', '0.5 h', ['PK_SAMPLING']),
    ('H1', '1 h', 'After', 'PT1H', '1 h', ['VITAL_SIGNS', 'ECG_12LEAD', 'PK_SAMPLING']),
    ('H2', '2 h', 'After', 'PT2H', '2 h', ['VITAL_SIGNS', 'ECG_12LEAD', 'PK_SAMPLING']),
    ('H3', '3 h', 'After', 'PT3H', '3 h', ['PK_SAMPLING']),
    ('H4', '4 h', 'After', 'PT4H', '4 h', ['VITAL_SIGNS', 'ECG_12LEAD', 'PK_SAMPLING']),
    ('H6', '6 h', 'After', 'PT6H', '6 h', ['PK_SAMPLING']),
    ('H8', '8 h', 'After', 'PT8H', '8 h', ['VITAL_SIGNS', 'ECG_12LEAD', 'PK_SAMPLING']),
    ('H12', '12 h', 'After', 'PT12H', '12 h', ['VITAL_SIGNS', 'PK_SAMPLING']),
]
act_by_name = {a['name']: a for a in activities}
sub_exit = {'id': nid('ScheduleTimelineExit'), 'instanceType': 'ScheduleTimelineExit', 'extensionAttributes': []}
sub_sais, sub_timings = [], []
for nm, lab, tt, val, vl, acts in SUB:
    sub_sais.append(obj('ScheduledActivityInstance', name=f'D1_{nm}', label=lab, description=f'Day 1 {lab}', epochId=epochs['TREATMENT']['id'],
                        activityIds=[act_by_name[x]['id'] for x in acts], encounterId=None, defaultConditionId=None, timelineId=None,
                        timelineExitId=sub_exit['id'] if nm == SUB[-1][0] else None))
for i, x in enumerate(sub_sais):
    x['defaultConditionId'] = sub_sais[i + 1]['id'] if i + 1 < len(sub_sais) else None
dose_sai = sub_sais[1]['id']
for (nm, lab, tt, val, vl, acts), x in zip(SUB, sub_sais):
    sub_timings.append(obj('Timing', name=f'TIM_D1_{nm}', label=lab, description=f'{lab} relative to dosing', type=code(TIMING_CT[tt], tt), value=val, valueLabel=vl,
                           relativeToFrom=code('C201355', 'Start to Start'), relativeFromScheduledInstanceId=x['id'],
                           relativeToScheduledInstanceId=None if tt == 'Fixed Reference' else dose_sai,
                           windowLower='PT5M' if nm not in ('PREDOSE', 'DOSE') else None, windowUpper='PT5M' if nm not in ('PREDOSE', 'DOSE') else None,
                           windowLabel='+/- 5 min' if nm not in ('PREDOSE', 'DOSE') else None))
sub_timeline = obj('ScheduleTimeline', name='DAY1_INTENSIVE', label='Day 1 intensive sampling', description='Dosing, PK sampling and safety assessments on Day 1 (hours relative to dose)',
                   mainTimeline=False, entryCondition='Participant dosed on Day 1', entryId=sub_sais[0]['id'], exits=[sub_exit], timings=sub_timings, instances=sub_sais,
                   plannedDuration=obj('Duration', text='13 hours', quantity=qty(13, alias('C25529', 'HOURS')), durationWillVary=False))
sais[ALL.index('D1')]['timelineId'] = sub_timeline['id']

# ------------------------------------------------------------------ eligibility, objectives, population
INCL = ['Healthy male or female participants aged 18 to 55 years inclusive at screening.',
        'Body mass index (BMI) of 18.0 to 32.0 kg/m2 inclusive and body weight of at least 50 kg at screening.',
        'Healthy as determined by medical history, physical examination, vital signs, 12-lead ECG and clinical laboratory tests at screening and Day -1.',
        'Women of childbearing potential must have a negative pregnancy test at screening and Day -1 and agree to use highly effective contraception.',
        'Able and willing to provide written informed consent and comply with study procedures.']
EXCL = ['History or presence of clinically significant cardiovascular, respiratory, hepatic, renal, gastrointestinal, endocrine, hematological or neurological disease.',
        'QTcF greater than 450 ms (males) or greater than 470 ms (females) at screening or Day -1.',
        'ALT or AST greater than 1.5 x ULN, or total bilirubin greater than ULN at screening.',
        'Positive test for hepatitis B surface antigen, hepatitis C virus RNA, or HIV-1/2 antibody.',
        'Positive urine drug screen or alcohol breath test at screening or Day -1.',
        'Use of any prescription or over-the-counter medication within 14 days before dosing.',
        'Participation in another interventional clinical study within 30 days or 5 half-lives before dosing.']
crit_items, crits = [], []
for cat, ccode, texts, pref in (('INCLUSION', 'C25532', INCL, 'INCL'), ('EXCLUSION', 'C25370', EXCL, 'EXCL')):
    for i, t in enumerate(texts, 1):
        it = obj('EligibilityCriterionItem', name=f'{pref}{i:02d}', label=f'{cat.title()} {i}', text=t, notes=[])
        crit_items.append(it)
        crits.append(obj('EligibilityCriterion', name=f'{pref}{i:02d}', label=f'{cat.title()} criterion {i}', category=code(ccode, cat),
                         identifier=f'{pref[0]}{i}', criterionItemId=it['id'], notes=[]))
for i, c in enumerate(crits):
    c['previousId'] = crits[i - 1]['id'] if i else None; c['nextId'] = crits[i + 1]['id'] if i + 1 < len(crits) else None

objectives = [
    obj('Objective', name='OBJ_PRI', label='Primary objective', text='To evaluate the safety and tolerability of single ascending oral doses of CTX-101 in healthy adult participants.',
        level=code('C85826', 'Study Primary Objective'), notes=[], endpoints=[
            obj('Endpoint', name='EP_PRI_1', label='TEAEs', text='Incidence and severity of treatment-emergent adverse events.', purpose='Safety', level=code('C94496', 'Primary Endpoint'), notes=[]),
            obj('Endpoint', name='EP_PRI_2', label='Safety parameters', text='Change from baseline in vital signs, 12-lead ECG parameters (including QTcF) and clinical laboratory tests.',
                purpose='Safety', level=code('C94496', 'Primary Endpoint'), notes=[])]),
    obj('Objective', name='OBJ_SEC', label='Secondary objective', text='To characterise the single-dose plasma pharmacokinetics of CTX-101.',
        level=code('C85827', 'Study Secondary Objective'), notes=[], endpoints=[
            obj('Endpoint', name='EP_SEC_1', label='PK parameters', text='Plasma CTX-101 Cmax, tmax, AUC0-last, AUC0-inf and t1/2.', purpose='Pharmacokinetics',
                level=code('C139173', 'Secondary Endpoint'), notes=[])]),
]
cohorts = [obj('StudyCohort', name=f'COHORT{i}', label=f'Cohort {i} ({d} mg)', description=f'6 x CTX-101 {d} mg : 2 x placebo', includesHealthySubjects=True,
               plannedEnrollmentNumber=qty(8), plannedSex=[], criterionIds=[], notes=[], characteristics=[], indicationIds=[]) for i, d in enumerate(DOSES, 1)]
YEARS = lambda: alias('C29848', 'YEARS')
population = obj('StudyDesignPopulation', name='POP', label='Healthy adult participants', description='Healthy male and female adults',
                 includesHealthySubjects=True, plannedEnrollmentNumber=qty(40), plannedCompletionNumber=qty(40),
                 plannedSex=[code('C16576', 'F'), code('C20197', 'M')], criterionIds=[c['id'] for c in crits],
                 plannedAge=obj('Range', minValue=qty(18, YEARS()), maxValue=qty(55, YEARS()), isApproximate=False), notes=[], cohorts=cohorts)
analysis_pops = [obj('AnalysisPopulation', name='SAF', label='Safety Population', text='All randomised participants who received study drug.', subsetOfIds=[], notes=[]),
                 obj('AnalysisPopulation', name='PK', label='PK Population', text='All participants who received CTX-101 with at least one evaluable concentration.', subsetOfIds=[], notes=[])]
wocbp = obj('Condition', name='COND_WOCBP', label='Women of childbearing potential only', text='Performed only for women of childbearing potential.',
            notes=[], contextIds=[], appliesToIds=[a['id'] for a in activities if a['name'].startswith('PREG_')])

design = obj('InterventionalStudyDesign', name='CTX101-001 Design', label='SAD design', description='Randomised, double-blind, placebo-controlled, sequential-cohort single ascending dose',
             studyType=code('C98388', 'INTERVENTIONAL'), studyPhase=alias('C15600', 'PHASE I TRIAL'), therapeuticAreas=[],
             characteristics=[code('C46079', 'Randomized'), code('C217004', 'Single-Centre'), code('C217006', 'Single Country')],
             encounters=list(encs.values()), activities=activities, arms=list(arms.values()), studyCells=cells,
             rationale='First-in-human assessment of safety, tolerability and PK across 5 sequential dose cohorts (6 active : 2 placebo).',
             epochs=ep, elements=list(elements.values()), estimands=[], indications=[], studyInterventionIds=[ctx_int['id'], pbo_int['id']],
             objectives=objectives, population=population, scheduleTimelines=[timeline, sub_timeline], biospecimenRetentions=[], documentVersionIds=[],
             eligibilityCriteria=crits, analysisPopulations=analysis_pops, notes=[], subTypes=[code('C49667', 'SAFETY'), code('C98791', 'TOLERABILITY'), code('C49663', 'PHARMACOKINETIC')],
             model=code('C142568', 'SEQUENTIAL'), intentTypes=[], blindingSchema=alias('C15228', 'DOUBLE BLIND'))

# ------------------------------------------------------------------ organizations, identifiers, titles, documents
sponsor = obj('Organization', name='Example Biopharma Ltd', label='Example Biopharma (fictional sponsor)', type=code('C54149', 'Pharmaceutical Company'),
              identifierScheme='DUNS', identifier='000000000', legalAddress=None, managedSites=[])
registry = obj('Organization', name='ClinicalTrials.gov', label='ClinicalTrials.gov', type=code('C93453', 'Clinical Study Registry'),
               identifierScheme='USGOV', identifier='CT-GOV', legalAddress=None, managedSites=[])
global_scope = lambda: obj('GeographicScope', type=code('C68846', 'Global'), code=None)
approval = obj('GovernanceDate', name='SPONSOR_APPROVAL', label='Sponsor approval', description='Protocol sponsor approval date',
               type=code('C71476', 'Approval Date'), dateValue='2026-09-01', geographicScopes=[global_scope()])
doc_ver = obj('StudyDefinitionDocumentVersion', version='1.0', status=code('C25508', 'Final'), dateValues=[], contents=[], notes=[])
doc = obj('StudyDefinitionDocument', name='CTX101-001 Protocol', label='Protocol', description='Clinical study protocol', language=code('en', 'English', system='ISO 639-1', ver='2007'),
          type=code('C70817', 'Protocol'), templateName='Sponsor', versions=[doc_ver], childIds=[], notes=[])
design['documentVersionIds'] = [doc_ver['id']]
version = obj('StudyVersion', versionIdentifier='1.0', rationale='Original protocol', documentVersionIds=[doc_ver['id']], dateValues=[approval], amendments=[],
              businessTherapeuticAreas=[code('TA-IMM', 'Immunology', system='http://www.example.com/sponsor-therapeutic-areas', ver='2026')],
              studyIdentifiers=[obj('StudyIdentifier', text='CTX101-001', scopeId=sponsor['id']), obj('StudyIdentifier', text='NCT09999999', scopeId=registry['id'])],
              referenceIdentifiers=[], studyDesigns=[design],
              titles=[obj('StudyTitle', text='A Phase 1, Randomised, Double-Blind, Placebo-Controlled, Single Ascending Dose Study to Evaluate the Safety, Tolerability and Pharmacokinetics of CTX-101 in Healthy Adult Participants', type=code('C207616', 'Official Study Title')),
                      obj('StudyTitle', text='CTX-101 Single Ascending Dose Study in Healthy Adults', type=code('C207615', 'Brief Study Title')),
                      obj('StudyTitle', text='CTX101-SAD', type=code('C207646', 'Study Acronym'))],
              eligibilityCriterionItems=crit_items, narrativeContentItems=[], abbreviations=[],
              roles=[obj('StudyRole', name='SPONSOR', label='Sponsor', code=code('C70793', 'Sponsor'), appliesToIds=[], assignedPersons=[], organizationIds=[sponsor['id']], masking=None, notes=[])],
              organizations=[sponsor, registry], studyInterventions=[ctx_int, pbo_int], administrableProducts=[ctx_prod, pbo_prod], medicalDevices=[],
              productOrganizationRoles=[], biomedicalConcepts=bcs, bcCategories=categories, bcSurrogates=surrogates, dictionaries=[], conditions=[wocbp], notes=[])
study = obj('Study', name='CTX101-001', label='CTX-101 SAD', description='Fictional Phase 1 SAD study for the USDM -> P21 POC', versions=[version], documentedBy=[doc])
study['id'] = '7f3c1a2e-5b4d-4e8f-9a10-c7d2b1e0f101'
wrapper = {'study': study, 'usdmVersion': '4.0.0', 'systemName': 'Certara USDM-P21 POC builder', 'systemVersion': '0.1'}

Wrapper.model_validate(wrapper)  # pydantic validation against the CDISC USDM 4.0 model
json.dump(wrapper, open(OUT, 'w'), indent=2)
print(f'USDM written: {len(bcs)} BCs, {len(surrogates)} surrogates, {len(activities)} activities, {len(encs)} encounters, {len(crits)} criteria')
