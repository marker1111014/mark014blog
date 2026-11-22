# Mark's Blog (`@mark014blog`) 個人生活隨筆網站

將公開 Telegram 頻道 **[@mark014blog](https://t.me/mark014blog)** 的內容即時同步並呈現為個人靜態部落格 / 數位花園。

- 網站倉庫：[marker1111014/mark014blog](https://github.com/marker1111014/mark014blog)
- GitHub Pages 網址：`https://marker1111014.github.io/mark014blog/`

---

## 方案二設定指南：Telegram Bot + Cloudflare Worker 毫秒級即時同步

專案採用「**Bot Webhook 即時觸發 + GitHub Actions 備援排程**」雙架構：發完或改完 Telegram 貼文後，Telegram 會在毫秒內通知 Cloudflare Worker，Worker 立刻喚醒 GitHub Actions 抓取最新貼文、產生 `data/posts.json` 與 `feed.xml` 並自動發佈到 GitHub Pages。

### 步驟 1：開啟 GitHub Pages 與 Actions 寫入權限

1. 進入倉庫 **Settings → Pages**，將 **Source** 設為 **GitHub Actions**。
2. 進入 **Settings → Actions → General → Workflow permissions**，勾選 **Read and write permissions** 後儲存。

### 步驟 2：建立 GitHub Token（供 Worker 觸發 Actions）

1. 前往 GitHub **Settings → Developer settings → Personal access tokens → Fine-grained tokens**。
2. **Repository access** 選擇 **Only select repositories → `marker1111014/mark014blog`**。
3. **Repository permissions** 只需要設定 **Contents: Read and write**（`repository_dispatch` 需要 Contents 寫入權限）。
4. 產生並記下這組 Token（以下稱 `GITHUB_TOKEN`）。

### 步驟 3：部署 Cloudflare Worker

可直接在 Cloudflare Dashboard 貼上 [`worker/telegram-webhook.js`](worker/telegram-webhook.js)，或在本機用 Wrangler CLI 部署：

```bash
cd worker
npx wrangler deploy
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret put TG_WEBHOOK_SECRET
```

> 若使用 Cloudflare Dashboard 貼上程式碼，程式內已預設 `mark014blog` 與 `marker1111014/mark014blog`，你只需在 **Settings → Variables and Secrets** 新增 `GITHUB_TOKEN` 與 `TG_WEBHOOK_SECRET`（自訂一串隨機英數字）即可。
> 部署後直接用瀏覽器打開 Worker 網址，看到 `"github_token": true, "webhook_secret": true` 即代表準備就緒！

### 步驟 4：建立 Telegram Bot 並綁定 Webhook

1. 在 Telegram 找 `@BotFather` 執行 `/newbot` 建立機器人，取得 `BOT_TOKEN`。
2. 打開頻道 `@mark014blog` → **Administrators（管理員）→ Add Admin**，將剛剛建立的機器人加為頻道管理員。
3. 執行以下指令綁定 Webhook（替換 `<BOT_TOKEN>`、`<WORKER_URL>`、`<TG_WEBHOOK_SECRET>`）：

```bash
curl -X POST "https://api.telegram.org/bot<BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "<WORKER_URL>",
    "secret_token": "<TG_WEBHOOK_SECRET>",
    "allowed_updates": ["channel_post", "edited_channel_post"]
  }'
```

完成後，只要你在 `@mark014blog` 發新訊息或修改訊息，Worker 就會立刻透過 `repository_dispatch` 觸發部署，約 25～40 秒後網站就會同步更新！同時 [`.github/workflows/sync-and-deploy.yml`](.github/workflows/sync-and-deploy.yml) 也會每 2 小時定時巡檢一次瀏覽數與表情反應。

---

## 本機手動同步與預覽

```bash
# 增量同步（更新最新幾頁與近期編輯）
python3 scripts/sync_telegram.py --channel mark014blog --root .

# 完整重新抓取整個頻道歷史
python3 scripts/sync_telegram.py --channel mark014blog --root . --full

# 若希望把圖片與貼圖也下載備份到本機 media/ 目錄
python3 scripts/sync_telegram.py --channel mark014blog --root . --download-media

# 本機啟動靜態伺服器預覽
python3 -m http.server 8080
```
