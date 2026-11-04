"""Record attempted writes and forbidden reads while exercising the public CLI."""
import json
import os
from pathlib import Path
import sys

blocked=[]
foreign={str(Path(p).resolve()).casefold() for p in json.loads(os.environ.get('DFM_TEST_FORBIDDEN_READS','[]'))}


def audit(event,args):
    if event=='open':
        name,mode,flags=args
        if isinstance(name,(str,bytes)):
            path=str(Path(os.fsdecode(name)).resolve())
            if path.casefold() in foreign:
                blocked.append(dict(event=event,path=path))
                raise RuntimeError('foreign read attempted')
        if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
            blocked.append(dict(event=event,path=str(name)))
            raise RuntimeError('read-only candidate attempted file write')
    if event in {'os.rename','os.remove','os.rmdir','os.mkdir','os.link','os.symlink','os.chmod','os.utime','subprocess.Popen','os.system','os.startfile','socket.connect','socket.bind'}:
        blocked.append(dict(event=event,args=repr(args)))
        raise RuntimeError('read-only candidate attempted mutation/process/network operation')


if __name__ == "__main__":
    sys.addaudithook(audit)
    try:
        from dfm_cli.cli import main
        raise SystemExit(main(sys.argv[1:]))
    finally:
        print(json.dumps({"review_audit": {"blocked": blocked}}), file=sys.stderr)
