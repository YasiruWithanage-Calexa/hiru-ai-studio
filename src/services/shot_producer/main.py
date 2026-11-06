"""Cloud Run function entry for `hiru-shot-producer` (functions-framework target `handle`)."""
import os

# The legacy engine calls OpenAI directly, outside LangChain: importing langfuse.openai traces those calls (ADR 0008).
# Not under AI_ENGINE=graph, which hiru_ai traces itself (a second tracer would record every call twice).
if os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("AI_ENGINE", "legacy") != "graph":
    try:
        import langfuse.openai  # noqa: F401
    except ImportError:  # the package is optional; without it nothing is traced
        pass

from shot_producer.app.handler import handle  # noqa: F401
