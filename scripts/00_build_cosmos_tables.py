"""Flatten COSMoS YAML (BC, SDTM dataset specializations, CRF specializations) into the
tables we'd hold locally in P21: cosmos_bc, cosmos_sdtm_item, cosmos_crf_item.
Input: directory of COSMoS YAMLs pulled from github.com/cdisc-org/COSMoS (yaml/<package>/{bc,sdtm,crf}).
Only the latest package version of each specialization is kept."""
import yaml, glob, json, csv, sys, os
src, out = sys.argv[1], sys.argv[2]
def latest(kind, key):
    best = {}
    for f in glob.glob(f'{src}/*__{kind}__*.yaml'):
        d = yaml.safe_load(open(f)); k = d[key]
        if k not in best or str(d['packageDate']) > str(best[k]['packageDate']): best[k] = d
    return best
bcs = latest('bc', 'conceptId'); sdtm = latest('sdtm', 'datasetSpecializationId'); crf = latest('crf', 'crfSpecializationId')

SDTM_COLS = "package_date,bc_id,sdtmig_start_version,sdtmig_end_version,domain,vlm_source,vlm_group_id,short_name,sdtm_variable,dec_id,nsv_flag,codelist,codelist_submission_value,subset_codelist,value_list,assigned_term,assigned_value,role,subject,linking_phrase,predicate_term,object,data_type,length,format,significant_digits,mandatory_variable,mandatory_value,origin_type,origin_source,comparator,vlm_target".split(',')
yn = lambda b: '' if b is None else ('Y' if b else 'N')
rows = []
for sid, d in sdtm.items():
    for v in d.get('variables', []):
        cl, at, rel = v.get('codelist') or {}, v.get('assignedTerm') or {}, v.get('relationship') or {}
        rows.append(dict(package_date=d['packageDate'], bc_id=d.get('biomedicalConceptId', ''), sdtmig_start_version=d.get('sdtmigStartVersion', ''),
            sdtmig_end_version=d.get('sdtmigEndVersion', ''), domain=d['domain'], vlm_source=d.get('source', ''), vlm_group_id=sid,
            short_name=d['shortName'], sdtm_variable=v['name'], dec_id=v.get('dataElementConceptId', ''), nsv_flag=yn(v.get('isNonStandard')),
            codelist=cl.get('conceptId', ''), codelist_submission_value=cl.get('submissionValue', ''), subset_codelist=v.get('subsetCodelist', ''),
            value_list=';'.join(map(str, v.get('valueList', []) or [])), assigned_term=at.get('conceptId', ''), assigned_value=at.get('value', ''),
            role=v.get('role', ''), subject=rel.get('subject', ''), linking_phrase=rel.get('linkingPhrase', ''), predicate_term=rel.get('predicateTerm', ''),
            object=rel.get('object', ''), data_type=v.get('dataType', ''), length=v.get('length', ''), format=v.get('format', ''),
            significant_digits=v.get('significantDigits', ''), mandatory_variable=yn(v.get('mandatoryVariable')), mandatory_value=yn(v.get('mandatoryValue')),
            origin_type=v.get('originType', ''), origin_source=v.get('originSource', ''), comparator=v.get('comparator', ''), vlm_target=yn(v.get('vlmTarget'))))
with open(f'{out}/cosmos_sdtm_item.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, SDTM_COLS); w.writeheader(); w.writerows(rows)

CRF_COLS = "package_date,crf_specialization_id,crf_group_id,implementation_option,scenario,domain,bc_id,sdtm_dataset_specialization_id,crf_item,variable_name,dec_id,question_text,prompt,order_number,mandatory_variable,data_type,length,significant_digits,display_hidden,derived_variable,codelist,codelist_submission_value,value_list,value_list_display,prepopulated_term,prepopulated_term_code,selection_type,sdtm_annotation,sdtm_target_variables".split(',')
crow = []
for cid, d in crf.items():
    for it in d.get('items', []):
        cl, pp, st = it.get('codelist') or {}, it.get('prepopulatedValue') or {}, it.get('sdtmTarget') or {}
        vl = it.get('valueList') or []
        crow.append(dict(package_date=d['packageDate'], crf_specialization_id=cid, crf_group_id=cid, implementation_option=d.get('implementationOption', ''),
            scenario=d.get('scenario', ''), domain=d['domain'], bc_id=d.get('biomedicalConceptId', ''), sdtm_dataset_specialization_id=d.get('sdtmDatasetSpecializationId', ''),
            crf_item=it['name'], variable_name=it.get('variableName', ''), dec_id=it.get('dataElementConceptId', ''), question_text=it.get('questionText', ''),
            prompt=it.get('prompt', ''), order_number=it.get('orderNumber', ''), mandatory_variable=yn(it.get('mandatoryVariable')), data_type=it.get('dataType', ''),
            length=it.get('length', ''), significant_digits=it.get('significantDigits', ''), display_hidden=yn(it.get('displayHidden')), derived_variable=yn(it.get('derivedVariable')),
            codelist=cl.get('conceptId', ''), codelist_submission_value=cl.get('submissionValue', ''),
            value_list=';'.join(str(x.get('value', x)) if isinstance(x, dict) else str(x) for x in vl),
            value_list_display=';'.join(str(x.get('displayValue', '')) if isinstance(x, dict) else '' for x in vl),
            prepopulated_term=pp.get('value', ''), prepopulated_term_code=pp.get('conceptId', ''), selection_type=it.get('selectionType', ''),
            sdtm_annotation=st.get('sdtmAnnotation', ''), sdtm_target_variables=';'.join(st.get('sdtmVariables', []) or [])))
with open(f'{out}/cosmos_crf_item.csv', 'w', newline='') as fh:
    w = csv.DictWriter(fh, CRF_COLS); w.writeheader(); w.writerows(crow)

json.dump({'bc': bcs, 'sdtm': {k: {kk: vv for kk, vv in v.items() if kk != 'variables'} for k, v in sdtm.items()},
           'crf': {k: {kk: vv for kk, vv in v.items() if kk != 'items'} for k, v in crf.items()}},
          open(f'{out}/cosmos_headers.json', 'w'), indent=1, default=str)
print(len(bcs), 'BCs', len(sdtm), 'SDTM specs', len(rows), 'rows', len(crf), 'CRF specs', len(crow), 'rows')
