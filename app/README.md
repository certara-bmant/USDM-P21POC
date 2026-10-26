# USDM → P21 Workbench (local POC)

Runs on your PC: `python usdm_p21_app.py` – or double-click `run_workbench.bat` (Windows) / run `./run_workbench.sh` (macOS/Linux; `chmod +x run_workbench.sh` once). Python 3.8+, standard library only.
Opens http://127.0.0.1:8765 (local only).

**Steps:** 1 Load USDM → 2 Standard & terminology (+ optional form library) → 3 Map specializations → 4 Generate & export → 5 Report dashboard (KPIs, coverage charts, findings by severity; Print/PDF).

**P21E connection (step 2):** enter your P21E root URL (e.g. `https://my-company.pinnacle21.com`) and a User API Key
(P21E › Your Profile › API Key › Add Key). The key stays in the local server process; tick *remember* to store it in
`config.json` next to the script (plain text – treat it like a password). Optionally set it via env var `P21_API_KEY`.
Calls used (read-only API): `/api/standards`, `/api/terminologies`, `/api/metadata/forms`, `/api/{standards|terminologies|forms}/:id/export?format=json`.
Exports are cached in `cache/` for 24 h (tick *refresh cache* to re-pull).

**Offline:** with no key, the app lists and loads JSON exports dropped in `p21_exports/` (git-ignored – add your own P21 exports).

**Form source per activity (step 3):** *COSMoS direct* (CRF specializations) or a form from the selected P21 form library.
Library forms are matched to the activity's BCs by test code (`--TESTCD = X` in the SDTM target, or IDs like `X_VSORRES`);
BCs the library form doesn't cover fall back to COSMoS items; library questions for tests not in the activity are flagged.

**Note:** the P21E API is GET-only, so generated artefacts are downloaded (xlsx/json) for import rather than written back.
`data/cosmos_catalogue.json` is the local COSMoS specialization table (98 SDTM / 309 CRF specializations in this POC).
