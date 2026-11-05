"""Private overlay entry point. No staging or native dispatch by this wrapper."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'src'))
import dfm_cli
dfm_cli.__path__.insert(0, str(HERE / 'overlay/src/dfm_cli'))
from dfm_cli.cli import main

if __name__ == '__main__':
    raise SystemExit(main())
