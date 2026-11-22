/**
 * Cloudflare Worker: Telegram Channel (@mark014blog) -> GitHub Actions 即時觸發橋接器
 *
 * 運作流程：
 * 1. Telegram Bot 收到頻道新貼文 (channel_post) 或編輯 (edited_channel_post) 後毫秒級推送到此 Worker
 * 2. Worker 驗證 X-Telegram-Bot-Api-Secret-Token 與頻道來源
 * 3. 呼叫 GitHub repository_dispatch API 立即喚醒 marker1111014/mark014blog 的自動同步部署流程
 *
 * Cloudflare Worker 只需設定 2 個 Secret（其餘已有預設值）：
 * - GITHUB_TOKEN      : 具備此倉庫 Contents/Actions 權限的 GitHub Personal Access Token
 * - TG_WEBHOOK_SECRET : 自訂隨機密碼（與 Telegram setWebhook 的 secret_token 一致）
 *
 * 可選變數（預設已對應本專案）：
 * - CHANNEL_USERNAME  : mark014blog
 * - GITHUB_OWNER      : marker1111014
 * - GITHUB_REPO       : mark014blog
 */

export default {
  async fetch(request, env) {
    const channelUsername = (env.CHANNEL_USERNAME || 'mark014blog').replace(/^@/, '').toLowerCase();
    const githubOwner = env.GITHUB_OWNER || 'marker1111014';
    const githubRepo = env.GITHUB_REPO || 'mark014blog';

    if (request.method === 'GET') {
      return Response.json({
        ok: true,
        service: 'mark014blog Telegram -> GitHub Webhook Bridge',
        channel: `@${channelUsername}`,
        target_repo: `${githubOwner}/${githubRepo}`,
        configured: {
          github_token: Boolean(env.GITHUB_TOKEN),
          webhook_secret: Boolean(env.TG_WEBHOOK_SECRET),
        },
      });
    }

    if (request.method !== 'POST') {
      return new Response('Method Not Allowed', { status: 405 });
    }

    if (env.TG_WEBHOOK_SECRET) {
      const secretHeader = request.headers.get('X-Telegram-Bot-Api-Secret-Token');
      if (secretHeader !== env.TG_WEBHOOK_SECRET) {
        return new Response('Unauthorized', { status: 401 });
      }
    }

    if (!env.GITHUB_TOKEN) {
      return new Response('Missing GITHUB_TOKEN secret in Worker environment', { status: 500 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response('Bad Request', { status: 400 });
    }

    const post = update.channel_post || update.edited_channel_post;
    if (!post) {
      return Response.json({ ok: true, skipped: 'not_channel_post' });
    }

    const actualChannel = (post.chat?.username || '').toLowerCase();
    if (actualChannel && actualChannel !== channelUsername) {
      return Response.json({ ok: true, skipped: 'other_channel', actualChannel });
    }

    const dispatchUrl = `https://api.github.com/repos/${githubOwner}/${githubRepo}/dispatches`;
    const ghRes = await fetch(dispatchUrl, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'mark014blog-tg-bridge',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        event_type: 'telegram-update',
        client_payload: {
          message_id: post.message_id || 0,
          edited: Boolean(update.edited_channel_post),
          media_group_id: post.media_group_id || null,
        },
      }),
    });

    if (!ghRes.ok) {
      const errText = await ghRes.text();
      return new Response(`GitHub dispatch failed: ${ghRes.status} ${errText}`, { status: 502 });
    }

    return Response.json({
      ok: true,
      dispatched: true,
      message_id: post.message_id || 0,
      edited: Boolean(update.edited_channel_post),
    });
  },
};
