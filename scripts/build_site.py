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
    assert len(qmap) == len(questions) == len(rubrics) == 500
    assert {r['question_id'] for r in rubrics} == set(qmap)
    out = ROOT / 'public'
    out.mkdir(exist_ok=True)
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
    results = json.loads((out / 'results.json').read_text())
    assert len(results['models']) == 12
    assert sum(m['count'] for m in results['models']) == 5998
    assert all(0 <= m['new_Q'] <= 100 for m in results['models'])
    assert not [p for p in out.rglob('*') if p.name == '.env' or p.name.startswith('AGENTS')]
    paper = json.loads((out / 'paper-results.json').read_text())
    assert paper['question_count'] == 500
    assert len(paper['models']) == paper['configuration_count'] == 11
    assert sorted(m['rank'] for m in paper['models']) == list(range(1, 12))
    assert len({(m['model'], m['harness']) for m in paper['models']}) == 11
    assert all(m['count'] == 500 and 0 <= m['q'] <= 100 for m in paper['models'])
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
    audit_rows = (ROOT / 'docs/paper-snapshot/tab_audit_full_rows.tex').read_text().splitlines()
    for line in audit_rows:
        fields = [x.strip() for x in line.split(' & ')]
        model = next(m for m in paper['models'] if m['model'] + ' / ' + m['harness'] == fields[0])
        assert int(fields[1].replace(',', '')) == model['claims']
        assert float(fields[3].split()[0]) == model['response_hallucination']
        assert float(fields[4].split()[0]) == model['claim_hallucination']
    assert sum(m['claims'] for m in paper['models']) == 305727
    html = (out / 'index.html').read_text()
    for value in re.findall(r'(?:src|href|data-figure)="([^"]+)"', html):
        if not value.startswith(('http', '#')):
            assert (out / value.split('#')[0]).exists(), value
    (out / '.nojekyll').touch()
    print('Paper website: 11 configurations, common 500 questions; source hashes verified.')
    print(f'Site built: {len(questions)} questions, {len(rubrics)} rubrics, 12 legacy results → {out}')


if __name__ == '__main__':
    build()
