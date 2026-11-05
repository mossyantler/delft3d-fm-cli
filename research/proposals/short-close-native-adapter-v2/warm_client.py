"""Warm the installed registered CLI before a command, never pause an engine."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arguments',type=Path,required=True);parser.add_argument('--sha256',required=True)
    parser.add_argument('--ready',type=Path,required=True)
    args=parser.parse_args();raw=args.arguments.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.sha256:raise ValueError('CLI arguments changed')
    arguments=json.loads(raw)
    if type(arguments) is not list or not all(type(x) is str for x in arguments):raise ValueError('Expected public argv array')
    # Exactly the registered product console entry point, in the admitted
    # installed interpreter under -I. No root/research product-path overlay.
    import dfm_cli
    from dfm_cli.cli import main as public_cli
    with args.ready.open('x',encoding='utf-8') as stream:
        json.dump({'state':'installed_public_cli_imported_command_NOT_started','argv':arguments,
                   'python':sys.executable,'package_origin':dfm_cli.__file__},stream)
    if sys.stdin.readline()!='go\n':return 2
    if hashlib.sha256(args.arguments.read_bytes()).hexdigest()!=args.sha256:raise ValueError('CLI arguments replaced after warm import')
    return public_cli(arguments)

if __name__=='__main__':raise SystemExit(main())
