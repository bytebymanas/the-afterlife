# THE AFTERLIFE

THE AFTERLIFE is a Victorian horror archive for conversations with historically grounded portrayals of deceased public figures. Soul prompts and conversation history are stored by the FastAPI backend; Ollama streams each reply to the React interface.

## Run locally

Requirements: Python 3.9 or newer, Node.js, and an Ollama installation if you want to chat with a local model.

```sh
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

In a second terminal, from the project root:

```sh
npm install
npm run dev
```

Open <http://127.0.0.1:5173>. The backend API runs at <http://127.0.0.1:8000> and uses SQLite by default.

## Configure AI

Open **Settings → Connection** to select the Ollama connection and model.

- **Local Ollama:** the default endpoint is `http://127.0.0.1:11434`. Install Ollama and a model locally; no API key is needed for a standard local install.
- **Kaggle GPU:** open `public/kaggle_gpu_manual.ipynb` in Kaggle, enable an available GPU accelerator, replace the `GATEWAY_TOKEN` placeholder with a private random value of at least 24 characters, and run the notebook cell. Keep the session open. Paste its Gateway URL, token, and model name into Settings. The same token is held in the backend's OS secret store and is not written to source files.

Dynamic famous-person summoning also requires a Brave Search API key. Set `BRAVE_SEARCH_API_KEY` in the backend process environment. The key is used only by the backend to verify identity and life status; it must never be placed in frontend code or committed to Git. If verification is inconclusive, summoning fails closed and asks for identifying details.

## Soul prompts and conversations

Owner-authored prompts are managed in **Settings → Connection → Character prompts**. Each saved prompt is stored as written and sent verbatim as that soul's system message. Conversation turns are persisted in the backend database and streamed from Ollama.

## Tests

```sh
cd backend
PYTHONPATH=. pytest -q tests
```

The conversation-flow evaluation checks multiple distinct soul prompts, multi-turn history, streaming, and reply persistence. Unit tests do not require external services.

## Security and local data

Do not commit `.env` files, database files, gateway tokens, API keys, private keys, or local secret-store data. The root `.gitignore` excludes common local state and generated output. Review files before publishing changes.
