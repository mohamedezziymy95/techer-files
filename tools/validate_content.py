#!/usr/bin/env python3
"""Validate deployable tests and the lesson catalog. Run before pushing GitHub content."""
import argparse, json, pathlib, math

def validate(root):
    root=pathlib.Path(root); index=json.loads((root/'tests/index.json').read_text(encoding='utf-8-sig'))
    ids=set();count=0
    def questions(rows):
        seen=set()
        for q in rows:
            assert q['id'] not in seen, f"Duplicate question {q['id']}"
            seen.add(q['id']);assert q['text'].strip();opts=q['options'];assert 2<=len(opts)<=12
            correct=q.get('correct_options') or [q['correct']]
            assert 0<len(set(correct))<len(opts) and all(isinstance(i,int) and 0<=i<len(opts) for i in correct)
            assert math.isfinite(q.get('points',1)) and q.get('points',1)>0
            questions(q.get('practice',[]))
    for s in index['tests']:
        assert s['id'] not in ids;ids.add(s['id'])
        p=pathlib.PurePosixPath(s['path']);assert not p.is_absolute() and '..' not in p.parts
        t=json.loads((root/'tests'/p).read_text(encoding='utf-8-sig'))
        assert t['id']==s['id'] and t['level']==s['level'];assert t['level']!='2BAC'
        assert len(t['questions'])==s['questions_count'];questions(t['questions']);count+=len(t['questions'])
    catalog=json.loads((root/'content/index.json').read_text(encoding='utf-8-sig'))
    assert catalog['schema_version']==1
    for level in catalog['levels']:
        for subject in level['subjects']:
            for lesson in subject['lessons']:
                for r in lesson['resources']:
                    p=pathlib.PurePosixPath(r['path']);assert '..' not in p.parts and not p.is_absolute()
                    assert (root/p).is_file(), f"Missing resource {p}"
                if lesson.get('test_path'):assert (root/'tests'/lesson['test_path']).is_file()
    return len(ids),count
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',nargs='?',default='app/src/main/assets');args=parser.parse_args()
    n,q=validate(args.root);print(f'PASS: {n} indexed tests, {q} questions; catalog resources valid')
