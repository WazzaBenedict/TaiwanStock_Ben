"""寫入 API 的身分驗證：驗 Firebase ID token（不需 service account）或管理用 ADMIN_TOKEN。

環境變數（Render）：
- AUTH_ENFORCE=true      開始強制；預設 false 只記錄、不擋，避免舊前端一上線就壞掉
- FIREBASE_PROJECT_ID     預設 taiwanstock-ben
- ALLOWED_UIDS            逗號分隔；有設時只有這些 Firebase 使用者能寫入
- ADMIN_TOKEN             給腳本用，放在 X-Admin-Token 標頭
"""
from __future__ import annotations

import hmac
import logging
import os
import re
import time

import httpx
import jwt
from cryptography import x509
from fastapi import HTTPException, Request

log = logging.getLogger("authz")
CERTS_URL = "https://www.googleapis.com/robot/v1/metadata/x509/securetoken@system.gserviceaccount.com"
_certs: dict[str, object] = {}
_certs_exp = 0.0


def _settings():
    return {
        "enforce": os.getenv("AUTH_ENFORCE", "false").lower() == "true",
        "project": os.getenv("FIREBASE_PROJECT_ID", "taiwanstock-ben"),
        "uids": {u.strip() for u in os.getenv("ALLOWED_UIDS", "").split(",") if u.strip()},
        "admin": os.getenv("ADMIN_TOKEN", ""),
    }


def _load_certs() -> dict[str, object]:
    global _certs, _certs_exp
    if _certs and time.time() < _certs_exp:
        return _certs
    r = httpx.get(CERTS_URL, timeout=8)
    r.raise_for_status()
    m = re.search(r"max-age=(\d+)", r.headers.get("cache-control", ""))
    _certs = {kid: x509.load_pem_x509_certificate(pem.encode()).public_key() for kid, pem in r.json().items()}
    _certs_exp = time.time() + (int(m.group(1)) if m else 3600)
    return _certs


def verify_firebase_token(token: str, project: str) -> dict:
    kid = jwt.get_unverified_header(token).get("kid")
    key = _load_certs().get(kid)
    if key is None:
        raise jwt.InvalidTokenError("unknown kid")
    claims = jwt.decode(token, key, algorithms=["RS256"], audience=project,
                        issuer=f"https://securetoken.google.com/{project}", leeway=60,
                        options={"require": ["exp", "iat", "sub"]})
    if not claims.get("sub"):
        raise jwt.InvalidTokenError("empty sub")
    return claims


def require_writer(request: Request) -> dict:
    """FastAPI dependency：放在會改伺服器狀態或發 LINE 的 POST 上。"""
    s = _settings()
    admin = request.headers.get("x-admin-token", "")
    if s["admin"] and admin and hmac.compare_digest(admin, s["admin"]):
        return {"uid": "admin"}
    reason = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            claims = verify_firebase_token(auth[7:].strip(), s["project"])
            if s["uids"] and claims["sub"] not in s["uids"]:
                if s["enforce"]:
                    raise HTTPException(403, detail="此帳號沒有寫入權限")
                log.warning("authz: uid %s not in ALLOWED_UIDS (not enforced)", claims["sub"])
            return {"uid": claims["sub"]}
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            reason = f"invalid token: {type(e).__name__}"
    else:
        reason = "missing token"
    if s["enforce"]:
        raise HTTPException(401, detail="需要登入才能執行此操作")
    log.warning("authz: %s on %s (not enforced)", reason, request.url.path)
    return {"uid": None}
