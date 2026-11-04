"""Compatibility entry point; see research/workflows/."""
if __package__:
    from ._compat import redirect
else:
    from _compat import redirect

redirect(__name__, "research.workflows.collection.acquire_managed_cli")
