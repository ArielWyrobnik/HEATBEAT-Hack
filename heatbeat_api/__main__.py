"""python -m heatbeat_api [--port 8000]: start the API server."""
import argparse

import uvicorn

p = argparse.ArgumentParser()
p.add_argument("--port", type=int, default=8000)
p.add_argument("--host", default="127.0.0.1")
p.add_argument("--reload", action="store_true")
a = p.parse_args()
uvicorn.run("heatbeat_api.app:app", host=a.host, port=a.port, reload=a.reload)
