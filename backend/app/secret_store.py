"""Local single-user credential store. Secrets stay backend-side and out of Git."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path


_DEFAULT_PATH = Path(__file__).resolve().parents[1] / ".private" / "credentials.json"
_LOCK = threading.RLock()


class SecretStoreError(RuntimeError):
    pass


class SecretStore:
    """Restrict the local credential file and its parent directory to this user.

    This app is currently a single-user local installation. The file is deliberately
    ignored by Git and never copied into generated Kaggle notebook source.
    """
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.getenv("AFTERLIFE_SECRETS_FILE", str(_DEFAULT_PATH)))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.path.parent == _DEFAULT_PATH.parent:
                os.chmod(self.path.parent, 0o700)
            if self.path.exists():
                os.chmod(self.path, 0o600)
        except OSError as exc:
            raise SecretStoreError("LOCAL_CREDENTIAL_STORE_UNAVAILABLE") from exc

    def _read(self) -> dict[str, str]:
        try:
            if not self.path.exists():
                return {}
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or any(not isinstance(v, str) for v in data.values()):
                raise ValueError("invalid credential store")
            return data
        except Exception as exc:
            raise SecretStoreError("LOCAL_CREDENTIAL_STORE_UNREADABLE") from exc

    def _write(self, data: dict[str, str]):
        temp = self.path.with_suffix(".tmp")
        try:
            fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, self.path)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            try: temp.unlink(missing_ok=True)
            except OSError: pass
            raise SecretStoreError("LOCAL_CREDENTIAL_STORE_WRITE_FAILED") from exc

    def set(self, key: str, value: str):
        with _LOCK:
            data = self._read()
            data[key] = value
            self._write(data)

    def get(self, key: str) -> str | None:
        with _LOCK:
            return self._read().get(key)

    def delete(self, key: str):
        with _LOCK:
            data = self._read()
            data.pop(key, None)
            self._write(data)

    def has(self, key: str) -> bool:
        return bool(self.get(key))
