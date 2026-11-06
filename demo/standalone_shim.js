/* Standalone shim: lets app/static/index.html run as a single offline file.
   Routes the local-server endpoints (/app/*) to embedded data (window.__EMBED = {catalogue, sample, master}) and to
   P21 export JSON files the user loads in the browser. The P21E API itself needs the local app (CORS + API key). */
(function () {
  'use strict';
  const EMB = window.__EMBED;
  const LOADED = { standards: {}, terminologies: {}, forms: {} };   // id -> { meta, data }
  const norm = (h, file) => ({ id: String(h.specId || h.id || file), name: h.name || file, version: String(h.version || ''), type: h.type || '',
    status: h.status || '', publisher: h.publisher || '', file });
  const respond = (o, code) => Promise.resolve(new Response(JSON.stringify(o), { status: code || 200, headers: { 'Content-Type': 'application/json' } }));
  const realFetch = window.fetch ? window.fetch.bind(window) : null;
  const STD_ID = String(EMB.master.std.specId), CT_ID = String(EMB.master.ct.specId);

  /* ---- port of usdm_p21_app.build_master (split so embedded standard/CT can be combined with loaded exports) ---- */
  const VC = ['variable', 'internalId', 'order', 'label', 'dataType', 'length', 'core', 'codelist', 'origin', 'role'];
  function stdParts(std) {
    const cat = EMB.catalogue, stdDoms = new Set((std.datasets || []).map(d => d.dataset));
    const doms = new Set([...Object.values(cat.sdtm).map(v => v.d), ...Object.values(cat.crf).map(v => v.d), 'TA', 'TE', 'TV', 'TI', 'TS'].filter(d => stdDoms.has(d)));
    const datasets = {}; (std.datasets || []).forEach(d => { if (doms.has(d.dataset)) datasets[d.dataset] = { id: d.internalId, label: d.label, class: d.class,
      structure: d.structure, keys: d.keyVariables, repeating: d.repeating, ref: d.referenceData }; });
    const vars = {}; (std.variables || []).forEach(v => (vars[v.dataset] = vars[v.dataset] || []).push(VC.map(c => v[c] == null ? null : v[c])));
    const classes = {}; (std.datasets || []).forEach(d => classes[d.dataset] = d.class);
    const sh = std.standard || {};
    return { std: { specId: sh.specId, name: sh.name, version: sh.version, type: sh.type }, datasets, classes, vars, VC };
  }
  function ctParts(term, sp) {
    const cat = EMB.catalogue, S = cat.SCOLS, C = cat.CCOLS, referenced = {};
    const add = (cl, v) => (referenced[cl] = referenced[cl] || new Set()).add(v);
    const iCL = S.indexOf('codelist_submission_value'), iAV = S.indexOf('assigned_value'), iVL = S.indexOf('value_list');
    const jCL = C.indexOf('codelist_submission_value'), jVL = C.indexOf('value_list'), jPP = C.indexOf('prepopulated_term');
    Object.values(cat.sdtm).forEach(s => s.rows.forEach(r => { if (r[iCL]) (r[iAV] ? [r[iAV]] : r[iVL].split(';')).forEach(x => add(r[iCL], x)); }));
    Object.values(cat.crf).forEach(c => c.items.forEach(i => { if (i[jCL]) (i[jVL] ? i[jVL].split(';') : [i[jPP]]).forEach(x => add(i[jCL], x)); }));
    const used = new Set([...Object.keys(referenced), 'TSPARMCD', 'TSPARM', 'UNIT', 'ROUTE', 'FRM', 'FREQ', 'TPHASE', 'STYPE', 'INTMODEL', 'TBLIND', 'TTYPE', 'TINDTP',
      'INTTYPE', 'SEXPOP', 'NY', 'TCNTRL', 'IECAT', 'EPOCH']);
    Object.keys(sp.datasets).forEach(d => (sp.vars[d] || []).forEach(v => { if (v[7]) used.add(v[7]); }));
    const tby = {}; (term.terms || []).forEach(t => (tby[t.codelist] = tby[t.codelist] || []).push(t));
    const codelists = {}, terms = {};
    (term.codelists || []).forEach(c => {
      if (!used.has(c.id)) return; const all = tby[c.id] || [];
      codelists[c.id] = { id: c.internalId, name: c.name, nci: c.nciCode, ext: c.extensible || 'Yes', type: c.dataType, n: all.length, partial: all.length > 1000 };
      const keep = all.length <= 1000 ? all : all.filter(t => referenced[c.id] && referenced[c.id].has(t.term));
      terms[c.id] = keep.map(t => [t.internalId, t.term, t.decodedValue, t.nciCode]);
    });
    const th = term.terminology || {};
    return { ct: { specId: th.specId, name: th.name, version: th.version }, codelists, terms, ctTotalTerms: (term.terms || []).length };
  }
  function compactForms(fx) {   // port of usdm_p21_app.compact_forms
    const pick = k => Array.isArray(fx[k]) ? fx[k] : [];
    let forms = Array.isArray(fx.forms) ? fx.forms : [];
    if (!forms.length) for (const k in fx) { const v = fx[k]; if (Array.isArray(v) && v.length && v[0] && typeof v[0] === 'object' && 'id' in v[0] && 'isRepeating' in v[0] && !('forms' in v[0]) && !('form' in v[0])) { forms = v; break; } }
    const questions = pick('questions');
    if (!forms.length) forms = [...new Set(questions.map(q => q.form).filter(Boolean))].map(f => ({ id: f, name: f }));
    return { header: (fx.forms && !Array.isArray(fx.forms)) ? fx.forms : {}, forms, events: pick('events'), sections: pick('sections'), questions,
      codelists: pick('codelists'), terms: pick('terms'), units: pick('units') };
  }

  window.fetch = (u, o) => {
    const p = String(u).replace(/^https?:\/\/[^/]+/, '').split('?')[0];
    if (!p.startsWith('/app/')) return realFetch ? realFetch(u, o) : Promise.reject(new Error('fetch unavailable'));
    const body = o && o.body ? JSON.parse(o.body) : {};
    try {
      switch (p) {
        case '/app/catalogue': return respond(EMB.catalogue);
        case '/app/sample': return respond(EMB.sample);
        case '/app/config': return respond({ base_url: '', has_key: false, remember: false, mode: 'offline' });
        case '/app/test': return respond({ ok: false, mode: 'offline', message: 'Standalone demo – run the local app (usdm_p21_app.py) to use the P21E API' });
        case '/app/standards': return respond({ mode: 'offline', items: [Object.assign(norm(EMB.master.std, 'embedded'), { status: 'Final' }), ...Object.values(LOADED.standards).map(x => x.meta)] });
        case '/app/terminologies': return respond({ mode: 'offline', items: [Object.assign(norm(EMB.master.ct, 'embedded'), { type: 'SDTM', status: 'Final' }), ...Object.values(LOADED.terminologies).map(x => x.meta)] });
        case '/app/forms': return respond({ mode: 'offline', items: Object.values(LOADED.forms).map(x => x.meta) });
        case '/app/master': {
          const sid = String(body.standardId), tid = String(body.terminologyId), t0 = Date.now();
          const sp = sid === STD_ID && !LOADED.standards[sid] ? { std: EMB.master.std, datasets: EMB.master.datasets, classes: EMB.master.classes, vars: EMB.master.vars, VC: EMB.master.VC }
            : LOADED.standards[sid] ? stdParts(LOADED.standards[sid].data) : null;
          if (!sp) return respond({ error: `standard ${sid} not loaded` }, 404);
          let cp;
          if (tid === CT_ID && !LOADED.terminologies[tid]) {
            if (sp.std === EMB.master.std) cp = { ct: EMB.master.ct, codelists: EMB.master.codelists, terms: EMB.master.terms, ctTotalTerms: EMB.master.ctTotalTerms };
            else return respond({ error: 'The embedded terminology is pre-cut for the embedded standard – load the terminology export too' }, 400);
          } else if (LOADED.terminologies[tid]) cp = ctParts(LOADED.terminologies[tid].data, sp);
          else return respond({ error: `terminology ${tid} not loaded` }, 404);
          return respond(Object.assign({}, sp, cp, { elapsed: ((Date.now() - t0) / 1000).toFixed(1), mode: 'offline' }));
        }
        case '/app/formlib': { const f = LOADED.forms[String(body.formId)]; return f ? respond(compactForms(f.data)) : respond({ error: 'form spec not loaded' }, 404); }
      }
      return respond({ error: 'not found' }, 404);
    } catch (e) { return respond({ error: e.message }, 500); }
  };

  /* ---- replace the P21E connection card with a P21 export loader ---- */
  function loaderCard() {
    const card = document.getElementById('cf-url') && document.getElementById('cf-url').closest('.card'); if (!card) return;
    card.style.display = 'none';   // keep the original connection inputs in the DOM (the app script reads them) but hide them
    const nc = document.createElement('div'); nc.className = 'card'; card.parentNode.insertBefore(nc, card);
    nc.innerHTML = `<h2>P21 exports <span class="pill warn">standalone demo · offline</span></h2>
      <div class="muted" style="margin-bottom:8px">This single-file demo can't call the P21E API (browser security and API key) – run <code>app/usdm_p21_app.py</code> for that.
        It ships with <b>${EMB.master.std.name} ${EMB.master.std.version}</b> and <b>${EMB.master.ct.name} ${EMB.master.ct.version}</b>. You can add more by loading JSON exports
        (<code>/api/standards/:id/export</code>, <code>/api/terminologies/:id/export</code>, <code>/api/forms/:id/export</code>).</div>
      <label class="btn" style="display:inline-block">Load P21 export file(s)…<input type="file" id="sx-files" accept=".json" multiple style="display:none"></label>
      <span id="sx-msg" class="muted" style="margin-left:10px"></span><div id="sx-list" class="muted" style="margin-top:8px"></div>`;
    document.getElementById('sx-files').onchange = async e => {
      const msgs = [];
      for (const f of e.target.files) {
        try {
          const d = JSON.parse(await f.text());
          if (d.standard) { const m = norm(d.standard, f.name); LOADED.standards[m.id] = { meta: m, data: d }; msgs.push(`standard ${m.name} ${m.version}`); }
          else if (d.terminology) { const m = norm(d.terminology, f.name); LOADED.terminologies[m.id] = { meta: m, data: d }; msgs.push(`terminology ${m.name} ${m.version}`); }
          else if (Array.isArray(d.questions)) { const h = (d.forms && !Array.isArray(d.forms)) ? d.forms : {}; const m = norm(Object.assign({ name: f.name.replace(/\.json$/i, '') }, h), f.name);
            LOADED.forms[m.id] = { meta: m, data: d }; msgs.push(`form spec ${m.name}`); }
          else msgs.push(`${f.name}: not a P21 standard / terminology / form export`);
        } catch (err) { msgs.push(`${f.name}: ${err.message}`); }
      }
      document.getElementById('sx-msg').textContent = 'Loaded: ' + msgs.join(' · ');
      document.getElementById('sx-list').textContent = `${Object.keys(LOADED.standards).length} standard(s), ${Object.keys(LOADED.terminologies).length} terminology(ies), ${Object.keys(LOADED.forms).length} form spec(s) loaded in this session`;
      e.target.value = ''; if (window.refreshLists) window.refreshLists();
    };
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', loaderCard); else loaderCard();
})();
