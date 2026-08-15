import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

import uvicorn
from config import DOCS_BASE_URL
from main import app

if __name__ == "__main__":
    print("Starting FlytBase Graph Knowledge-Base Agent Server at http://127.0.0.1:8088")
    uvicorn.run(app, host="127.0.0.1", port=8088, reload=False)


