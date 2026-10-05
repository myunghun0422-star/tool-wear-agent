from __future__ import annotations
import os
import uvicorn

if __name__ == "__main__":
    host = os.environ.get("TWA_HOST", "0.0.0.0")
    port = int(os.environ.get("TWA_PORT", "8001"))
    uvicorn.run("api:app", host=host, port=port, reload=False)
