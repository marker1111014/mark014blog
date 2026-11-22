# Mark's Blog (`@mark11blog`) 個人生活隨筆網站

將公開 Telegram 頻道 **[@mark11blog](https://t.me/mark11blog)** 的內容自動同步並呈現為個人靜態部落格 / 數位花園。

## 功能特色

- **零依賴純 Python 同步引擎**（[`scripts/sync_telegram.py`](scripts/sync_telegram.py)）：
  - 支援完整歷史回溯（`--full`）與日常增量同步（自動捕捉最新貼文、編輯紀錄與瀏覽／反應數）。
  - 完整解析純文字格式（粗體、斜體、程式碼區塊、引用、劇透遮罩、`#標籤`）、多圖相簿、影片、檔案附件、轉發來源、回覆引用與網頁連結預覽。
  - 自動產生結構化 `data/posts.json`、`data/site.json`、標準 RSS 訂閱 [`feed.xml`](feed.xml) 與 SEO `sitemap.xml`。
- **閱讀體驗設計**：
  - 溫暖紙本筆記質感（支援淺色 / 深色主題一鍵切換）。
  - 依日期分組的時間軸、**相片牆**專區、即時全文搜尋（快捷鍵 `/`）、月份歸檔、標籤過濾、圖片燈箱檢視、單則貼文獨立分享連結（`?post=1053`）以及「隨機回顧」功能。

---

## 如何自動將 Telegram 內容轉到這個個人網站？

本專案提供兩種自動化方式（可單獨使用或搭配使用）：

### 方案一：GitHub Actions 定時自動同步（零設定、免費、免 Bot Token）

> 原理：公開 Telegram 頻道均有官方網頁預覽 `https://t.me/s/mark11blog`，不需要伺服器或 Bot Token 即可自動抓取。

1. 將此專案推送到你的 GitHub 倉庫（例如 `mark11blog`）。
2. 到 GitHub 倉庫的 **Settings → Pages**，將 **Source** 設為 **GitHub Actions**。
3. 到 **Settings → Actions → General → Workflow permissions**，確認已勾選 **Read and write permissions**（讓 Actions 可以把新同步到的 `data/posts.json` 寫回倉庫）。
4. 完成！內建的 [`.github/workflows/sync-and-deploy.yml`](.github/workflows/sync-and-deploy.yml) 會每 **30 分鐘**自動同步一次新貼文並重新部署網站，你隨時也能到 **Actions** 頁面手動按下 **Run workflow** 立即同步。

### 方案二：Telegram Bot + Cloudflare Worker 即時同步（發文 30 秒內更新）

若你不想等 30 分鐘排程，希望在頻道發完訊息就立刻更新網站：

1. 在 Telegram 透過 `@BotFather` 建立一個機器人，將它加入 `@mark11blog` 並設為**管理員**（只需發佈/讀取訊息權限）。
2. 將 [`worker/telegram-webhook.js`](worker/telegram-webhook.js) 部署到 Cloudflare Workers，並設定環境變數：
   - `TG_WEBHOOK_SECRET`：自訂安全密碼
   - `CHANNEL_USERNAME`：`mark11blog`
   - `GITHUB_OWNER`：你的 GitHub 用戶名
   - `GITHUB_REPO`：這個倉庫名稱
   - `GITHUB_TOKEN`：具有 `repo`（或 Fine-grained token 的 `Actions: write` + `Contents: read`）權限的 Token
3. 呼叫 Telegram API 設定 Webhook：
   ```bash
   curl -X POST "https://api.telegram.org/bot<你的BOT_TOKEN>/setWebhook" \
     -d "url=https://<你的WORKER網址>/" \
     -d "secret_token=<你的TG_WEBHOOK_SECRET>" \
     -d 'allowed_updates=["channel_post","edited_channel_post"]'
   ```
4. 之後只要在頻道發新貼文或修改舊貼文，Worker 就會透過 `repository_dispatch` 立即觸發 GitHub Actions 同步並部署！

---

## 本機手動同步與預覽

```bash
# 增量同步（更新最新幾頁與近期編輯）
python3 scripts/sync_telegram.py --channel mark11blog --root .

# 完整重新抓取整個頻道歷史
python3 scripts/sync_telegram.py --channel mark11blog --root . --full

# 若希望把圖片與貼圖也下載備份到本機 media/ 目錄（防止外連失效）
python3 scripts/sync_telegram.py --channel mark11blog --root . --download-media

# 本機啟動靜態伺服器預覽
python3 -m http.server 8080
```
