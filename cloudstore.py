"""把伺服器上的小型 JSON 狀態檔備份到 Firestore，讓 Render 休眠／重啟後能還原。

Render 免費方案沒有永久磁碟：主機休眠、重啟或重新部署後，本機檔案會消失。
做法：本機檔案仍是日常讀寫的地方；每次寫檔後把內容推到 Firestore
（集合 server_state，一檔一份文件），啟動時若本機檔不存在就從 Firestore 拉回。

啟用條件：環境變數 FIREBASE_SERVICE_ACCOUNT 內含服務帳戶金鑰 JSON，
或 Render Secret File /etc/secrets/FIREBASE_SERVICE_ACCOUNT。
未設定時所有函式都是 no-op，行為與原本只寫檔相同。
只用既有套件（httpx、PyJWT），不引入 firebase-admin。
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import jwt

COLLECTION = "server_state"
MAX_BYTES = 900_000          # Firestore 單一文件上限約 1 MiB
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/datastore"
SECRET_FILES = ["/etc/secrets/FIREBASE_SERVICE_ACCOUNT", str(Path(__file__).resolve().parent / "FIREBASE_SERVICE_ACCOUNT")]

_lock = threading.Lock()
_token: tuple[str, float] | None = None
_last_error: str | None = None
_last_push: str | None = None
_transport: httpx.BaseTransport | None = None   # tests inject a MockTransport


def _account() -> dict | None:
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT", "").strip()
    if not raw:   # Render「Secret Files」：檔案會出現在 /etc/secrets/<檔名> 與 App 根目錄
        for f in SECRET_FILES:
            try:
                raw = Path(f).read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if raw:
                break
    if not raw:
        return None
    try:
        acc = json.loads(raw)
        if acc.get("client_email") and acc.get("private_key") and acc.get("project_id"):
            return acc
    except Exception:
        pass
    return None


def enabled() -> bool:
    return _account() is not None


def status() -> dict:
    return {"enabled": enabled(), "collection": COLLECTION, "last_push": _last_push, "last_error": _last_error}


def _client() -> httpx.Client:
    return httpx.Client(timeout=10, transport=_transport)


def _access_token(acc: dict) -> str:
    global _token
    with _lock:
        if _token and _token[1] - 60 > time.time():
            return _token[0]
    now = int(time.time())
    assertion = jwt.encode(
        {"iss": acc["client_email"], "scope": SCOPE, "aud": TOKEN_URL, "iat": now, "exp": now + 3600},
        acc["private_key"], algorithm="RS256")
    with _client() as cl:
        r = cl.post(TOKEN_URL, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
    r.raise_for_status()
    d = r.json()
    with _lock:
        _token = (d["access_token"], time.time() + int(d.get("expires_in", 3600)))
        return _token[0]


def _doc_url(acc: dict, name: str) -> str:
    return (f"https://firestore.googleapis.com/v1/projects/{acc['project_id']}"
            f"/databases/(default)/documents/{COLLECTION}/{name}")


def push(path: Path) -> bool:
    """Upload the file's current content. Returns True when stored."""
    global _last_error, _last_push
    acc = _account()
    if not acc:
        return False
    try:
        text = Path(path).read_text(encoding="utf-8")
        if len(text.encode("utf-8")) > MAX_BYTES:
            _last_error = f"{Path(path).name}: too large to back up"
            return False
        body = {"fields": {"json": {"stringValue": text},
                           "updated_at": {"stringValue": datetime.now(timezone.utc).isoformat()}}}
        with _client() as cl:
            r = cl.patch(_doc_url(acc, Path(path).stem), json=body,
                         headers={"Authorization": f"Bearer {_access_token(acc)}"})
        r.raise_for_status()
        _last_push = datetime.now(timezone.utc).isoformat()
        _last_error = None
        return True
    except Exception as e:  # backup must never break the request that triggered it
        _last_error = f"push {Path(path).name}: {str(e)[:160]}"
        return False


def push_async(path: Path) -> None:
    if enabled():
        threading.Thread(target=push, args=(path,), daemon=True).start()


def pull(path: Path) -> bool:
    """Restore the file from Firestore if it is missing locally. Returns True when restored."""
    global _last_error
    acc = _account()
    path = Path(path)
    if not acc or path.exists():
        return False
    try:
        with _client() as cl:
            r = cl.get(_doc_url(acc, path.stem), headers={"Authorization": f"Bearer {_access_token(acc)}"})
        if r.status_code == 404:
            return False
        r.raise_for_status()
        text = r.json().get("fields", {}).get("json", {}).get("stringValue")
        if not text:
            return False
        json.loads(text)  # refuse to restore something that is not JSON
        path.write_text(text, encoding="utf-8")
        return True
    except Exception as e:
        _last_error = f"pull {path.name}: {str(e)[:160]}"
        return False


def pull_all(paths) -> list[str]:
    return [Path(p).name for p in paths if pull(p)]
