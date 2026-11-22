/**
 * Cloudflare Worker: Telegram Channel -> GitHub Actions 即時觸發橋接器
 *
 * 適用情境：希望在 @mark11blog 發完或編輯訊息後 30 秒內自動更新個人網站，
 * 不必等待 GitHub Actions 的 30 分鐘排程。
 *
 * 環境變數 (Cloudflare Worker Secrets / Variables)：
 * - TG_WEBHOOK_SECRET : 自訂隨機字串，設定 Telegram setWebhook 的 secret_token
 * - CHANNEL_USERNAME  : 頻道用戶名（例如 mark11blog）
 * - GITHUB_OWNER      : GitHub 帳號名稱（例如 marker1111014）
 * - GITHUB_REPO       : 網站倉庫名稱（例如 mark11blog）
 * - GITHUB_TOKEN      : 具備 repo / actions:write 權限的 GitHub Personal Access Token
 */

export default {
  async fetch(request, env) {
    if (request.method !== 'POST') {
      return new Response('OK - Telegram Webhook Bridge', { status: 200 });
    }

    if (env.TG_WEBHOOK_SECRET) {
      const secretHeader = request.headers.get('X-Telegram-Bot-Api-Secret-Token');
      if (secretHeader !== env.TG_WEBHOOK_SECRET) {
        return new Response('Unauthorized', { status: 401 });
      }
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response('Bad Request', { status: 400 });
    }

    const post = update.channel_post || update.edited_channel_post;
    if (!post) {
      return new Response('Ignored (not a channel post)', { status: 200 });
    }

    const expectedChannel = (env.CHANNEL_USERNAME || 'mark11blog').toLowerCase();
    const actualChannel = (post.chat?.username || '').toLowerCase();
    if (actualChannel && actualChannel !== expectedChannel) {
      return new Response('Ignored (other channel)', { status: 200 });
    }

    const dispatchUrl = `https://api.github.com/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/dispatches`;
    const ghRes = await fetch(dispatchUrl, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'mark11blog-tg-bridge',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        event_type: 'telegram-update',
        client_payload: {
          message_id: post.message_id,
          edited: Boolean(update.edited_channel_post),
        },
      }),
    });

    if (!ghRes.ok) {
      const errText = await ghRes.text();
      return new Response(`GitHub dispatch failed: ${ghRes.status} ${errText}`, { status: 502 });
    }

    return new Response('Dispatched sync workflow', { status: 200 });
  },
};
