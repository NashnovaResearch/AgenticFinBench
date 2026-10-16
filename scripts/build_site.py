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
    print(f'Site built: {len(questions)} questions, {len(rubrics)} rubrics, 12 results → {out}')


if __name__ == '__main__':
    build()
