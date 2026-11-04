"""Public pump subcommands share a group; inspection keeps its own read-only contract."""
from . import pump_public, pump_edit

def register(groups):
    actions = groups.add_parser("pump", help="Inspect pump input files or preview and apply an explicit scalar edit").add_subparsers(dest="action", required=True)
    pump_public.register_inspect(actions)
    pump_edit.register(actions)
    return actions

def execute(args):
    if args.action == "set":
        return pump_edit.execute(args)
    return pump_public.execute(args)
