#!/usr/bin/env python3
"""Scan a local clone of techer-files once; keep curated lessons and index the existing library."""
import json,pathlib,argparse,hashlib
p=argparse.ArgumentParser();p.add_argument('repository');args=p.parse_args();root=pathlib.Path(args.repository)
path=root/'content/index.json';catalog=json.loads(path.read_text())
extensions={'.pdf','.doc','.docx','.ppt','.pptx','.xls','.xlsx','.png','.jpg','.jpeg','.webp','.mp4','.webm','.mp3','.wav','.html','.txt','.md'}
for level in catalog['levels']:
    directory=root/level['code']
    if not directory.exists() and level['code']=='2BACPC':directory=root/'2BAC'
    if not directory.exists():continue
    subjects={s['id']:s for s in level['subjects']}
    for subjectDir in directory.iterdir():
        if not subjectDir.is_dir():continue
        key=subjectDir.name.lower();subject=subjects.get(key)
        if subject is None:subject={'id':key,'title':subjectDir.name,'lessons':[]};level['subjects'].append(subject)
        subject['lessons']=[l for l in subject['lessons'] if l['id']!='library-index']
        resources=[]
        for f in sorted(subjectDir.rglob('*')):
            if not f.is_file() or f.suffix.lower() not in extensions:continue
            data=f.read_bytes();sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
            resources.append({'title':f.stem,'path':f.relative_to(root).as_posix(),'category':'دروس','sha':sha})
        if resources:subject['lessons'].append({'id':'library-index','title':'المكتبة الدراسية • Bibliothèque','objectives':[],'resources':resources,'test_path':''})
catalog['includes_legacy_library']=False
path.write_text(json.dumps(catalog,ensure_ascii=False,indent=2));print('Catalog updated; existing library retained')
