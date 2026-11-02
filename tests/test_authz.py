import datetime as dt
import time

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

import app as appmod
import authz

PROJECT = "taiwanstock-ben"


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    now = dt.datetime.now(dt.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(1).not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=1)).sign(key, hashes.SHA256()))
    return key, cert


@pytest.fixture
def client(monkeypatch, keypair):
    _, cert = keypair
    monkeypatch.setattr(authz, "_load_certs", lambda: {"k1": cert.public_key()})
    monkeypatch.setattr(appmod, "_wwl", lambda items: None)   # 不寫磁碟
    return TestClient(appmod.app)


def token(keypair, sub="u1", aud=PROJECT, exp_in=600):
    key, _ = keypair
    now = int(time.time())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    return jwt.encode({"sub": sub, "aud": aud, "iss": f"https://securetoken.google.com/{aud}",
                       "iat": now, "exp": now + exp_in}, pem, algorithm="RS256", headers={"kid": "k1"})


BODY = {"watchlist": []}


def test_not_enforced_by_default(client, monkeypatch):
    monkeypatch.delenv("AUTH_ENFORCE", raising=False)
    assert client.post("/api/watchlist", json=BODY).status_code == 200


def test_enforced_rejects_missing_and_bad(client, monkeypatch, keypair):
    monkeypatch.setenv("AUTH_ENFORCE", "true")
    assert client.post("/api/watchlist", json=BODY).status_code == 401
    bad = token(keypair, aud="other-project")
    assert client.post("/api/watchlist", json=BODY, headers={"Authorization": f"Bearer {bad}"}).status_code == 401
    old = token(keypair, exp_in=-3600)
    assert client.post("/api/watchlist", json=BODY, headers={"Authorization": f"Bearer {old}"}).status_code == 401


def test_enforced_accepts_valid_and_checks_allowlist(client, monkeypatch, keypair):
    monkeypatch.setenv("AUTH_ENFORCE", "true")
    ok = {"Authorization": f"Bearer {token(keypair)}"}
    assert client.post("/api/watchlist", json=BODY, headers=ok).status_code == 200
    monkeypatch.setenv("ALLOWED_UIDS", "someone-else")
    assert client.post("/api/watchlist", json=BODY, headers=ok).status_code == 403


def test_admin_token(client, monkeypatch):
    monkeypatch.setenv("AUTH_ENFORCE", "true")
    monkeypatch.setenv("ADMIN_TOKEN", "s3cret")
    assert client.post("/api/watchlist", json=BODY, headers={"X-Admin-Token": "s3cret"}).status_code == 200
    assert client.post("/api/watchlist", json=BODY, headers={"X-Admin-Token": "nope"}).status_code == 401


def test_read_endpoints_stay_open(client, monkeypatch):
    monkeypatch.setenv("AUTH_ENFORCE", "true")
    assert client.get("/health").status_code == 200
