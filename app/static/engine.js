/* USDM -> P21 generation engine (browser + node). Port of scripts/02_generate_p21.py */
(function (root) {
'use strict';
const SD_URL = 'http://www.cdisc.org/usdm/extensions/specializations/sdtm';
const CRF_URL = 'http://www.cdisc.org/usdm/extensions/specializations/crf';
const P21 = 'https://www.certara.com/usdm/extensions/p21';
const TDM = ['TA', 'TE', 'TV', 'TI', 'TS'];
const DICTIONARIES = new Set(['MedDRA', 'WHODD', 'LOINC', 'SNOMED', 'UNII', 'ISO3166', 'ISO 3166', 'ISO 8601']);

function Engine(D) {
  this.D = D;
  const zip = (cols, row) => { const o = {}; cols.forEach((c, i) => o[c] = row[i] == null ? '' : row[i]); return o; };
  this.sdtmRows = {}; for (const k in D.sdtm) this.sdtmRows[k] = D.sdtm[k].rows.map(r => zip(D.SCOLS, r));
  this.crfItems = {}; for (const k in D.crf) this.crfItems[k] = D.crf[k].items.map(r => zip(D.CCOLS, r));
  this.allTopicCodes = new Set(); for (const k in this.sdtmRows) { const t = this.sdtmRows[k].find(r => r.role === 'Topic' && r.assigned_value); if (t) this.allTopicCodes.add(t.assigned_value.toUpperCase()); }
  this.mVar = {}; for (const d in D.vars) { this.mVar[d] = {}; D.vars[d].forEach(r => { const v = zip(D.VC, r); this.mVar[d][v.variable] = v; }); }
  this.termBy = {}; this.termByCode = {};
  for (const cl in D.terms) D.terms[cl].forEach(t => { const o = { internalId: t[0], term: t[1], decodedValue: t[2], nciCode: t[3], codelist: cl };
    this.termBy[cl + '|' + t[1]] = o; this.termByCode[cl + '|' + t[3]] = o; });
}

/* ---------------------------------------------------------------- USDM model */
Engine.prototype.parse = function (u) {
  const study = u.study, sv = study.versions[0], design = sv.studyDesigns[0];
  const bcById = {}; (sv.biomedicalConcepts || []).forEach(b => bcById[b.id] = b);
  const surById = {}; (sv.bcSurrogates || []).forEach(s => surById[s.id] = s);
  const catById = {}; (sv.bcCategories || []).forEach(c => catById[c.id] = c);
  const chain = (arr) => { // order by previous/next chain where present
    if (!arr.length || !arr.some(a => a.nextId || a.previousId)) return arr.slice();
    const by = {}; arr.forEach(a => by[a.id] = a);
    let head = arr.find(a => !a.previousId || !by[a.previousId]); const out = [], seen = new Set();
    while (head && !seen.has(head.id)) { out.push(head); seen.add(head.id); head = by[head.nextId]; }
    arr.forEach(a => { if (!seen.has(a.id)) out.push(a); }); return out;
  };
  const acts = chain(design.activities || []);
  const childOf = new Set(); acts.forEach(a => (a.childIds || []).forEach(c => childOf.add(c)));
  const catMembers = (cid, seen = new Set()) => { const c = catById[cid]; if (!c || seen.has(cid)) return []; seen.add(cid);
    return [...(c.memberIds || []), ...(c.childIds || []).flatMap(x => catMembers(x, seen))]; };
  const activities = acts.map(a => ({ a, isParent: (a.childIds || []).length > 0, isChild: childOf.has(a.id),
    bcIds: [...new Set([...(a.biomedicalConceptIds || []), ...(a.bcCategoryIds || []).flatMap(c => catMembers(c))])].filter(id => bcById[id]),
    surIds: (a.bcSurrogateIds || []).filter(id => surById[id]) }));
  const tl = (design.scheduleTimelines || []).find(t => t.mainTimeline) || (design.scheduleTimelines || [])[0];
  const encById = {}; (design.encounters || []).forEach(e => encById[e.id] = e);
  const epById = {}; (design.epochs || []).forEach(e => epById[e.id] = e);
  const orderSais = t => { let ss = (t.instances || []).filter(i => i.instanceType === 'ScheduledActivityInstance');
    if (t.entryId && ss.some(x => x.defaultConditionId)) { // follow the default-condition chain from entry
      const by = {}; ss.forEach(x => by[x.id] = x); const out = [], seen = new Set(); let cur = by[t.entryId];
      while (cur && !seen.has(cur.id)) { out.push(cur); seen.add(cur.id); cur = by[cur.defaultConditionId]; }
      ss.forEach(x => { if (!seen.has(x.id)) out.push(x); }); ss = out; }
    return ss; };
  const timingMap = t => { const m = {}; (t.timings || []).forEach(x => m[x.relativeFromScheduledInstanceId] = x); return m; };
  const sais = tl ? orderSais(tl) : [];
  const timingByInst = tl ? timingMap(tl) : {};
  // sub-timelines: every non-main timeline, with what triggers it (main SAIs / activities pointing at it)
  const allSais = (design.scheduleTimelines || []).flatMap(t => (t.instances || []).map(i => [i, t]));
  const subTimelines = (design.scheduleTimelines || []).filter(t => t !== tl).map(t => ({ tl: t, sais: orderSais(t), timingByInst: timingMap(t),
    triggers: [...allSais.filter(([i]) => i.timelineId === t.id).map(([i, p]) => ({ kind: 'instance', name: (encById[i.encounterId] || {}).name || i.label || i.name, timeline: p.name })),
               ...(design.activities || []).filter(a => a.timelineId === t.id).map(a => ({ kind: 'activity', name: a.label || a.name }))] }));
  const bcActs = {}; activities.forEach(x => x.bcIds.forEach(b => (bcActs[b] = bcActs[b] || []).push(x.a)));
  return { u, study, sv, design, activities, bcById, surById, tl, sais, encById, epById, timingByInst, subTimelines, bcActs };
};

/* ---------------------------------------------------------------- candidates & suggestions */
const specimenOf = (name) => { const n = (name || '').toLowerCase();
  if (n.includes('platelet poor plasma')) return 'PPP'; if (n.includes('urine')) return 'URINE'; if (n.includes('serum') || n.includes('plasma')) return 'SERPL';
  if (n.includes('blood')) return 'BLOOD'; if (n.includes('stool')) return 'STOOL'; return ''; };
const analyteOf = (name) => (name || '').toLowerCase().replace(/\(.*?\)/g, '').split(/ (concentration|presence|count|measurement|activity|in|of|by) /)[0].trim();
const contextSpecimen = (txt) => { const t = txt.toLowerCase();
  if (/urin|dipstick/.test(t)) return 'URINE'; if (/coag/.test(t)) return 'PPP'; if (/h(a)?emat|blood count|cbc/.test(t)) return 'BLOOD';
  if (/chem|serolog|virolog|serum|biochem|lipid|liver|renal|electrolyte/.test(t)) return 'SERPL'; return ''; };
Engine.prototype.sdtmCandidates = function (bc, acts) {
  const D = this.D, code = bc.code && bc.code.standardCode && bc.code.standardCode.code;
  const ctxTxt = (acts || []).map(a => [a.name, a.label, a.description].join(' ')).join(' ') + ' ' + bc.name;
  const ctx = contextSpecimen(ctxTxt), urinalysis = /urin|dipstick/i.test(ctxTxt);
  const out = [];
  for (const k in D.sdtm) {
    const s = D.sdtm[k]; if (s.bc !== code) continue;
    if (!this.versionOk(k)) continue;
    let score = 10; const why = [];
    if ((s.name || '').toLowerCase() === (bc.name || '').toLowerCase()) { score += 100; why.push('name match'); }
    const sp = specimenOf(s.name);
    if (ctx && sp) { if (sp === ctx || (ctx === 'SERPL' && sp === 'SERPL')) { score += 50; why.push('specimen fits activity (' + sp + ')'); }
                     else if (ctx === 'BLOOD' && sp === 'SERPL' || ctx === 'SERPL' && sp === 'BLOOD') { score += 15; } else score -= 20; }
    if (urinalysis && /presence/i.test(s.name)) { score += 20; why.push('presence test in urinalysis'); }
    if (/RETIRED/.test(s.name)) { score -= 100; why.push('retired'); }
    out.push({ id: k, name: s.name, domain: s.d, score, why: why.join('; ') });
  }
  return out.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
};
Engine.prototype.crfCandidates = function (sdtmId, bc) {
  const D = this.D; if (!sdtmId) return [];
  const code = D.sdtm[sdtmId] ? D.sdtm[sdtmId].bc : (bc && bc.code.standardCode.code);
  const sp = specimenOf(D.sdtm[sdtmId] && D.sdtm[sdtmId].name);
  const out = [];
  for (const k in D.crf) {
    const c = D.crf[k], exact = c.sdtm === sdtmId;
    if (!exact && c.bc !== code) continue;
    let score = exact ? 100 : 10;
    if (exact) { if (k === sdtmId + '_DENORMALIZED') score += 30; else if (k === sdtmId) score += 25; else if (k === sdtmId + '_NORMALIZED') score += 20;
                 score -= k.length / 100; if (/_360|_SHORT|_MF/.test(k)) score -= 10; }
    else { const csp = specimenOf(D.sdtm[c.sdtm] ? D.sdtm[c.sdtm].name : c.name);
           if (analyteOf(D.sdtm[sdtmId] && D.sdtm[sdtmId].name) !== analyteOf(c.name)) score -= 60;   // same BC code but different analyte (e.g. COSMoS mis-tag)
           if (sp && csp) { if (csp === sp) score += 30; else if ((sp === 'SERPL' && csp === 'BLOOD') || (sp === 'BLOOD' && csp === 'SERPL')) score += 20; else score -= 30; } }
    out.push({ id: k, name: c.name, exact, nativeSdtm: c.sdtm, score });
  }
  return out.sort((a, b) => b.score - a.score || a.id.localeCompare(b.id));
};
Engine.prototype.extOf = function (o, url) { const e = (o.extensionAttributes || []).find(x => x.url === url); return e && e.valueString ? e.valueString.replace(/\/$/, '').split('/').pop() : null; };
Engine.prototype.readSelections = function (M) {
  const sel = {};
  for (const id in M.bcById) { const b = M.bcById[id], s = this.extOf(b, SD_URL), c = this.extOf(b, CRF_URL);
    if (s || c) sel[id] = { sdtm: s || '', crf: c || '', confirmed: true, source: 'extension' }; }
  return sel;
};
Engine.prototype.readFormSources = function (M) {
  const out = {}; M.activities.forEach(x => { const e = (x.a.extensionAttributes || []).find(e => e.url === P21 + '/form-source'); if (e) out[x.a.id] = e.valueString; }); return out;
};
Engine.prototype.suggest = function (M, sel, overwrite) {
  sel = sel || {};
  for (const id in M.bcById) {
    if (sel[id] && !overwrite) continue;
    const b = M.bcById[id], s = this.sdtmCandidates(b, M.bcActs[id])[0];
    const c = s ? this.crfCandidates(s.id, b).filter(x => x.score > 0)[0] : null;
    sel[id] = { sdtm: s ? s.id : '', crf: c ? c.id : '', confirmed: false, source: 'suggested' };
  }
  return sel;
};
Engine.prototype.matchType = function (s) {
  if (!s || !s.sdtm) return 'none';
  if (!s.crf) return 'sdtm-only';
  return this.D.crf[s.crf] && this.D.crf[s.crf].sdtm === s.sdtm ? 'exact' : 'cross';
};

/* reconcile one CRF item with the selected SDTM specialization (SDTM side authoritative) */
Engine.prototype.reconcileItem = function (s, c, r0) {
  const D = this.D, r = Object.assign({}, r0), out = { r, note: '', base: c.replace(/_(DENORMALIZED|NORMALIZED)$/, ''), overrides: [], review: false };
  const crfSdtm = D.crf[c].sdtm; if (!(s && crfSdtm && crfSdtm !== s)) return out;
  const mapType = t => ({ decimal: 'float', float: 'float', integer: 'integer', text: 'text', string: 'text', datetime: 'datetime', date: 'date', boolean: 'text' }[t] || t || null);
  const sr = this.sdtmRows[s].find(x => x.sdtm_variable === (r.sdtm_target_variables.split(';')[0] || ''));
  const nativeVars = new Set(this.sdtmRows[crfSdtm] ? this.sdtmRows[crfSdtm].map(x => x.sdtm_variable) : []);
  const tgt = r.sdtm_target_variables.split(';')[0] || '';
  if (sr) {
    if (sr.assigned_value && r.prepopulated_term && r.prepopulated_term !== sr.assigned_value) {
      out.overrides.push({ item: r.crf_item, field: 'prepopulated value', from: r.prepopulated_term, to: sr.assigned_value });
      r.sdtm_annotation = r.sdtm_annotation.split(r.prepopulated_term).join(sr.assigned_value); r.prepopulated_term = sr.assigned_value;
      r.codelist_submission_value = sr.codelist_submission_value || r.codelist_submission_value; }
    const a = new Set(sr.value_list ? sr.value_list.split(';') : []), b = new Set(r.value_list ? r.value_list.split(';').filter(Boolean) : []);
    if (sr.value_list && (a.size !== b.size || [...a].some(x => !b.has(x)))) {
      out.overrides.push({ item: r.crf_item, field: 'value list', from: r.value_list || '(none)', to: sr.value_list });
      r.value_list = sr.value_list; r.value_list_display = ''; r.codelist_submission_value = sr.codelist_submission_value || r.codelist_submission_value;
      r.selection_type = r.selection_type || 'Single'; }
    const st = sr.data_type ? mapType(sr.data_type) : null;
    if (st && r.data_type && st !== mapType(r.data_type) && !(st === 'float' && (r.data_type === 'decimal' || r.data_type === 'float'))) {
      out.overrides.push({ item: r.crf_item, field: 'data type', from: r.data_type, to: st }); r.data_type = st; }
    out.base = s;
  } else if (nativeVars.has(tgt)) { out.review = true; out.note = `Review: ${tgt} is not part of SDTM specialization ${s} (item comes from CRF specialization ${c})`; }
  return out;
};

/* ---------------------------------------------------------------- form library (tier 1) */
Engine.prototype.topicCode = function (spec) {
  if (!spec || !this.sdtmRows[spec]) return null; const t = this.sdtmRows[spec].find(r => r.role === 'Topic' && r.assigned_value); return t ? t.assigned_value.toUpperCase() : null;
};
Engine.prototype.qTokens = function (q) {
  return new Set([q.id, q.sdtmTarget, q.questionText, q.section].filter(Boolean).join(' ').toUpperCase().split(/[^A-Z0-9]+/).filter(Boolean));
};
/* explicit test codes a library question is about: "...TESTCD = X" in the SDTM target, or an ID like X_VSORRES */
Engine.prototype.qTestCodes = function (q) {
  const out = new Set(), t = (q.sdtmTarget || '').toUpperCase();
  for (const m of t.matchAll(/[A-Z]{2}TESTCD\s*(?:=|EQ|IN)\s*\(?\s*"?([A-Z0-9_]+)/g)) out.add(m[1]);
  const m2 = String(q.id || '').toUpperCase().match(/^([A-Z0-9]+)_[A-Z]{2}(ORRES|ORRESU|STAT|REASND|PERF|ND)/); if (m2) out.add(m2[1]);
  return out;
};
Engine.prototype.setFormLibrary = function (lib, name) {
  if (!lib) { this.lib = null; return; }
  const L = { name: name || (lib.header && lib.header.name) || 'Form library', formById: {}, questionsByForm: {}, codelistById: {}, termsByCl: {} };
  (lib.forms || []).forEach(f => { L.formById[f.id] = f; L.questionsByForm[f.id] = []; });
  (lib.questions || []).forEach(q => { (L.questionsByForm[q.form] = L.questionsByForm[q.form] || []).push(q); if (!L.formById[q.form]) L.formById[q.form] = { id: q.form, name: q.form }; });
  Object.values(L.questionsByForm).forEach(a => a.sort((x, y) => (+x.order || 0) - (+y.order || 0)));
  (lib.codelists || []).forEach(c => L.codelistById[c.id] = c);
  (lib.terms || []).forEach(t => (L.termsByCl[t.codelist] = L.termsByCl[t.codelist] || []).push(t));
  this.lib = L;
};
/* rank library forms for an activity by how many of its BCs (topic test codes) the form's questions mention */
Engine.prototype.libraryCandidates = function (M, actX, sel) {
  if (!this.lib) return [];
  const codes = actX.bcIds.map(id => this.topicCode((sel[id] || {}).sdtm)).filter(Boolean);
  if (!codes.length) return [];
  const out = [];
  for (const fid in this.lib.questionsByForm) {
    const toks = new Set(); this.lib.questionsByForm[fid].forEach(q => this.qTokens(q).forEach(t => toks.add(t)));
    const hit = codes.filter(c => toks.has(c)).length;
    if (hit) out.push({ id: fid, name: this.lib.formById[fid].name || fid, hit, of: codes.length });
  }
  return out.sort((a, b) => b.hit - a.hit || a.id.localeCompare(b.id));
};
Engine.prototype.versionOk = function (specId) {
  const s = this.D.sdtm[specId], std = this.D.std || {};
  if (!s || !s.v || !/SDTMIG/i.test(std.name || '') || !std.version) return true;
  const n = x => String(x).replace('-', '.').split('.').map(Number), cmp = (a, b) => { a = n(a); b = n(b); for (let i = 0; i < 3; i++) { const d = (a[i] || 0) - (b[i] || 0); if (d) return d; } return 0; };
  if (s.v[0] && cmp(std.version, s.v[0]) < 0) return false;
  if (s.v[1] && cmp(std.version, s.v[1]) > 0) return false;
  return true;
};

/* ---------------------------------------------------------------- generation */
Engine.prototype.generate = function (M, sel, opts) {
  opts = Object.assign({ mandatoryOnly: true, vlm: true }, opts || {});
  const E = this, D = this.D, now = new Date().toISOString().slice(0, 19);
  const report = {}; const rep = (k, v) => (report[k] = report[k] || []).push(v);
  const prov = (o) => Object.assign({ generatedBy: 'USDM-P21 Workbench POC', generatedAt: now, usdmStudy: M.study.name }, o || {});
  const sv = M.sv, design = M.design;
  const mapType = t => ({ decimal: 'float', float: 'float', integer: 'integer', text: 'text', string: 'text', datetime: 'datetime', date: 'date', boolean: 'text' }[t] || t || null);
  const sub = (cl, c) => { const code = typeof c === 'object' ? c.code : c; const t = E.termByCode[cl + '|' + code]; return t ? t.term : (typeof c === 'object' ? c.decode : c); };
  const ct = (cl, v) => { const t = E.termBy[cl + '|' + v]; return t ? [t.nciCode, 'CDISC CT', D.ct.version] : ['', '', '']; };

  // ---- selected BCs
  const selected = [];
  M.activities.forEach(x => {
    x.bcIds.forEach(id => { const bc = M.bcById[id], s = sel[id] || {};
      const sd = s.sdtm && D.sdtm[s.sdtm] ? s.sdtm : null, cr = s.crf && D.crf[s.crf] ? s.crf : null;
      selected.push({ act: x.a, bc, s: sd, c: cr });
      if (!sd) rep('bc_without_sdtm_specialization', { activity: x.a.name, bc: bc.name, bcCode: bc.code.standardCode.code });
      if (!cr) rep('bc_without_crf_specialization', { activity: x.a.name, bc: bc.name, bcCode: bc.code.standardCode.code, sdtmSpecialization: sd });
      if (s.sdtm && !s.confirmed) rep('selections_not_confirmed', { activity: x.a.name, bc: bc.name, sdtm: s.sdtm, crf: s.crf });
    });
    x.surIds.forEach(id => rep('bc_surrogates_excluded', { activity: x.a.name, surrogate: M.surById[id].name, description: M.surById[id].description || '' }));
  });
  const specIds = []; selected.forEach(x => { if (x.s && !specIds.includes(x.s)) specIds.push(x.s); });
  specIds.forEach(s => { if (/RETIRED/.test(D.sdtm[s].name)) rep('retired_specializations_used', s); });

  // ---- trial design (Flow 3)
  const orgs = {}; (sv.organizations || []).forEach(o => orgs[o.id] = o);
  const sponsorId = (sv.studyIdentifiers || []).find(i => orgs[i.scopeId] && orgs[i.scopeId].type && orgs[i.scopeId].type.code === 'C54149');
  const studyid = sponsorId ? sponsorId.text : M.study.name;
  const TA = [], TE = [], TV = [], TI = [], TS = [];
  const epochs = {}; (design.epochs || []).forEach(e => epochs[e.id] = e);
  const elements = {}; (design.elements || []).forEach(e => elements[e.id] = e);
  const epOrder = (design.epochs || []).map(e => e.id);
  (design.arms || []).forEach(arm => {
    const cells = (design.studyCells || []).filter(c => c.armId === arm.id).sort((a, b) => epOrder.indexOf(a.epochId) - epOrder.indexOf(b.epochId));
    let n = 0;
    cells.forEach(c => (c.elementIds || []).forEach(eid => { n++; const el = elements[eid] || {}, ep = epochs[c.epochId] || {};
      TA.push({ STUDYID: studyid, DOMAIN: 'TA', ARMCD: arm.name, ARM: arm.label || arm.name, TAETORD: n, ETCD: el.name, ELEMENT: el.label || el.name,
        TABRANCH: ep.type && ep.type.code === 'C202487' ? 'Randomized to ' + (arm.label || arm.name) : '', TATRANS: '', EPOCH: ep.name }); }));
  });
  (design.elements || []).forEach(el => { TE.push({ STUDYID: studyid, DOMAIN: 'TE', ETCD: el.name, ELEMENT: el.label || el.name,
    TESTRL: (el.transitionStartRule || {}).text || '', TEENRL: (el.transitionEndRule || {}).text || '', TEDUR: '' });
    rep('trial_design_blank_fields', { domain: 'TE', field: 'TEDUR', element: el.name, reason: 'No element duration in USDM' }); });
  const timingById = {}; (M.tl ? M.tl.timings || [] : []).forEach(t => timingById[t.id] = t);
  const studyDay = t => { const n = parseInt((t.value || '').replace(/\D/g, '') || '0', 10);
    return ({ C201357: -n, C201356: n + 1, C201358: 1 })[t.type.code]; };
  (design.encounters || []).forEach((e, i) => { const t = timingById[e.scheduledAtId];
    TV.push({ STUDYID: studyid, DOMAIN: 'TV', VISITNUM: i + 1, VISIT: e.name, VISITDY: t ? studyDay(t) : '', ARMCD: '',
      TVSTRL: t ? t.valueLabel + (t.windowLabel ? ' (' + t.windowLabel + ')' : '') : '', TVENRL: '' }); });
  const items = {}; (sv.eligibilityCriterionItems || []).forEach(i => items[i.id] = i);
  (design.eligibilityCriteria || []).forEach(c => { const txt = (items[c.criterionItemId] || {}).text || c.text || '';
    TI.push({ STUDYID: studyid, DOMAIN: 'TI', IETESTCD: c.name, IETEST: txt.slice(0, 200), IECAT: sub('IECAT', c.category), IESCAT: '', TIRL: '', TIVERS: sv.versionIdentifier });
    if (txt.length > 200) rep('trial_design_blank_fields', { domain: 'TI', field: 'IETEST', criterion: c.name, reason: 'Text > 200 chars truncated' }); });
  const tsparm = {}; (D.terms.TSPARMCD || []).forEach(t => tsparm[t[1]] = t[2]);
  const ts = (parm, val, cd, src) => { cd = cd || ['', '', ''];
    TS.push({ STUDYID: studyid, DOMAIN: 'TS', TSSEQ: TS.filter(r => r.TSPARMCD === parm).length + 1, TSPARMCD: parm, TSPARM: tsparm[parm] || '',
      TSVAL: String(val).slice(0, 200), TSVALCD: cd[0], TSVCDREF: cd[1], TSVCDVER: cd[2], _usdm: src || '' }); };
  const tsc = (parm, cl, c, src) => { if (!c) return; const v = sub(cl, c); ts(parm, v, ct(cl, v), src); };
  const title = (sv.titles || []).find(t => t.type && t.type.code === 'C207616');
  if (title) ts('TITLE', title.text, null, 'StudyVersion.titles[Official Study Title]');
  if (design.studyPhase) tsc('TPHASE', 'TPHASE', design.studyPhase.standardCode, 'StudyDesign.studyPhase');
  if (design.studyType) tsc('STYPE', 'STYPE', design.studyType, 'StudyDesign.studyType');
  if (design.model) tsc('INTMODEL', 'INTMODEL', design.model, 'StudyDesign.model');
  if (design.blindingSchema) tsc('TBLIND', 'TBLIND', design.blindingSchema.standardCode, 'StudyDesign.blindingSchema');
  const chars = (design.characteristics || []).map(c => c.code);
  ts('RANDOM', chars.includes('C46079') ? 'Y' : 'N', ct('NY', chars.includes('C46079') ? 'Y' : 'N'), 'StudyDesign.characteristics');
  ts('ADAPT', chars.includes('C98704') ? 'Y' : 'N', ct('NY', chars.includes('C98704') ? 'Y' : 'N'), 'StudyDesign.characteristics');
  (design.subTypes || []).forEach(s => tsc('TTYPE', 'TTYPE', s, 'StudyDesign.subTypes'));
  (design.intentTypes || []).forEach(s => tsc('TINDTP', 'TINDTP', s, 'StudyDesign.intentTypes'));
  const pop = design.population || {};
  if (pop.plannedEnrollmentNumber && pop.plannedEnrollmentNumber.value != null) ts('PLANSUB', pop.plannedEnrollmentNumber.value, null, 'StudyDesignPopulation.plannedEnrollmentNumber');
  if (pop.plannedAge) { ts('AGEMIN', 'P' + pop.plannedAge.minValue.value + 'Y', null, 'plannedAge.minValue'); ts('AGEMAX', 'P' + pop.plannedAge.maxValue.value + 'Y', null, 'plannedAge.maxValue'); }
  const sexes = new Set((pop.plannedSex || []).map(c => c.code));
  if (sexes.size) { const sp = sexes.has('C16576') && sexes.has('C20197') ? 'BOTH' : (sexes.has('C16576') ? 'F' : 'M'); ts('SEXPOP', sp, ct('SEXPOP', sp), 'plannedSex'); }
  if (pop.includesHealthySubjects != null) { const v = pop.includesHealthySubjects ? 'Y' : 'N'; ts('HLTSUBJI', v, ct('NY', v), 'includesHealthySubjects'); }
  if ((pop.cohorts || []).length) ts('NCOHORT', pop.cohorts.length, null, 'population.cohorts');
  ts('NARMS', (design.arms || []).length, null, 'StudyDesign.arms');
  const ints = {}; (sv.studyInterventions || []).forEach(i => ints[i.id] = i);
  const prods = {}; (sv.administrableProducts || []).forEach(p => prods[p.id] = p);
  const usdmAssigned = {};
  (design.studyInterventionIds || []).forEach(iid => { const si = ints[iid]; if (!si) return;
    (si.administrations || []).forEach(a => {
      if (a.dose && a.dose.unit) (usdmAssigned.DOSU = usdmAssigned.DOSU || new Set()).add(sub('UNIT', a.dose.unit.standardCode));
      if (a.route) (usdmAssigned.ROUTE = usdmAssigned.ROUTE || new Set()).add(sub('ROUTE', a.route.standardCode));
      if (a.frequency) (usdmAssigned.DOSFRQ = usdmAssigned.DOSFRQ || new Set()).add(sub('FREQ', a.frequency.standardCode));
      const p = prods[a.administrableProductId]; if (p) (usdmAssigned.DOSFRM = usdmAssigned.DOSFRM || new Set()).add(sub('FRM', p.administrableDoseForm.standardCode)); });
    if (si.role && si.role.code === 'C41161') {
      ts('TRT', si.name, null, 'StudyIntervention (Experimental)'); tsc('INTTYPE', 'INTTYPE', si.type, 'StudyIntervention.type');
      (si.administrations || []).forEach(a => { if (a.dose) ts('DOSE', a.dose.value, null, 'Administration ' + a.id); });
      const a0 = (si.administrations || [])[0];
      if (a0) { if (a0.dose && a0.dose.unit) tsc('DOSU', 'UNIT', a0.dose.unit.standardCode, 'Administration.dose.unit');
        if (a0.frequency) tsc('DOSFRQ', 'FREQ', a0.frequency.standardCode, 'Administration.frequency');
        if (a0.route) tsc('ROUTE', 'ROUTE', a0.route.standardCode, 'Administration.route');
        const p = prods[a0.administrableProductId]; if (p) tsc('DOSFRM', 'FRM', p.administrableDoseForm.standardCode, 'AdministrableProduct.administrableDoseForm'); }
    }
    if (si.role && si.role.code === 'C753') ts('COMPTRT', si.label || si.name, null, 'StudyIntervention (Placebo)');
  });
  if ((design.arms || []).some(a => a.type && a.type.code === 'C174268')) ts('TCNTRL', 'PLACEBO', ct('TCNTRL', 'PLACEBO'), 'StudyArm.type');
  (design.objectives || []).forEach(o => { const p = { C85826: 'OBJPRIM', C85827: 'OBJSEC', C163559: 'OBJEXP' }[o.level && o.level.code]; if (p) ts(p, o.text, null, 'Objective ' + o.id);
    (o.endpoints || []).forEach(e => { const q = { C94496: 'OUTMSPRI', C139173: 'OUTMSSEC', C170559: 'OUTMSEXP' }[e.level && e.level.code]; if (q) ts(q, e.text, null, 'Endpoint ' + e.id); }); });
  (sv.studyIdentifiers || []).forEach(i => { const o = orgs[i.scopeId]; if (!o || !o.type) return;
    if (o.type.code === 'C93453') ts('REGID', i.text, null, 'StudyIdentifier (registry)'); if (o.type.code === 'C54149') ts('SPONSOR', o.name, null, 'Organization (sponsor)'); });
  const dur = M.tl && M.tl.plannedDuration; if (dur && dur.quantity) ts('LENGTH', 'P' + dur.quantity.value + 'D', null, 'ScheduleTimeline.plannedDuration');
  (design.therapeuticAreas || []).forEach(t => ts('THERAREA', t.decode, null, 'StudyDesign.therapeuticAreas'));
  (design.indications || []).forEach(i => ts('INDIC', i.name, null, 'StudyDesign.indications'));
  const TS_EXPECTED = ['ADDON', 'AGEMAX', 'AGEMIN', 'LENGTH', 'PLANSUB', 'RANDOM', 'SEXPOP', 'STOPRULE', 'TBLIND', 'TCNTRL', 'TDIGRP', 'TINDTP', 'TITLE', 'TPHASE', 'TTYPE',
    'CURTRT', 'OBJPRIM', 'OBJSEC', 'SPONSOR', 'COMPTRT', 'INDIC', 'TRT', 'RANDQT', 'STRATFCT', 'REGID', 'OUTMSPRI', 'OUTMSSEC', 'PCLAS', 'FCNTRY', 'ADAPT', 'DCUTDTC',
    'DCUTDESC', 'INTMODEL', 'NARMS', 'STYPE', 'INTTYPE', 'SSTDTC', 'SENDTC', 'ACTSUB', 'HLTSUBJI', 'SDMDUR', 'CRMDUR', 'EXTTIND', 'PDPSTIND', 'PDSTIND', 'PIPIND',
    'RDIND', 'ONGOSIND', 'THERAREA', 'DOSE', 'DOSU', 'DOSFRQ', 'ROUTE', 'NCOHORT'];
  const have = new Set(TS.map(r => r.TSPARMCD));
  TS_EXPECTED.forEach(p => { if (!have.has(p)) rep('ts_parameters_not_derivable_from_usdm', { TSPARMCD: p, TSPARM: tsparm[p] || '' }); });
  const td = { TA, TE, TV, TI, TS };

  // ---- SDTM define (Flow 2)
  const domains = []; specIds.forEach(s => { const d = D.sdtm[s].d; if (!domains.includes(d)) domains.push(d); });
  const allDomains = domains.concat(TDM.filter(d => !domains.includes(d)));
  const hdrCl = new Set(); Object.values(this.sdtmRows).forEach(rs => rs.forEach(r => r.codelist_submission_value && hdrCl.add(r.codelist_submission_value)));
  const whereOf = spec => this.sdtmRows[spec].filter(r => r.comparator === 'EQ' && r.assigned_value && (r.mandatory_variable === 'Y' || !opts.mandatoryOnly))
    .map(r => `${r.sdtm_variable} EQ "${r.assigned_value}"`).join(' AND ');
  const demand = new Map();
  const want = (cl, values, by, full, specFull) => { if (!demand.has(cl)) demand.set(cl, { terms: [], full: false, unconstrained: [], by: [] });
    const d = demand.get(cl); d.full = d.full || !!specFull; values.forEach(v => { if (v && !d.terms.includes(v)) d.terms.push(v); });
    if (full) d.unconstrained.push(by); d.by.push(by); return d; };
  const datasets = [], variables = [], valueLevel = [];
  allDomains.forEach(dom => {
    const md = D.datasets[dom]; if (!md) { rep('domain_not_in_master_standard', dom); return; }
    const domSpecs = specIds.filter(s => D.sdtm[s].d === dom);
    datasets.push({ internalId: null, dataset: dom, label: md.label, class: md.class, structure: md.structure, keyVariables: md.keys, repeating: md.repeating,
      referenceData: md.ref, customAttribute: prov({ sourceSpecId: D.std.specId, sourceInternalId: md.id, specializations: domSpecs }) });
    const rowsByVar = new Map();
    domSpecs.forEach(s => this.sdtmRows[s].forEach(r => { if (r.mandatory_variable === 'Y' || !opts.mandatoryOnly) {
      if (!rowsByVar.has(r.sdtm_variable)) rowsByVar.set(r.sdtm_variable, []); rowsByVar.get(r.sdtm_variable).push([s, r]); } }));
    const mvars = this.mVar[dom] || {};
    const shell = Object.values(mvars).filter(v => v.core === 'Required' || v.core === 'Expected').map(v => v.variable);
    const inScope = [...new Set([...shell, ...rowsByVar.keys()])];
    inScope.forEach(vn => {
      const mv = mvars[vn];
      if (!mv) { const rs = rowsByVar.get(vn) || []; rep('specialization_variable_not_in_master', { domain: dom, variable: vn, specializations: [...new Set(rs.map(x => x[0]))] }); return; }
      const rs = rowsByVar.get(vn) || [];
      const v = { internalId: null, order: mv.order, dataset: dom, variable: vn, label: mv.label, dataType: mv.dataType, length: mv.length, core: mv.core,
        codelist: null, origin: mv.origin, role: mv.role,
        customAttribute: prov({ sourceSpecId: D.std.specId, sourceInternalId: mv.internalId, inclusion: shell.includes(vn) ? 'domain shell (' + mv.core + ')' : 'specialization',
          specializations: [...new Set(rs.map(x => x[0]))].sort() }) };
      const groups = new Map();
      rs.forEach(([s, r]) => { if (!r.codelist_submission_value) return; if (!groups.has(r.codelist_submission_value)) groups.set(r.codelist_submission_value, [[], false]);
        const g = groups.get(r.codelist_submission_value);
        if (r.assigned_value) g[0].push(r.assigned_value); else if (r.value_list) g[0].push(...r.value_list.split(';')); else g[1] = true; });
      if (!groups.size && mv.codelist) groups.set(mv.codelist, [[], true]);
      const sfx = vn.startsWith(dom) ? vn.slice(dom.length) : vn;
      for (const [cl, g] of groups) {
        let vals = g[0], unconstrained = g[1];
        if ((dom === 'EC' || dom === 'EX') && usdmAssigned[sfx]) { vals = [...usdmAssigned[sfx]].sort(); unconstrained = false; }
        if (TDM.includes(dom)) { vals = [...new Set(td[dom].map(r => r[vn]).filter(x => x !== '' && x != null).map(String))].sort(); unconstrained = !vals.length; }
        if (DICTIONARIES.has(cl) || (mv.codelist === cl && !D.codelists[cl] && !hdrCl.has(cl))) { rep('external_dictionaries', { variable: dom + '.' + vn, dictionary: cl }); continue; }
        want(cl, vals, dom + '.' + vn, unconstrained, unconstrained && rs.length > 0 && !TDM.includes(dom));
      }
      v.codelist = groups.size ? (groups.has(mv.codelist) ? mv.codelist : (groups.size === 1 ? [...groups.keys()][0] : null)) : null;
      if (groups.size > 1) v.customAttribute.note = 'codelists differ by specialization (' + [...groups.keys()].join(', ') + '); carried at value level';
      if (opts.vlm) rs.forEach(([s, r]) => {
        if (r.vlm_target !== 'Y') return; const wc = whereOf(s); if (!wc) return;
        let vcl = r.codelist_submission_value || null;
        if (vcl && !(r.assigned_value || r.value_list)) want(vcl, [], `${dom}.${vn} [${s}]`, true, true);
        if (r.codelist_submission_value && (r.assigned_value || r.value_list)) {
          vcl = `${dom}_${s}_${r.codelist_submission_value}`;
          const d = want(vcl, r.assigned_value ? [r.assigned_value] : r.value_list.split(';'), `${dom}.${vn} [${s}]`); d.parent = r.codelist_submission_value; }
        valueLevel.push({ internalId: null, order: String(valueLevel.length + 1), dataset: dom, variable: vn, whereClause: wc, label: D.sdtm[s].name,
          dataType: mapType(r.data_type) || mv.dataType, length: String(r.length).split('.')[0] || mv.length, significantDigits: String(r.significant_digits).split('.')[0] || null,
          mandatory: r.mandatory_value === 'Y' ? 'Yes' : 'No', assignedValue: r.assigned_value || null, codelist: vcl, origin: r.origin_type || null, source: r.origin_source || null,
          customAttribute: prov({ bcId: D.sdtm[s].bc, specialization: s, decId: r.dec_id || null }) });
      });
      variables.push(v);
    });
  });
  const shellRole = u => { const [dv] = u.split(' '); const [d, vn] = dv.split('.'); return ((this.mVar[d] || {})[vn] || {}).role; };
  const codelists = [], terms = [];
  for (const [cl, d] of demand) {
    const parent = d.parent || cl, mc = D.codelists[parent];
    if (!mc) { rep('codelist_not_in_terminology', { codelist: cl, usedBy: d.by }); continue; }
    let rule, chosen = [];
    const allTerms = (D.terms[parent] || []).map(t => E.termBy[parent + '|' + t[1]]);
    if (d.terms.length && !d.full) {
      rule = 'assigned/value list';
      if (d.unconstrained.length && cl === parent) rep('codelist_unconstrained_usage_limited_to_resolved_terms', { codelist: cl, terms: d.terms.length, masterTerms: mc.n, unconstrainedVariables: d.unconstrained });
      d.terms.forEach(val => { const t = E.termBy[parent + '|' + val];
        if (t) chosen.push([t, false]);
        else if (mc.ext === 'Yes') { chosen.push([{ internalId: null, term: val, decodedValue: val, nciCode: null }, true]); rep('sponsor_extended_terms', { codelist: cl, term: val }); }
        else rep('term_not_in_nonextensible_codelist', { codelist: cl, term: val }); });
    } else if (d.full || mc.ext === 'No' || !d.unconstrained.every(u => shellRole(u) === 'Record Qualifier')) {
      rule = 'full codelist'; chosen = allTerms.map(t => [t, false]);
      if (mc.partial) rep('embedded_ct_subset_warning', { codelist: cl, note: 'Full codelist requested but demo embeds only referenced terms', masterTerms: mc.n });
      rep('full_codelists_included', { codelist: cl, terms: mc.n, usedBy: d.unconstrained });
    } else {
      rule = 'deferred - to be populated (lab/sponsor-specific)';
      rep('codelists_deferred_to_be_populated', { codelist: cl, masterTerms: mc.n, usedBy: d.unconstrained, reason: 'Extensible codelist referenced only by domain-shell Record Qualifier variables' });
    }
    codelists.push({ internalId: null, id: cl, name: cl !== parent ? `${mc.name} (${cl})` : mc.name, nciCode: mc.nci, dataType: mc.type, extensible: mc.ext,
      customAttribute: prov({ sourceSpecId: D.ct.specId, sourceInternalId: mc.id, parentCodelist: parent, subsetRule: rule, usedBy: d.by }) });
    chosen.forEach(([t, ext], i) => terms.push({ internalId: null, order: String(i + 1), codelist: cl, term: t.term, decodedValue: t.decodedValue, nciCode: t.nciCode,
      customAttribute: prov({ sourceSpecId: D.ct.specId, sourceInternalId: t.internalId, extended: ext }) }));
  }
  const define = { standard: { name: studyid + ' SDTM', baseName: D.std.name, baseVersion: D.std.version, terminology: D.ct.name + ' ' + D.ct.version,
    customAttribute: prov({ sourceStandardSpecId: D.std.specId, sourceTerminologySpecId: D.ct.specId, options: opts }) }, datasets, variables, value_level: valueLevel, codelists, terms };

  // ---- CRF form spec (Flow 1)
  const REPEATING = new Set(['AE', 'CM', 'MH']);
  const encs = M.design.encounters || [];
  const events = encs.map((e, i) => ({ Order: i + 1, ID: e.name, Name: e.label || e.name, Type: 'Scheduled', Mandatory: '', Repeating: 'No', DeveloperNotes: '' }));
  const forms = [], questions = [], soa = [], crfCls = new Map(), crfTerms = [], actForms = {};
  const emitCosmos = (act, formId, sectionPrefix, { bc, s, c }, orderRef) => {
    const crfSdtm = D.crf[c].sdtm, cross = !!(s && crfSdtm && crfSdtm !== s);
    const overrides = [], review = [];
    this.crfItems[c].forEach(r0 => {
      orderRef.n++; const rc = this.reconcileItem(s, c, r0); const r = rc.r, note = rc.note, base = rc.base;
      overrides.push(...rc.overrides); if (rc.review) review.push(r.crf_item);
      let cl = '';
      if (r.value_list || r.prepopulated_term) {
        cl = `${D.crf[c].d}_${base}_${r.codelist_submission_value || r.variable_name}`;
        if (!crfCls.has(cl)) {
          crfCls.set(cl, { ID: cl, Name: `${r.prompt || r.question_text || r.variable_name} (${base})`, DataType: 'text', Terminology: r.codelist_submission_value || '', Source: 'COSMoS' });
          const vals = r.value_list ? r.value_list.split(';') : [r.prepopulated_term];
          const disp = r.value_list_display ? r.value_list_display.split(';') : vals.map(() => '');
          vals.forEach((val, j) => { const t = E.termBy[r.codelist_submission_value + '|' + val];
            crfTerms.push({ Codelist: cl, Order: j + 1, Term: val, DecodedValue: disp[j] || (t ? t.decodedValue : val), NCICode: t ? t.nciCode : '' }); });
        }
      }
      questions.push({ Form: formId, Section: sectionPrefix + c, Order: orderRef.n, ID: r.crf_item, SourceVariableName: r.variable_name, QuestionText: r.question_text, Prompt: r.prompt,
        Description: r.dec_id, DataType: r.data_type, Length: r.length, Digits: r.significant_digits, Mandatory: r.mandatory_variable === 'Y' ? 'Yes' : 'No', Codelist: cl,
        DefaultValue: r.prepopulated_term, Hidden: r.display_hidden === 'Y' ? 'Yes' : 'No', ControlType: r.selection_type,
        SDTMTarget: r.sdtm_target_variables.split(';').filter(Boolean).map(x => D.crf[c].d + '.' + x).join(';'), MappingInstructions: r.sdtm_annotation,
        Core: '', CompletionInstructions: '', ImplementationNotes: '', DeveloperNotes: note, Source: 'COSMoS', BC: bc.name, CRFSpecialization: c, SDTMSpecialization: s || '' });
    });
    if (cross) rep('crf_specialization_user_selected_cross_match', { activity: act.name, bc: bc.name, sdtmSpecialization: s, crfSpecialization: c, crfNativeSdtmSpecialization: crfSdtm, overrides, itemsToReview: review });
  };
  const formSource = opts.formSource || {};
  M.activities.forEach(x => {
    const act = x.a, selAll = selected.filter(y => y.act.id === act.id), selA = selAll.filter(y => y.c);
    const fsrc = formSource[act.id] || '', libForm = fsrc.startsWith('lib:') && this.lib ? this.lib.formById[fsrc.slice(4)] : null;
    if (libForm) {   // ---- tier 1: sponsor form library
      const fid = libForm.id; actForms[act.id] = fid;
      forms.push({ Order: forms.length + 1, ID: fid, Name: libForm.name || fid, Description: libForm.description || '', Class: '', Repeating: libForm.isRepeating ? 'Yes' : 'No',
        Condition: '', SourceDatasetName: '', SDTMTargetDomains: '', DeveloperNotes: `Library form (${this.lib.name}) for USDM activity ${act.name}`, Source: 'Library' });
      const codes = new Set(selAll.map(y => this.topicCode(y.s)).filter(Boolean));
      const covered = new Set(); const orderRef = { n: 0 };
      this.lib.questionsByForm[fid].forEach(q => {
        orderRef.n++; const toks = this.qTokens(q), hit = selAll.filter(y => { const tc = this.topicCode(y.s); return tc && toks.has(tc); });
        hit.forEach(y => covered.add(y.bc.id));
        const other = [...new Set([...this.qTestCodes(q), ...[...toks].filter(t => this.allTopicCodes.has(t))])].filter(t => !codes.has(t));
        const cl = q.codelist || '';
        if (cl && !crfCls.has(cl) && this.lib.codelistById[cl]) {
          const lc = this.lib.codelistById[cl]; crfCls.set(cl, { ID: cl, Name: lc.name || cl, DataType: lc.dataType || 'text', Terminology: lc.recommendedCodelist || '', Source: 'Library' });
          (this.lib.termsByCl[cl] || []).forEach(t => crfTerms.push({ Codelist: cl, Order: t.order, Term: t.term, DecodedValue: t.recommendedTerm || t.term, NCICode: '' }));
        }
        questions.push({ Form: fid, Section: q.section || '', Order: orderRef.n, ID: q.id, SourceVariableName: q.id, QuestionText: q.questionText || '', Prompt: '',
          Description: q.description || '', DataType: q.type || '', Length: q.length || '', Digits: q.digits || '', Mandatory: q.isMandatory ? 'Yes' : 'No', Codelist: cl,
          DefaultValue: '', Hidden: 'No', ControlType: '', SDTMTarget: q.sdtmTarget || '', MappingInstructions: '', Core: '', CompletionInstructions: '', ImplementationNotes: '',
          DeveloperNotes: [q.developerNotes, other.length && !hit.length ? `Review: test ${other.join(', ')} not in USDM activity ${act.name} - remove if not collected` : ''].filter(Boolean).join(' | '),
          Source: 'Library', BC: hit.map(y => y.bc.name).join('; '), CRFSpecialization: '', SDTMSpecialization: hit.map(y => y.s).join('; ') });
        if (other.length && !hit.length) rep('library_questions_not_required_by_usdm', { activity: act.name, form: fid, question: q.id, tests: other });
      });
      selAll.filter(y => !covered.has(y.bc.id)).forEach(y => {
        if (y.c) { emitCosmos(act, fid, 'COSMoS:', y, orderRef); rep('bc_not_in_library_form_cosmos_fallback', { activity: act.name, form: fid, bc: y.bc.name, crfSpecialization: y.c }); }
        else rep('bc_not_in_library_form_no_fallback', { activity: act.name, form: fid, bc: y.bc.name });
      });
      rep('library_forms_used', { activity: act.name, form: fid, library: this.lib.name, bcsCovered: covered.size, bcs: selAll.length });
      return;
    }
    if (!selA.length) return;   // ---- tier 3: COSMoS CRF specializations written directly
    const doms = [...new Set(selA.map(y => D.crf[y.c].d))].sort();
    actForms[act.id] = act.name;
    forms.push({ Order: forms.length + 1, ID: act.name, Name: act.label || act.name, Description: '', Class: '', Repeating: doms.some(d => REPEATING.has(d)) ? 'Yes' : 'No',
      Condition: '', SourceDatasetName: doms.join(','), SDTMTargetDomains: doms.join(','), DeveloperNotes: '', Source: 'COSMoS' });
    const orderRef = { n: 0 };
    selA.forEach(y => emitCosmos(act, act.name, '', y, orderRef));
  });
  M.sais.forEach(sai => { const enc = M.encById[sai.encounterId]; if (!enc) return; let o = 0;
    (sai.activityIds || []).forEach(aid => { if (actForms[aid]) soa.push({ Order: ++o, Event: enc.name, Form: actForms[aid], Mandatory: 'Yes' }); }); });
  const crf = { events, forms, scheduleOfActivities: soa, questions, codelists: [...crfCls.values()], terms: crfTerms };

  // ---- extended USDM (persist selections + hidden P21 links)
  const ext = JSON.parse(JSON.stringify(M.u)); const xsv = ext.study.versions[0];
  let n = 0; JSON.stringify(ext).replace(/"ExtensionAttribute_(\d+)"/g, (m, k) => { n = Math.max(n, +k); return m; });
  const xa = (url, val) => Object.assign({ id: 'ExtensionAttribute_' + (++n), url, instanceType: 'ExtensionAttribute', extensionAttributes: [] }, val);
  xsv.extensionAttributes = (xsv.extensionAttributes || []).filter(e => !e.url.startsWith(P21)).concat([xa(P21 + '/study-link', { extensionAttributes: [
    xa(P21 + '/sdtmStandard', { valueString: `${D.std.specId}|${D.std.name} ${D.std.version}` }),
    xa(P21 + '/terminology', { valueString: `${D.ct.specId}|${D.ct.name} ${D.ct.version}` }),
    xa(P21 + '/generatedAt', { valueString: now })] })]);
  const xd = xsv.studyDesigns[0];
  (xd.activities || []).forEach(a => { a.extensionAttributes = (a.extensionAttributes || []).filter(e => e.url !== P21 + '/form-source');
    const f = formSource[a.id]; if (f && f.startsWith('lib:') && this.lib) a.extensionAttributes.push(xa(P21 + '/form-source', { valueString: f })); });
  (xsv.biomedicalConcepts || []).forEach(bc => {
    const s = sel[bc.id]; bc.extensionAttributes = (bc.extensionAttributes || []).filter(e => e.url !== SD_URL && e.url !== CRF_URL && !e.url.startsWith(P21));
    if (!s || !s.sdtm || !D.sdtm[s.sdtm]) return;
    bc.extensionAttributes.push(xa(SD_URL, { valueString: '/mdr/specializations/sdtm/datasetspecializations/' + s.sdtm }));
    if (s.crf) bc.extensionAttributes.push(xa(CRF_URL, { valueString: '/mdr/specializations/crf/specializations/' + s.crf }));
    const dom = D.sdtm[s.sdtm].d, links = [];
    if (D.datasets[dom]) links.push(xa(P21 + '/dataset', { valueString: `${D.datasets[dom].id}|${dom}` }));
    const topic = this.sdtmRows[s.sdtm].find(r => r.role === 'Topic');
    if (topic && (this.mVar[dom] || {})[topic.sdtm_variable]) {
      links.push(xa(P21 + '/topicVariable', { valueString: `${this.mVar[dom][topic.sdtm_variable].internalId}|${dom}.${topic.sdtm_variable}` }));
      const t = E.termBy[topic.codelist_submission_value + '|' + topic.assigned_value];
      if (t) links.push(xa(P21 + '/topicTerm', { valueString: `${t.internalId}|${t.codelist}|${t.term}|${t.nciCode}` }));
    }
    const wc = whereOf(s.sdtm); if (wc) links.push(xa(P21 + '/whereClause', { valueString: wc }));
    bc.extensionAttributes.push(xa(P21 + '/sdtm-link', { extensionAttributes: links }));
  });

  const summary = { bcs: selected.length, sdtmSpecializations: specIds.length, domains, datasets: datasets.length, variables: variables.length, vlmRows: valueLevel.length,
    codelists: codelists.length, terms: terms.length, forms: forms.length, questions: questions.length, crfCodelists: crfCls.size, soaRows: soa.length,
    TS: TS.length, crossMatched: (report.crf_specialization_user_selected_cross_match || []).length,
    bcWithoutCrf: (report.bc_without_crf_specialization || []).length, surrogates: (report.bc_surrogates_excluded || []).length };
  return { define, crf, td, report, summary, extended: ext, studyid };
};

/* ---------------------------------------------------------------- minimal XLSX writer (no deps) */
const CRC = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = b => { let c = 0xFFFFFFFF; for (let i = 0; i < b.length; i++) c = CRC[(c ^ b[i]) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
function zipStore(files) { // files: [{name, data:Uint8Array}]
  const enc = new TextEncoder(), parts = [], central = []; let off = 0;
  files.forEach(f => { const nm = enc.encode(f.name), crc = crc32(f.data), sz = f.data.length;
    const h = new DataView(new ArrayBuffer(30)); h.setUint32(0, 0x04034b50, true); h.setUint16(4, 20, true); h.setUint16(8, 0, true);
    h.setUint32(14, crc, true); h.setUint32(18, sz, true); h.setUint32(22, sz, true); h.setUint16(26, nm.length, true);
    parts.push(new Uint8Array(h.buffer), nm, f.data);
    const c = new DataView(new ArrayBuffer(46)); c.setUint32(0, 0x02014b50, true); c.setUint16(4, 20, true); c.setUint16(6, 20, true);
    c.setUint32(16, crc, true); c.setUint32(20, sz, true); c.setUint32(24, sz, true); c.setUint16(28, nm.length, true); c.setUint32(42, off, true);
    central.push(new Uint8Array(c.buffer), nm); off += 30 + nm.length + sz; });
  const cs = central.reduce((a, b) => a + b.length, 0);
  const e = new DataView(new ArrayBuffer(22)); e.setUint32(0, 0x06054b50, true); e.setUint16(8, files.length, true); e.setUint16(10, files.length, true);
  e.setUint32(12, cs, true); e.setUint32(16, off, true);
  const all = [...parts, ...central, new Uint8Array(e.buffer)], out = new Uint8Array(all.reduce((a, b) => a + b.length, 0)); let p = 0;
  all.forEach(a => { out.set(a, p); p += a.length; }); return out;
}
const xesc = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '');
const colName = i => { let s = ''; i++; while (i) { const m = (i - 1) % 26; s = String.fromCharCode(65 + m) + s; i = Math.floor((i - 1) / 26); } return s; };
function buildXlsx(sheets) { // sheets: [{name, header:[...], rows:[[...]]}]
  const enc = new TextEncoder(), files = [];
  const add = (n, s) => files.push({ name: n, data: enc.encode(s) });
  add('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' +
    sheets.map((s, i) => `<Override PartName="/xl/worksheets/sheet${i + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`).join('') + '</Types>');
  add('_rels/.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>');
  add('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
    sheets.map((s, i) => `<sheet name="${xesc(s.name.slice(0, 31))}" sheetId="${i + 1}" r:id="rId${i + 1}"/>`).join('') + '</sheets></workbook>');
  add('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
    sheets.map((s, i) => `<Relationship Id="rId${i + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${i + 1}.xml"/>`).join('') +
    `<Relationship Id="rId${sheets.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>`);
  add('xl/styles.xml', '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="2"><font><sz val="10"/><name val="Arial"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Arial"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F3864"/></patternFill></fill></fills><borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs><cellXfs count="2"><xf fontId="0" fillId="0"/><xf fontId="1" fillId="2" applyFont="1" applyFill="1"/></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>');
  sheets.forEach((s, i) => {
    const rows = [s.header, ...s.rows];
    const widths = s.header.map((h, c) => Math.min(60, Math.max(8, String(h).length + 2, ...rows.slice(1, 200).map(r => String(r[c] == null ? '' : r[c]).length + 2))));
    let x = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>' +
      widths.map((w, c) => `<col min="${c + 1}" max="${c + 1}" width="${w}" customWidth="1"/>`).join('') + '</cols><sheetData>';
    rows.forEach((r, ri) => { x += `<row r="${ri + 1}">`;
      r.forEach((v, ci) => { if (v == null || v === '') return; const ref = colName(ci) + (ri + 1), st = ri === 0 ? ' s="1"' : '';
        if (typeof v === 'number' && isFinite(v)) x += `<c r="${ref}"${st}><v>${v}</v></c>`;
        else x += `<c r="${ref}"${st} t="inlineStr"><is><t xml:space="preserve">${xesc(typeof v === 'object' ? JSON.stringify(v) : v)}</t></is></c>`; });
      x += '</row>'; });
    x += `</sheetData>${rows.length > 1 ? `<autoFilter ref="A1:${colName(s.header.length - 1)}${rows.length}"/>` : ''}</worksheet>`;
    add(`xl/worksheets/sheet${i + 1}.xml`, x);
  });
  return zipStore(files);
}
const objSheet = (name, objs, cols) => { cols = cols || (objs.length ? Object.keys(objs[0]) : ['(empty)']);
  return { name, header: cols, rows: objs.map(o => cols.map(c => o[c])) }; };
const ca = (o, k) => (o.customAttribute || {})[k];
const reportSheet = (report) => { const rows = []; for (const k in report) report[k].forEach(v => rows.push([k, typeof v === 'object' ? JSON.stringify(v) : v])); return { name: 'Generation report', header: ['Finding type', 'Detail'], rows }; };
Engine.prototype.defineWorkbook = function (G) {
  const d = G.define;
  return buildXlsx([
    { name: 'Datasets', header: ['Dataset', 'Label', 'Class', 'Structure', 'Key Variables', 'Repeating', 'Reference Data', 'Source internalId', 'Specializations'],
      rows: d.datasets.map(x => [x.dataset, x.label, x.class, x.structure, x.keyVariables, x.repeating, x.referenceData, ca(x, 'sourceInternalId'), (ca(x, 'specializations') || []).join(', ')]) },
    { name: 'Variables', header: ['Order', 'Dataset', 'Variable', 'Label', 'Data Type', 'Length', 'Core', 'Codelist', 'Origin', 'Role', 'Inclusion', 'Source internalId', 'Specializations'],
      rows: d.variables.map(v => [v.order ? +v.order : '', v.dataset, v.variable, v.label, v.dataType, v.length, v.core, v.codelist, v.origin, v.role, ca(v, 'inclusion'), ca(v, 'sourceInternalId'), (ca(v, 'specializations') || []).join(', ')]) },
    { name: 'ValueLevel', header: ['Order', 'Dataset', 'Variable', 'Where Clause', 'Label', 'Data Type', 'Length', 'Significant Digits', 'Mandatory', 'Assigned Value', 'Codelist', 'Origin', 'Source', 'BC', 'Specialization'],
      rows: d.value_level.map(v => [+v.order, v.dataset, v.variable, v.whereClause, v.label, v.dataType, v.length, v.significantDigits, v.mandatory, v.assignedValue, v.codelist, v.origin, v.source, ca(v, 'bcId'), ca(v, 'specialization')]) },
    { name: 'Codelists', header: ['ID', 'Name', 'NCI Code', 'Data Type', 'Extensible', 'Parent Codelist', 'Subset Rule', 'Source internalId', 'Used By'],
      rows: d.codelists.map(c => [c.id, c.name, c.nciCode, c.dataType, c.extensible, ca(c, 'parentCodelist'), ca(c, 'subsetRule'), ca(c, 'sourceInternalId'), (ca(c, 'usedBy') || []).join(', ')]) },
    { name: 'Terms', header: ['Codelist', 'Order', 'Term', 'Decoded Value', 'NCI Code', 'Sponsor Extended', 'Source internalId'],
      rows: d.terms.map(t => [t.codelist, +t.order, t.term, t.decodedValue, t.nciCode, ca(t, 'extended') ? 'Yes' : 'No', ca(t, 'sourceInternalId')]) },
    reportSheet(G.report)]);
};
Engine.prototype.formWorkbook = function (G) {
  const c = G.crf;
  return buildXlsx([objSheet('Events', c.events), objSheet('Forms', c.forms), objSheet('ScheduleOfActivities', c.scheduleOfActivities),
    objSheet('Questions', c.questions), objSheet('Codelists', c.codelists), objSheet('Terms', c.terms), reportSheet(G.report)]);
};
Engine.prototype.tsWorkbook = function (G) {
  return buildXlsx([objSheet('TS', G.td.TS, ['STUDYID', 'DOMAIN', 'TSSEQ', 'TSPARMCD', 'TSPARM', 'TSVAL', 'TSVALCD', 'TSVCDREF', 'TSVCDVER', '_usdm']),
    objSheet('TA', G.td.TA), objSheet('TE', G.td.TE), objSheet('TV', G.td.TV), objSheet('TI', G.td.TI),
    { name: 'TS gaps', header: ['TSPARMCD', 'TSPARM'], rows: (G.report.ts_parameters_not_derivable_from_usdm || []).map(x => [x.TSPARMCD, x.TSPARM]) }]);
};
Engine.SD_URL = SD_URL; Engine.CRF_URL = CRF_URL;
root.Engine = Engine;
if (typeof module !== 'undefined') module.exports = Engine;
})(typeof window !== 'undefined' ? window : globalThis);
