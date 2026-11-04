"""Keep old script commands/imports working from any working directory."""
from importlib import import_module
from pathlib import Path
import sys


def redirect(name, target):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    module = import_module(target)
    if name == "__main__":
        module.main()
    else:
        sys.modules[name] = module
