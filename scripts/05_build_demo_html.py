"""Assemble the self-contained demo HTML: app_template + engine.js + data blob + sample USDM (no extensions)."""
import json, sys
d = sys.argv[1]; out = sys.argv[2]
safe = lambda s: s.replace('</', '<\\/')
t = open(f'{d}/app_template.html').read()
t = t.replace('/*__ENGINE__*/', open(f'{d}/engine.js').read())
t = t.replace('/*__DATA__*/', safe(open(f'{d}/demo_data.json').read()))
t = t.replace('/*__SAMPLE__*/', safe(json.dumps(json.load(open(f'{d}/CTX101-001_USDM_v4_no-extensions.json')), separators=(',', ':'))))
open(out, 'w').write(t); print(out, len(t) // 1024, 'KB')
