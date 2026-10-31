import os

from app.secret_store import SecretStore


def test_local_secret_store_round_trip_has_private_permissions_and_atomic_replacement(tmp_path):
    path = tmp_path / "private" / "credentials.json"
    store = SecretStore(path)
    store.set("kaggle_api_token", "sample-secret-value")
    assert store.get("kaggle_api_token") == "sample-secret-value"
    assert store.has("kaggle_api_token")
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert os.stat(path.parent).st_mode & 0o777 == 0o700
    store.delete("kaggle_api_token")
    assert not store.has("kaggle_api_token")
