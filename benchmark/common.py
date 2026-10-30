import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'public-full-pipeline-v2-cohort230'


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    tmp.replace(path)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def digest(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def require(ok, message):
    if not ok:
        raise ValueError(message)


def dataset():
    m = read(ROOT/'data/manifest.json')
    for name, h in m['files'].items():
        require(sha((ROOT/'data'/name).read_bytes()) == h, 'Dataset hash changed: ' + name)
    qs = read(ROOT/'data/questions.json')
    rs = read(ROOT/'data/rubrics.json')
    q = {x['id']: x for x in qs}
    r = {x['question_id']: x for x in rs}
    require(len(qs) == len(rs) == len(q) == len(r) == 230 and q.keys() == r.keys(), 'Expected exact 230 question/rubric pairs')
    cohort = read(ROOT/'data/cohort230.json')
    bindings = {x['question_id']: x for x in cohort['questions']}
    require(len(bindings) == cohort['count'] == 230 and bindings.keys() == q.keys(), 'Cohort membership mismatch')
    for k, v in q.items():
        require(v['question_sha256'] == bindings[k]['question_sha256'] and v['level'] == bindings[k]['level'], 'Cohort binding mismatch: ' + k)
    from .scoring import validate_rubric
    for k, v in q.items():
        require(v['question'] == r[k]['question'] and sha(v['question'].encode()) == v['question_sha256'] == r[k]['question_sha256'], 'Question/rubric mismatch: ' + k)
        validate_rubric(r[k])
    return q, r
