"""Infrastructure behind core/ports.py: Supabase REST, storage, the image API.

Only a composition root (a function handler, the API, the CLI) imports from here; a part asks the run for its port.
"""
