"""Cloud Run function entry for `hiru-echo` (functions-framework target `handle`).

The service package `echo_service` sits next to this file; `contracts` is on the path
(editable install locally, copied into the zip root by the deploy workflow).
"""
from echo_service.app.handler import handle  # noqa: F401
