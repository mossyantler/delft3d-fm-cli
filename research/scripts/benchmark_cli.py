"""Compatibility entry point; see research/workflows/."""
if __package__:
    from ._compat import redirect
else:
    from _compat import redirect

redirect(__name__, "research.workflows.verification.benchmark_cli")
