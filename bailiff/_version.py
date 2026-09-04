"""Single source of truth for the release identifier.

Every place that names a version — `pyproject.toml`, the FastAPI app, the
generated dataset manifests, `outputs/manifest.json` — must import this
constant rather than retype it. A hardcoded copy is exactly how a submission
ends up with three different version strings in three different files.
"""

RELEASE_VERSION = "0.9.0"
