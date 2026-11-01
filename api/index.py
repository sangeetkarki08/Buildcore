"""BuildCore web - the one serverless function Vercel runs for every /api and /files request.

It starts the BuildCore engine (the same Python code as the desktop app) on the Supabase database and
answers with the desktop's own request handler.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "engine")
sys.path.insert(0, ENGINE)

from web import boot  # noqa: E402

server = boot.start()

from web.webpatch import make_handler  # noqa: E402

_WebHandler = make_handler(server)
class handler(_WebHandler):
    pass
