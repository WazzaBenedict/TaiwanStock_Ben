import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import cloudstore


@pytest.fixture
def store(monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT", json.dumps(
        {"client_email": "svc@x.iam.gserviceaccount.com", "private_key": pem, "project_id": "proj"}))
    docs, calls = {}, []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, str(req.url)))
        if req.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 3600})
        assert req.headers["authorization"] == "Bearer tok"
        name = req.url.path.rsplit("/", 1)[-1]
        if req.method == "PATCH":
            docs[name] = json.loads(req.content)
            return httpx.Response(200, json=docs[name])
        if name in docs:
            return httpx.Response(200, json=docs[name])
        return httpx.Response(404, json={"error": "not found"})

    monkeypatch.setattr(cloudstore, "_transport", httpx.MockTransport(handler))
    monkeypatch.setattr(cloudstore, "_token", None)
    return docs, calls


def test_disabled_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv("FIREBASE_SERVICE_ACCOUNT", raising=False)
    f = tmp_path / "watchlist.json"
    f.write_text("{}", encoding="utf-8")
    assert cloudstore.enabled() is False
    assert cloudstore.push(f) is False
    assert cloudstore.pull(tmp_path / "missing.json") is False


def test_bad_key_is_disabled(monkeypatch):
    monkeypatch.setenv("FIREBASE_SERVICE_ACCOUNT", "not json")
    assert cloudstore.enabled() is False


def test_push_then_restore_after_disk_wipe(store, tmp_path):
    docs, calls = store
    f = tmp_path / "watchlist.json"
    f.write_text(json.dumps({"watchlist": [{"id": "2330", "name": "台積電"}]}, ensure_ascii=False), encoding="utf-8")
    assert cloudstore.push(f) is True
    assert "watchlist" in docs and "server_state/watchlist" in calls[-1][1]

    f.unlink()                                   # Render 休眠後磁碟被清空
    assert cloudstore.pull(f) is True
    assert json.loads(f.read_text(encoding="utf-8"))["watchlist"][0]["name"] == "台積電"
    assert sum(1 for m, u in calls if "oauth2" in u) == 1   # token cached


def test_pull_never_overwrites_existing_file(store, tmp_path):
    f = tmp_path / "tw_weights.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    cloudstore.push(f)
    f.write_text('{"a": 2}', encoding="utf-8")
    assert cloudstore.pull(f) is False
    assert json.loads(f.read_text(encoding="utf-8")) == {"a": 2}


def test_pull_missing_doc_and_oversize(store, tmp_path):
    assert cloudstore.pull(tmp_path / "nothing.json") is False
    big = tmp_path / "big.json"
    big.write_text(json.dumps({"x": "y" * (cloudstore.MAX_BYTES + 10)}), encoding="utf-8")
    assert cloudstore.push(big) is False
    assert "too large" in cloudstore.status()["last_error"]


def test_network_failure_does_not_raise(monkeypatch, store, tmp_path):
    def boom(req):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(cloudstore, "_transport", httpx.MockTransport(boom))
    f = tmp_path / "watchlist.json"
    f.write_text("{}", encoding="utf-8")
    assert cloudstore.push(f) is False
    f.unlink()
    assert cloudstore.pull(f) is False
