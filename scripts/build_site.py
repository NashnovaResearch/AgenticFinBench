"""Build the static showcase from frozen data, without model or network calls."""
import hashlib
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    manifest = json.loads((ROOT / 'data/manifest.json').read_text())
    for name, expected in manifest['files'].items():
        assert hashlib.sha256((ROOT / 'data' / name).read_bytes()).hexdigest() == expected, name
    questions = json.loads((ROOT / 'data/questions.json').read_text())
    rubrics = json.loads((ROOT / 'data/rubrics.json').read_text())
    qmap = {q['id']: q for q in questions}
    cohort = json.loads((ROOT / 'data/cohort230.json').read_text())
    bindings = {q['question_id']: q for q in cohort['questions']}
    assert len(bindings) == 230 and bindings.keys() == qmap.keys()
    for qid, q in qmap.items():
        assert hashlib.sha256(q['question'].encode()).hexdigest() == q['question_sha256'] == bindings[qid]['question_sha256']
        assert q['level'] == bindings[qid]['level']
    assert len(qmap) == len(questions) == len(rubrics) == 230
    assert {r['question_id'] for r in rubrics} == set(qmap)
    out = ROOT / 'public'
    # This directory is generated and ignored; remove stale downloadable questions.
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    shutil.copytree(ROOT / 'site', out, dirs_exist_ok=True)
    (out / 'data/rubrics').mkdir(parents=True, exist_ok=True)
    for r in rubrics:
        qid = r['question_id']
        assert re.fullmatch(r'[a-z0-9-]+', qid)
        assert r['question'] == qmap[qid]['question']
        (out / 'data/rubrics' / f'{qid}.json').write_text(json.dumps(r, ensure_ascii=False))
    for name in manifest['files']:
        shutil.copyfile(ROOT / 'data' / name, out / 'data' / name)
    shutil.copyfile(ROOT / 'data/manifest.json', out / 'data/manifest.json')
    shutil.copyfile(ROOT / 'examples/one-answer.jsonl', out / 'data/one-answer.jsonl')
    assert sum(len(r['positive']) for r in rubrics) == manifest['positive_items']
    assert sum(len(r['negative']) for r in rubrics) == manifest['negative_items']
    assert not [p for p in out.rglob('*') if p.name == '.env' or p.name.startswith('AGENTS')]
    paper = json.loads((out / 'paper-results.json').read_text())
    assert paper['question_count'] == 230
    assert len(paper['models']) == paper['configuration_count'] == 18
    assert sorted(m['rank'] for m in paper['models']) == list(range(1, 19))
    assert len({(m['model'], m['harness']) for m in paper['models']}) == 18
    assert all(m['count'] == 230 and 0 <= m['q'] <= 100 for m in paper['models'])
    sources = json.loads((out / 'paper-sources.json').read_text())
    for name, expected in sources['sources'].items():
        assert hashlib.sha256((ROOT / 'docs/paper-snapshot' / name).read_bytes()).hexdigest() == expected
    for name, expected in sources['figures'].items():
        assert hashlib.sha256((out / 'assets/figures' / name).read_bytes()).hexdigest() == expected
    for line, model in zip((ROOT / 'docs/paper-snapshot/tab_main_rows.tex').read_text().splitlines(), paper['models']):
        fields = [x.strip() for x in line.split(' & ')]
        assert fields[1] == model['model'] + ' / ' + model['harness']
        assert float(re.search(r'[0-9.]+', fields[2])[0]) == model['q']
        assert [float(x) for x in fields[3].split('--')] == model['ci']
        assert float(fields[4]) == model['baseline'] and float(fields[5]) == model['delta']
    overview_rows = [line for line in (ROOT / 'docs/paper-snapshot/tab_main_overview.tex').read_text().splitlines() if re.match(r'^\d+ &', line)]
    assert len(overview_rows) == len(paper['models']) == 18
    for line, model in zip(overview_rows, paper['models']):
        fields = line.split(' & ')
        number = lambda s: float(re.search(r'-?\d+(?:\.\d+)?', s)[0])
        assert int(fields[0]) == model['rank']
        assert fields[1:3] == [model['model'], model['harness']]
        assert number(fields[3]) == model['q']
        assert [float(x) for x in fields[4].split('--')] == model['ci']
        assert number(fields[5]) == model['delta']
        assert int(fields[6].split()[0]) == model['baseline_rank']
        assert number(fields[7]) == model['time_minutes']
        assert number(fields[8]) == model['cost_usd']
        for field, cell, descending in [('q', fields[3], True), ('time_minutes', fields[7], False), ('cost_usd', fields[8], False)]:
            leaders = sorted(paper['models'], key=lambda m: m[field], reverse=descending)[:3]
            assert ('textbf' in cell) == (model == leaders[0])
            assert ('underline' in cell) == (model in leaders[1:])
    audit_rows = (ROOT / 'docs/paper-snapshot/tab_audit_full_rows.tex').read_text().splitlines()
    for line in audit_rows:
        fields = [x.strip() for x in line.split(' & ')]
        model = next(m for m in paper['models'] if m['model'] + ' / ' + m['harness'] == fields[0])
        assert int(fields[1].replace(',', '')) == model['claims']
        assert float(fields[3].split()[0]) == model['response_hallucination']
        assert float(fields[4].split()[0]) == model['claim_hallucination']
    assert len(list((out / 'data/rubrics').glob('*.json'))) == 230
    assert not (out / 'results.json').exists()
    assert sum(m['claims'] for m in paper['models']) == 232698
    # Content-addressed resources keep a new HTML page from using cached old code/data.
    results_bytes = (out / 'paper-results.json').read_bytes()
    results_name = 'paper-results.' + hashlib.sha256(results_bytes).hexdigest()[:16] + '.json'
    (out / results_name).write_bytes(results_bytes)
    app = (out / 'assets/app.js').read_text().replace("readJson('paper-results.json')", f"readJson('{results_name}')")
    app_bytes = app.encode()
    app_name = 'assets/app.' + hashlib.sha256(app_bytes).hexdigest()[:16] + '.js'
    (out / app_name).write_bytes(app_bytes)
    css_bytes = (out / 'assets/style.css').read_bytes()
    css_name = 'assets/style.' + hashlib.sha256(css_bytes).hexdigest()[:16] + '.css'
    (out / css_name).write_bytes(css_bytes)
    html = (out / 'index.html').read_text()
    html = html.replace('src="assets/app.js"', f'src="{app_name}"')
    html = html.replace('href="assets/style.css"', f'href="{css_name}"')
    html = html.replace('href="paper-results.json"', f'href="{results_name}"')
    assert 'src="assets/app.js"' not in html
    assert 'href="assets/style.css"' not in html
    assert f"readJson('{results_name}')" in app
    (out / 'index.html').write_text(html)
    for value in re.findall(r'(?:src|href|data-figure)="([^"]+)"', html):
        if not value.startswith(('http', '#')):
            assert (out / value.split('#')[0]).exists(), value
    (out / '.nojekyll').touch()
    print('Paper website: 18 configurations, common 230 questions; source hashes verified.')
    print(f'Site built: {len(questions)} questions, {len(rubrics)} rubrics → {out}')


if __name__ == '__main__':
    build()
