# Backend setup

Use Python 3.9+ (the current repository runtime is Python 3.9).

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API defaults to SQLite at `backend/afterlife.db`. For PostgreSQL, set `DATABASE_URL` to a SQLAlchemy URL such as `postgresql+psycopg://user:password@host/database` and run `alembic upgrade head` from this directory. FastAPI's interactive API reference is at `http://127.0.0.1:8000/docs`.

Install/start Ollama separately, then choose the connection and model in Settings. For a local Ollama install, the default endpoint is `http://127.0.0.1:11434`; no API key is needed. For Kaggle, run `public/kaggle_gpu_manual.ipynb` with GPU enabled, then paste its HTTPS Gateway URL, model name, and the same gateway token into Settings. The backend stores the token in the operating system's local secret store. No Kaggle API token is needed.

Dynamic famous-person summoning requires a Brave Search API key in the backend environment as `BRAVE_SEARCH_API_KEY`; obtain one from the Brave Search API dashboard. Verification fails closed when search is unavailable or the identity/life status is unclear. Ollama also needs to be reachable from the backend for generated character prompts. Never put the Brave key or gateway token in the Vite frontend.

Predefined soul prompts are authored in Settings under Connection → Character prompts. Each saved prompt is stored verbatim and sent as the sole system message for each turn. Conversation history and streamed assistant replies are stored in the backend database.

Start the UI in another terminal with `npm run dev`; Vite proxies `/api` to FastAPI. The Kaggle notebook is run manually by the project owner; if the session stops, reopen and rerun the notebook, then save its current endpoint in Settings.

Run unit tests with `PYTHONPATH=. pytest -q` from this directory. Tests do not use the network.
