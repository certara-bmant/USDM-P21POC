# POC Summary – USDM → P21 study artefact generation

**Author:** Ben Mant · **Date:** 26 October 2026 · **Status:** Proof of concept complete
**Relates to:** Framing Pitch 2 – *USDM Workbench: Downstream P21 Study Artefact Generation*

## 1. Objective

Show, on a realistic study, that a USDM v4 protocol can drive P21 study artefacts by:
1. letting a user link each Biomedical Concept (BC) to a COSMoS SDTM and CRF specialization,
2. **persisting** those choices in the USDM (SoA-Workbench-style extensions, keyed to P21 `internalId`s), and
3. generating a **study SDTM define**, **CRF form spec** and **TS / trial design** by subsetting a P21 master standard and terminology.

## 2. What was built

| Deliverable | Description |
|---|---|
| **Sample USDM – CTX101-001** | Fictional Phase 1 randomised, placebo-controlled SAD study in healthy volunteers: 5 cohorts, 3 epochs, 8 visits, 12 criteria, 24 activities, **83 BCs** (vitals, ECG, haematology, coagulation, chemistry, urinalysis, virology, pregnancy, demography, AE, CM, dosing, disposition) and 6 BC surrogates, plus a Day 1 intensive sub-timeline (dosing, PK, vitals, ECG). Validated against the CDISC USDM 4.0 model and rules. Available with and without extensions. |
| **Local COSMoS specialization table** | 98 SDTM dataset and 309 CRF specializations from the CDISC COSMoS GitHub (packages r9–r18, CRF draft 2026-07-31), flattened as the table P21 would hold. |
| **Batch pipeline (Python)** | Scripts 00–05: build tables, build USDM, generate define/CRF/TDM/report, Excel export, build demo. |
| **Local workbench app** | `app/usdm_p21_app.py` – stdlib Python server + browser UI: load USDM → select standard/CT/form library via the **P21 API** (or offline exports) → map in the **SoA** → generate & export → **report dashboard**. |
| **Single-file demo** | `USDM_P21_Workbench_Demo.html` – same flow with embedded data, no server. |

## 3. Results (CTX101-001, SDTMIG 3.4, SDTM CT 2026-03-27)

| Measure | Result |
|---|---|
| BCs with an SDTM specialization | 82 / 83 (99%) |
| BCs with a CRF specialization | 73 / 83 (63 exact pairs, 10 user-selected cross-matches) |
| Study define | 17 datasets · 192 variables · 274 VLM rows · 87 codelists |
| Study terminology | **521 terms** from 46,883 in the CT release (≈ 98.9% reduction) |
| CRF form spec | 18 forms · 643 questions · 62 visit × form rows |
| Trial design | TA 6 · TE 4 · TV 8 · TI 12 · TS 38 rows (31 of 55 TS parameters derivable) |
| Automatic suggestions vs confirmed selections | 81 / 83 agree using BC code + activity context |
| JS engine vs Python generator | identical counts on the same selections |

## 4. Key design decisions

1. **Persist choices in USDM, not only in P21.** The SoA-Workbench extension URLs are reused for the specialization IDs. A Certara extension holds P21 links stored as **`internalId | natural key`**: `internalId` gives a fast exact lookup, and the natural key lets links be re-resolved after re-imports or version changes.
2. **Select in the SoA, review in a table.** The activity is the context the user needs to choose a specialization. A generic BC such as *Glucose Measurement* means a serum test under *Chemistry* and a urine presence test under *Urinalysis*. Both views share the same selections.
3. **The SDTM specialization is authoritative.** When the user pairs a CRF specialization built for another specimen or scale (e.g. `SODIUMBLD` CRF for `SODIUMSERPL`), form items are reconciled to the SDTM side and the differences are reported.
4. **Codelist cut rules extended beyond the pitch.**
   - Values come from the specializations, from the USDM (dose unit, route, form, frequency) and from the generated trial-design values.
   - The full codelist is used only when a specialization asks for it, when the codelist is closed, or when the variable is not a Record Qualifier.
   - Extensible codelists used only by Record Qualifiers are deferred and flagged. METHOD, for example, drops from 531 terms to "to be populated".
5. **Form library first, COSMoS as the link and the fallback.** Each activity selects a library form, and BCs decide which items are relevant. BCs the library form doesn't cover get COSMoS items appended, and library questions for tests outside the activity are flagged.
6. **Run locally, keep the key on the server.** The Python proxy calls the P21 API so the key never reaches the browser. An offline mode uses exports.

## 5. Findings

**P21 platform**
- The P21E REST API is **read-only** (GET). The pitch's "post JSON artefacts via the API" step needs a write API or an import route. The POC delivers files (xlsx/json) instead.
- The API covers what the selection step needs: list and export standards, terminologies and library form specs.

**COSMoS content**
- **CRF coverage gaps.** Some BCs have CRF specializations for only one specimen (blood vs serum/plasma). Chemistry BCs could be paired only through user-selected cross-matches.
- **Mis-tag:** `UROBILURINPRES` carries the nitrite BC code (C64810), so code-based matching fails. This is worth reporting to CDISC.
- **Not covered:** leukocyte esterase (`LEUKASE`), physical exam, drug screen, HIV antibody and PK sampling have no BC/specialization and are modelled as BC surrogates.
- **Retired disposition specializations** (e.g. PROTCOMP) have been replaced by `DSSTUDYPARTICIPATION` and `DSSTUDYTREATMENT`, which have no CRF specialization yet.
- **No answer lists for urine presence tests:** these specializations don't list allowed result values.

**Terminology / standard**
- The COSMoS RACE specialization references codelist C74457, which is **absent from CT 2026-03-27** (only RACEC exists).
- The P21 SDTMIG 3.4 export has 25 variables with no `order`.
- An SDTM *role* is a useful but imperfect proxy for "values decided by the study/lab". `LBRESSCL` is a Record Qualifier with standard-defined values, so an override list will be needed.

**Tooling**
- The `usdm4` validator's CT-version list stops at 2025-03-28, so rule DDF00155 falsely fails on current CT. All implemented rules pass once that list is updated.

**USDM content – procedure-only activities (key gap, not built)**
- The POC drives everything from `Activity.biomedicalConceptIds`. The sample study is BC-complete, but many real USDMs describe assessments only as `Activity.definedProcedures`: a `Procedure` coded in CPT, SNOMED or NCIt, such as "12-lead ECG" or "Complete blood count", with no BCs attached. Such activities currently show no BCs, so they produce no define content and no form items. They aren't yet reported as a distinct gap either.
- **Potential route:** a curated reference table held in P21 next to the specialization table, for example:

  | procedure_code | code_system | bc_id | default_sdtm_specialization | default_crf_specialization |
  |---|---|---|---|---|
  | 12-lead ECG code | NCIt / CPT | C117783 (QT) | QTAG | QTAG_DENORMALIZED |
  | CBC code | NCIt / CPT | C64848 (HGB) | HGBBLD | HGBBLD_DENORMALIZED |

  On load, procedure-only activities would be expanded into *proposed* BCs, which the user confirms in the SoA. They would then be written back to the USDM as `BiomedicalConcept`s on the activity, so the existing mapping, generation and extension persistence apply unchanged. Procedure codes without a table entry would be reported as gaps.
- **Dependencies:** consistent procedure coding in sponsor USDMs, and ownership and curation of the procedure → BC table (procedure panels vary by sponsor and lab).

## 6. Open questions

1. Is a P21 write/import API planned, or should the generated files target the P21 Excel import templates?
2. Where should the library form ↔ specialization link table live in P21, and who curates it?
3. Should BC surrogates whose test code exists in CT (e.g. `LEUKASE`) be added to the define automatically?
4. Will the full COSMoS catalogue be held in P21 as a table (with version history), and how are new COSMoS releases compared with existing studies?
5. How common are procedure-only activities in the USDMs we'll receive, and is a procedure → BC reference table (owned by the standards team) worth building to cover them?

## 7. Recommended next steps

1. Run the local app against a real P21E environment and a real sponsor form library export, then tune the library matching.
2. Add the CDASH-template tier and an override list for codelist rules.
3. Load the full COSMoS catalogue, add version-aware re-generation (diff of artefacts between COSMoS / CT releases), and add SUPP-- handling.
4. Feed COSMoS gaps and the mis-tag back to CDISC, and library gaps to the standards team.

---
*CTX101-001 is fictional. Outputs are for demonstration only and not validated for regulatory use.*
