"""發版前檢查：後端 APP_VERSION、前端 FRONTEND_VERSION、index.html 的 ?v= 與顯示版本必須一致。"""
import re
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
backend = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', (root / "app.py").read_text(encoding="utf-8"), re.M).group(1)
frontend = re.search(r'var FRONTEND_VERSION="([^"]+)"', (root / "public/js/app.js").read_text(encoding="utf-8")).group(1)
html = (root / "public/index.html").read_text(encoding="utf-8")
asset = set(re.findall(r'\?v=([0-9.]+)"', html))
shown = set(re.findall(r">V([0-9]+\.[0-9]+\.[0-9]+)<", html))
problems = []
if backend != frontend:
    problems.append(f"backend {backend} != frontend {frontend}")
if asset != {frontend}:
    problems.append(f"index.html ?v= {sorted(asset)} != {frontend}")
if shown - {frontend}:
    problems.append(f"index.html shows {sorted(shown)} but version is {frontend}")
if problems:
    print("VERSION MISMATCH: " + "; ".join(problems))
    sys.exit(1)
print("version", frontend, "ok")
