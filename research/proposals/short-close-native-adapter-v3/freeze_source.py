"""Freeze this candidate source and plan for independent review; never admit execution."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import HERE, PREPARED, save, sha


if __name__=='__main__':
    paths=[*HERE.glob('*.py'),HERE/'expected-product.json']
    files={p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(paths)}
    packet={'node':'NATIVE-ADAPTER-I','state':'source_candidate_for_independent_review',
        'artifact_files':files,'predeclared_sha256':sha(PREPARED/'predeclared.json'),
        'native_authorized':False,'native_launches':0}
    save(HERE/'freeze.json',packet)
    print(json.dumps({'freeze_sha256':sha(HERE/'freeze.json'),'native_launches':0}))
