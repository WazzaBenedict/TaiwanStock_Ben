# 台股監測儀表板 🇹🇼

> ⚠️ **免責聲明**：本工具僅供技術分析學習參考，**不構成任何投資建議**。股市有風險，投資人應自行判斷，買賣股票盈虧自負。

輸入台股股票代號（例如 `2330`），即可自動抓取一年股價資料，計算 MA / RSI / MACD 等技術指標，並顯示新聞情緒分析與回測勝率。

---

## 📁 專案結構

```
tw-stock-monitor/
├── app.py                 # FastAPI 後端
├── requirements.txt       # Python 套件清單
├── firebase.json          # Firebase Hosting 設定
├── .firebaserc            # Firebase 專案 ID
├── .gitignore
├── README.md
└── public/                # 前端靜態檔案（部署到 Firebase Hosting）
    ├── index.html         # 主頁面
    ├── config.js          # API URL 設定（唯一需要改的地方）
    └── 404.html           # 404 頁面
```

---

## 🚀 本機安裝與啟動

### 第一步：安裝 Python 套件

```bash
cd tw-stock-monitor
pip install -r requirements.txt
```

### 第二步：啟動後端

```bash
# 本機開發模式（允許所有來源，方便直接雙擊 HTML）
DEV_MODE=true python -m uvicorn app:app --reload --port 8000

# 或一般模式（只允許 localhost:5500 等）
python -m uvicorn app:app --reload --port 8000
```

看到 `Application startup complete.` 就成功了。

### 第三步：打開前端

方法 A（最簡單）：直接用瀏覽器開啟 `public/index.html`

方法 B（推薦，解決 CORS）：用 VS Code 的 Live Server 插件，
右鍵 `public/index.html` → `Open with Live Server`（預設在 `http://127.0.0.1:5500`）

### 測試 API 是否正常

```
http://localhost:8000/health
http://localhost:8000/api/stock/2330
```

---

## ⚙️ API URL 設定

編輯 `public/config.js`：

```js
// 本機開發
const API_BASE_URL = "http://127.0.0.1:8000";

// 部署到雲端後改成你的 API 網址
const API_BASE_URL = "https://your-api.onrender.com";
```

**改完 config.js 之後重新 `firebase deploy` 即可生效。**

---

## 🌐 GitHub 管理步驟

### 1. 在 GitHub 建立 repository

1. 前往 https://github.com → 右上角 `+` → `New repository`
2. Repository name：`tw-stock-monitor`
3. 設為 Private（建議）或 Public
4. 不要勾選「Add a README file」（我們已有）
5. 點 `Create repository`

### 2. 本機初始化 git

```bash
cd tw-stock-monitor

# 初始化
git init

# 加入所有檔案
git add .

# 第一次 commit
git commit -m "feat: 台股監測工具初始版本"

# 設定主分支名稱（配合 GitHub 預設）
git branch -M main

# 連接到你的 GitHub repo（把 YOUR_USERNAME 換成你的帳號）
git remote add origin https://github.com/YOUR_USERNAME/tw-stock-monitor.git

# 推送
git push -u origin main
```

### 3. 之後每次更新

```bash
git add .
git commit -m "fix: 修正某某問題"
git push
```

---

## 🔥 Firebase Hosting 部署步驟

### 1. 建立 Firebase 專案

1. 前往 https://console.firebase.google.com
2. 點「新增專案」→ 輸入專案名稱（例如 `tw-stock-monitor`）
3. 不需要啟用 Google Analytics（可跳過）
4. 等待建立完成

### 2. 安裝 Firebase CLI

```bash
# 需要先安裝 Node.js（https://nodejs.org）
npm install -g firebase-tools
```

### 3. 登入 Firebase

```bash
firebase login
# 會開啟瀏覽器，用 Google 帳號登入
```

### 4. 初始化 Hosting

```bash
cd tw-stock-monitor
firebase init hosting
```

回答問題：
- `Which Firebase project?` → 選你剛建立的專案
- `What do you want to use as your public directory?` → 輸入 `public`
- `Configure as single-page app?` → `Y`
- `Set up automatic builds with GitHub?` → `N`（暫時不需要）
- `File public/index.html already exists. Overwrite?` → `N`（不要覆蓋！）

### 5. 更新 .firebaserc

打開 `.firebaserc`，把 `你的-firebase-project-id` 換成你的實際 Project ID
（在 Firebase Console → 專案設定 → 一般設定 → 專案 ID）

### 6. 部署

```bash
firebase deploy
```

完成後會顯示：
```
Hosting URL: https://你的專案ID.web.app
```

### 7. 之後更新前端

```bash
# 修改 public/ 裡的檔案後
firebase deploy
# 或只部署 hosting
firebase deploy --only hosting
```

---

## 📡 後端部署方案比較

### 方案 A：免費簡易版（前端雲端 + 後端本機）

- 前端：Firebase Hosting（免費）
- 後端：你的電腦本機跑
- 缺點：**只有你的電腦開著時才能用**
- 適合：個人自用、測試階段

### 方案 B：完整雲端版

| 平台 | 免費額度 | 難度 | 需信用卡 | 推薦度 |
|------|---------|------|---------|--------|
| **Render** | 750小時/月，靜置會休眠 | ⭐ 最簡單 | 否 | ⭐⭐⭐⭐⭐ |
| Railway | $5 免費額度 | ⭐⭐ | 否 | ⭐⭐⭐⭐ |
| Fly.io | 有免費方案 | ⭐⭐⭐ | 需驗證 | ⭐⭐⭐ |
| Google Cloud Run | 每月 200萬次請求免費 | ⭐⭐⭐⭐ | 需信用卡 | ⭐⭐ |

**新手推薦 Render**（最簡單，不需信用卡）：

1. 前往 https://render.com → 用 GitHub 登入
2. `New` → `Web Service` → 選你的 GitHub repo
3. 設定：
   - Build Command：`pip install -r requirements.txt`
   - Start Command：`uvicorn app:app --host 0.0.0.0 --port $PORT`
4. 加入環境變數：
   - `ALLOWED_ORIGINS` = `https://你的專案ID.web.app,https://你的專案ID.firebaseapp.com`
5. 點 Deploy，等待完成
6. 取得 API 網址（例如 `https://tw-stock-api.onrender.com`）
7. 更新 `public/config.js` 裡的 `API_BASE_URL`
8. 重新 `firebase deploy`

> ⚠️ Render 免費方案：閒置 15 分鐘後會休眠，第一次請求需要 30 秒喚醒，屬正常現象。

---

## 🔧 CORS 設定說明

`app.py` 使用環境變數 `ALLOWED_ORIGINS` 管理允許的來源：

```bash
# 本機開發（允許所有來源）
DEV_MODE=true python -m uvicorn app:app --reload

# 指定允許的來源
ALLOWED_ORIGINS="https://你的專案.web.app,https://你的專案.firebaseapp.com" \
  python -m uvicorn app:app --reload
```

---

## 📊 API 說明

### `GET /api/stock/{stock_id}`

回傳格式：
```json
{
  "stock_id": "2330",
  "stock_name": "台積電",
  "last_date": "2024-01-15",
  "price": { "close": 600, "open": 598, "high": 605, "low": 597, "change": 5, "change_pct": 0.84 },
  "indicators": { "ma5": 595, "ma20": 580, "ma60": 560, "rsi": 62.5, "macd": 8.2, "signal": 7.1, "hist": 1.1 },
  "volume": { "latest_volume": 25000000, "avg_volume_20d": 20000000, "ratio": 1.25, "alert": false },
  "score": { "score": 4, "max": 5, "reasons": ["✅ ...", "✅ ..."] },
  "backtest": { "trials": 35, "wins": 22, "winrate": 62.9 },
  "conclusion": "短線偏多 📈",
  "rsi_alert": null,
  "news": [ { "title": "...", "link": "...", "pub_date": "...", "sentiment": "利多" } ],
  "chart_data": [ { "date": "2024-01-15", "close": 600, "volume": 25000000, "ma5": 595, ... } ]
}
```

### `GET /health`

確認後端是否正常運作。

---

## 🆓 使用的免費工具

| 工具 | 用途 | 費用 |
|------|------|------|
| FinMind API | 台股歷史股價 | 免費（有速率限制） |
| TWSE Open API | 股票名稱查詢 | 完全免費 |
| Google News RSS | 新聞抓取 | 完全免費 |
| Chart.js | 圖表繪製 | 完全免費 |
| Firebase Hosting | 前端部署 | 免費方案夠用 |
| Render | 後端部署 | 免費方案（有休眠限制） |
| GitHub | 程式碼管理 | 免費 |
