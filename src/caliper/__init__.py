"""Statistical Process Control over LLM-as-a-judge agent quality scores.

Caliper treats a judge score stream as a process: fit control limits on a
trusted Phase I baseline, then monitor Phase II observations against them.

The public surface is deliberately empty at this point in the build -- names
are exported here only once the story that introduces them lands.

BIN-57 lands ``Judge`` and ``ModelVersion``, but re-exports them from
``caliper.measurement`` only (see that package's ``__init__.py``), not from
this top-level package. ``tests/test_package.py`` pins this package's
``__all__`` to ``[]`` as a smoke test, and the measurement bounded context
is not yet the library's only context (baseline collection, fitting, and
monitoring will each add their own names) -- promoting names to the
top level piecemeal, one story at a time, would churn the top-level surface
repeatedly. That promotion is better made once, deliberately, when the
walking skeleton's public API shape is decided.
"""

__all__: list[str] = []
