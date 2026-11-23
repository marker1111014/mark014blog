(() => {
  'use strict';

  const BATCH_SIZE = 24;
  const WEEKDAYS = ['週日', '週一', '週二', '週三', '週四', '週五', '週六'];

  const state = {
    site: null,
    allPosts: [],
    filteredPosts: [],
    galleryItems: [],
    filter: 'all', // all | original | gallery
    tag: null,
    search: '',
    sort: 'desc', // desc | asc
    renderedCount: 0,
    lightboxItems: [],
    lightboxIndex: 0,
  };

  const els = {
    avatar: document.getElementById('profile-avatar'),
    title: document.getElementById('site-title'),
    handle: document.getElementById('channel-handle'),
    bio: document.getElementById('profile-bio'),
    viewFilters: document.getElementById('view-filters'),
    searchInput: document.getElementById('search-input'),
    searchClear: document.getElementById('search-clear'),
    sortToggle: document.getElementById('sort-toggle'),
    sortLabel: document.getElementById('sort-label'),
    activeFilterBar: document.getElementById('active-filter-bar'),
    activeFilterText: document.getElementById('active-filter-text'),
    clearFiltersBtn: document.getElementById('clear-filters-btn'),
    feedContainer: document.getElementById('feed-container'),
    loadMoreWrap: document.getElementById('load-more-wrap'),
    loadMoreBtn: document.getElementById('load-more-btn'),
    backToTop: document.getElementById('back-to-top'),
    themeToggle: document.getElementById('theme-toggle'),
    themeLabel: document.getElementById('theme-label'),
    mobileFilterToggle: document.getElementById('mobile-filter-toggle'),
    sidebarCollapsible: document.getElementById('sidebar-collapsible'),
    lightbox: document.getElementById('lightbox'),
    lightboxBackdrop: document.getElementById('lightbox-backdrop'),
    lightboxClose: document.getElementById('lightbox-close'),
    lightboxPrev: document.getElementById('lightbox-prev'),
    lightboxNext: document.getElementById('lightbox-next'),
    lightboxImg: document.getElementById('lightbox-img'),
    lightboxCaption: document.getElementById('lightbox-caption'),
    postModal: document.getElementById('post-modal'),
    postModalTitle: document.getElementById('post-modal-title'),
    postModalBody: document.getElementById('post-modal-body'),
    toast: document.getElementById('toast'),
  };

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatDateHeading(dateLocal) {
    if (!dateLocal) return '未知日期';
    const [datePart] = dateLocal.split(' ');
    const [y, m, d] = datePart.split('-').map(Number);
    if (!y || !m || !d) return datePart;
    const dt = new Date(y, m - 1, d);
    const weekday = WEEKDAYS[dt.getDay()] || '';
    return `${y} 年 ${m} 月 ${d} 日 · ${weekday}`;
  }

  function formatTimePart(dateLocal) {
    if (!dateLocal) return '';
    const parts = dateLocal.split(' ');
    return parts[1] || '';
  }

  let toastTimer = null;
  function showToast(msg) {
    if (!els.toast) return;
    els.toast.textContent = msg;
    els.toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      els.toast.hidden = true;
    }, 2200);
  }

  function updateThemeUI() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    els.themeLabel.textContent = isDark ? '淺色' : '深色';
  }

  function toggleTheme() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    const next = isDark ? 'light' : 'dark';
    if (next === 'dark') {
      document.documentElement.setAttribute('data-theme', 'dark');
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
    try {
      localStorage.setItem('mark014blog-theme', next);
    } catch {}
    updateThemeUI();
  }

  function mediaUrl(item, key = 'url', localKey = 'local_url') {
    if (!item) return '';
    return item[localKey] || item[key] || '';
  }

  function isRedundantUrlOnlyText(post) {
    if (!post.link_preview || !post.link_preview.url || !post.text) return false;
    const cleanText = post.text.trim().replace(/\/+$/, '');
    const cleanLp = post.link_preview.url.trim().replace(/\/+$/, '');
    return cleanText === cleanLp;
  }

  function renderMediaGrid(post) {
    const photos = post.photos || [];
    if (!photos.length) return '';

    const cls =
      photos.length === 1
        ? 'cols-1'
        : photos.length === 2
        ? 'cols-2'
        : photos.length === 3
        ? 'cols-3'
        : 'cols-many';

    const itemsHtml = photos
      .map((ph, idx) => {
        const src = escapeHtml(mediaUrl(ph));
        const alt = escapeHtml((post.text || `貼文 #${post.id}`).slice(0, 40));
        return `
          <button
            type="button"
            class="media-item"
            data-lightbox-post="${post.id}"
            data-lightbox-index="${idx}"
            aria-label="放大檢視第 ${idx + 1} 張圖片"
          >
            <img src="${src}" alt="${alt}" loading="lazy" referrerpolicy="no-referrer">
          </button>
        `;
      })
      .join('');

    return `<div class="media-grid ${cls}">${itemsHtml}</div>`;
  }

  function renderVideos(post) {
    const videos = post.videos || [];
    if (!videos.length) return '';
    return videos
      .map((v) => {
        const src = escapeHtml(mediaUrl(v, 'url', 'local_url'));
        const thumb = escapeHtml(mediaUrl(v, 'thumb', 'local_thumb'));
        const tgUrl = escapeHtml(post.url);
        const dur = v.duration ? ` (${escapeHtml(v.duration)})` : '';

        if (!src) {
          return `
            <div class="video-wrap">
              <a class="video-fallback-card" href="${tgUrl}" target="_blank" rel="noopener noreferrer">
                ${thumb ? `<img src="${thumb}" alt="影片縮圖" loading="lazy" referrerpolicy="no-referrer">` : ''}
                <div class="video-play-overlay">
                  <div class="video-play-circle">▶</div>
                  <span class="video-overlay-label">前往 Telegram 觀看影片${dur} ↗</span>
                </div>
              </a>
            </div>
          `;
        }

        return `
          <div class="video-wrap" data-tg-url="${tgUrl}" data-thumb="${thumb}" data-dur="${escapeHtml(v.duration || '')}">
            <video
              controls
              playsinline
              preload="none"
              ${thumb ? `poster="${thumb}"` : ''}
              src="${src}"
            ></video>
          </div>
        `;
      })
      .join('');
  }

  function renderStickers(post) {
    const stickers = post.stickers || [];
    if (!stickers.length) return '';
    return stickers
      .map((s) => {
        const src = escapeHtml(mediaUrl(s));
        return `
          <div class="sticker-wrap">
            <img src="${src}" alt="Telegram 貼圖" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.style.display='none'">
          </div>
        `;
      })
      .join('');
  }

  function renderDocuments(post) {
    const docs = post.documents || [];
    if (!docs.length) return '';
    return docs
      .map(
        (d) => `
      <a class="doc-card" href="${escapeHtml(d.url || post.url)}" target="_blank" rel="noopener noreferrer">
        <div class="doc-icon">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/></svg>
        </div>
        <div class="doc-meta">
          <div class="doc-title">${escapeHtml(d.title)}</div>
          ${d.extra ? `<div class="doc-extra">${escapeHtml(d.extra)} · 前往 Telegram 下載 ↗</div>` : '<div class="doc-extra">前往 Telegram 查看檔案 ↗</div>'}
        </div>
      </a>
    `
      )
      .join('');
  }

  function renderLinkPreview(post) {
    const lp = post.link_preview;
    if (!lp || !lp.url) return '';

    if (lp.telegraph_html) {
      const isLong = (lp.telegraph_len || 0) > 480 || (lp.telegraph_imgs || 0) > 2;
      return `
        <div class="telegraph-card">
          <div class="telegraph-header">
            <div class="telegraph-meta">
              <span class="lp-site">Telegraph</span>
              ${lp.telegraph_author ? `<span class="telegraph-author">· ${escapeHtml(lp.telegraph_author)}</span>` : ''}
            </div>
            <a class="telegraph-ext" href="${escapeHtml(lp.url)}" target="_blank" rel="noopener noreferrer">開啟原文 ↗</a>
          </div>
          ${lp.title ? `<h4 class="telegraph-title"><a href="${escapeHtml(lp.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(lp.title)}</a></h4>` : ''}
          <div class="telegraph-body ${isLong ? 'is-collapsed' : ''}">
            ${lp.telegraph_html}
          </div>
          ${isLong ? '<button type="button" class="telegraph-toggle" data-toggle-telegraph>展開全文 ▾</button>' : ''}
        </div>
      `;
    }

    const thumb = escapeHtml(lp.local_image || lp.image || '');
    return `
      <a class="link-preview-card" href="${escapeHtml(lp.url)}" target="_blank" rel="noopener noreferrer">
        <div class="lp-content">
          ${lp.site_name ? `<div class="lp-site">${escapeHtml(lp.site_name)}</div>` : ''}
          ${lp.title ? `<div class="lp-title">${escapeHtml(lp.title)}</div>` : ''}
          ${lp.description ? `<div class="lp-desc">${escapeHtml(lp.description)}</div>` : ''}
        </div>
        ${thumb ? `<img class="lp-thumb" src="${thumb}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none'">` : ''}
      </a>
    `;
  }

  function renderForwarded(post) {
    const fwd = post.forwarded_from;
    if (!fwd) return '';
    const parts = [];
    if (fwd.name) {
      parts.push(
        fwd.url
          ? `<a href="${escapeHtml(fwd.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(fwd.name)}</a>`
          : `<span>${escapeHtml(fwd.name)}</span>`
      );
    }
    if (fwd.author) {
      parts.push(`<span>${escapeHtml(fwd.author)}</span>`);
    }
    const label = parts.join(' · ') || '其他頻道';
    return `<div class="forwarded-line">↪ 轉發自 ${label}</div>`;
  }

  function renderReply(post) {
    const rep = post.reply_to;
    if (!rep) return '';
    return `
      <a class="reply-box" href="${escapeHtml(rep.url || post.url)}" target="_blank" rel="noopener noreferrer">
        ${rep.thumb ? `<img class="reply-thumb" src="${escapeHtml(rep.thumb)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.style.display='none'">` : ''}
        <div class="reply-body">
          ${rep.author ? `<div class="reply-author">回覆 ${escapeHtml(rep.author)}</div>` : '<div class="reply-author">回覆貼文</div>'}
          <div class="reply-text">${escapeHtml(rep.text || '查看原始訊息')}</div>
        </div>
      </a>
    `;
  }

  function renderPostCard(post, inModal = false) {
    const timeStr = inModal ? escapeHtml(post.date_local || '') : escapeHtml(formatTimePart(post.date_local));
    const reactionsHtml = (post.reactions || [])
      .map((r) => `<span class="reaction-pill">${escapeHtml(r.emoji)} ${escapeHtml(String(r.count))}</span>`)
      .join('');

    const showText = post.text_html && !isRedundantUrlOnlyText(post);
    const textHtml = showText ? `<div class="post-text">${post.text_html}</div>` : '';

    return `
      <article class="post-card" data-post-id="${post.id}">
        <header class="post-header">
          <div class="post-meta-left">
            <button type="button" class="post-time-btn" data-open-post="${post.id}" title="專注閱讀此貼文">
              <time class="post-time" datetime="${escapeHtml(post.datetime)}">${timeStr}</time>
            </button>
            ${renderForwarded(post)}
          </div>
        </header>

        ${renderReply(post)}
        ${renderMediaGrid(post)}
        ${renderVideos(post)}
        ${renderStickers(post)}
        ${renderDocuments(post)}
        ${textHtml}
        ${renderLinkPreview(post)}

        <footer class="post-footer">
          <div class="post-footer-left">
            ${reactionsHtml}
          </div>
          <div class="post-footer-actions">
            <button type="button" class="card-action-btn" data-copy-post="${post.id}" title="複製分享連結">分享</button>
            <a class="card-tg-link" href="${escapeHtml(post.url)}" target="_blank" rel="noopener noreferrer">原文 ↗</a>
          </div>
        </footer>
      </article>
    `;
  }

  function applyFilters() {
    const q = state.search.trim().toLowerCase();
    let list = state.allPosts.filter((p) => {
      if (state.filter === 'original' && p.forwarded_from) return false;
      if (state.filter === 'gallery' && !p.photos.length) return false;
      if (state.tag && !(p.tags || []).some((t) => t.toLowerCase() === state.tag.toLowerCase())) return false;

      if (q) {
        const hay = [
          p.text || '',
          p.link_preview ? `${p.link_preview.title} ${p.link_preview.description} ${p.link_preview.site_name}` : '',
          p.forwarded_from ? `${p.forwarded_from.name} ${p.forwarded_from.author}` : '',
          (p.tags || []).join(' '),
        ]
          .join(' ')
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    list = list.slice().sort((a, b) => (state.sort === 'desc' ? b.id - a.id : a.id - b.id));
    state.filteredPosts = list;

    if (state.filter === 'gallery') {
      const imgs = [];
      for (const p of list) {
        (p.photos || []).forEach((ph) => {
          imgs.push({
            src: mediaUrl(ph),
            caption: `${p.date_local || ''} · ${(p.text || '').slice(0, 100)}`.trim(),
            postId: p.id,
            postUrl: p.url,
          });
        });
      }
      state.galleryItems = imgs;
    } else {
      state.galleryItems = [];
    }

    state.renderedCount = 0;
    renderActiveFilterBanner();
    renderFeed(false);
  }

  function renderActiveFilterBanner() {
    const chips = [];
    if (state.tag) chips.push(`標籤：#${state.tag}`);
    if (state.search.trim()) chips.push(`搜尋：「${state.search.trim()}」`);

    if (!chips.length) {
      els.activeFilterBar.hidden = true;
      return;
    }

    const total = state.filter === 'gallery' ? state.galleryItems.length : state.filteredPosts.length;
    const unit = state.filter === 'gallery' ? '張照片' : '則貼文';
    els.activeFilterText.textContent = `${chips.join(' · ')}（${total} ${unit}）`;
    els.activeFilterBar.hidden = false;
  }

  function renderFeed(append) {
    if (state.filter === 'gallery') {
      renderGallery(append);
      return;
    }

    const posts = state.filteredPosts;
    if (!posts.length) {
      els.feedContainer.innerHTML = `
        <div class="empty-state">
          <p>找不到符合條件的貼文。</p>
          <button type="button" class="clear-filters-btn" id="empty-reset-btn">清除篩選</button>
        </div>
      `;
      document.getElementById('empty-reset-btn')?.addEventListener('click', resetFilters);
      els.loadMoreWrap.hidden = true;
      return;
    }

    const start = append ? state.renderedCount : 0;
    const end = Math.min(start + BATCH_SIZE, posts.length);
    const slice = posts.slice(start, end);

    let lastDate = append && start > 0 ? (posts[start - 1].date_local || '').split(' ')[0] : null;
    const htmlParts = [];

    for (const p of slice) {
      const dateOnly = (p.date_local || '').split(' ')[0];
      if (dateOnly && dateOnly !== lastDate) {
        htmlParts.push(`<div class="date-group-header">${escapeHtml(formatDateHeading(p.date_local))}</div>`);
        lastDate = dateOnly;
      }
      htmlParts.push(renderPostCard(p));
    }

    if (append) {
      els.feedContainer.insertAdjacentHTML('beforeend', htmlParts.join(''));
    } else {
      els.feedContainer.innerHTML = htmlParts.join('');
    }

    attachVideoFallbacks(els.feedContainer);
    state.renderedCount = end;

    const remaining = posts.length - end;
    if (remaining > 0) {
      els.loadMoreWrap.hidden = false;
      els.loadMoreBtn.textContent = `載入更多（還有 ${remaining} 則）`;
    } else {
      els.loadMoreWrap.hidden = true;
    }
  }

  function renderGallery(append) {
    const items = state.galleryItems;
    if (!items.length) {
      els.feedContainer.innerHTML = `<div class="empty-state"><p>此篩選條件下沒有圖片。</p></div>`;
      els.loadMoreWrap.hidden = true;
      return;
    }

    const batch = BATCH_SIZE + 12;
    const start = append ? state.renderedCount : 0;
    const end = Math.min(start + batch, items.length);
    const slice = items.slice(start, end);

    const tilesHtml = slice
      .map(
        (item, offset) => `
      <button
        type="button"
        class="gallery-tile"
        data-gallery-index="${start + offset}"
        aria-label="檢視圖片 #${item.postId}"
      >
        <img src="${escapeHtml(item.src)}" alt="${escapeHtml(item.caption)}" loading="lazy" referrerpolicy="no-referrer">
        <div class="gallery-tile-overlay">${escapeHtml(item.caption || '')}</div>
      </button>
    `
      )
      .join('');

    if (append && els.feedContainer.querySelector('.gallery-grid')) {
      els.feedContainer.querySelector('.gallery-grid').insertAdjacentHTML('beforeend', tilesHtml);
    } else {
      els.feedContainer.innerHTML = `<div class="gallery-grid">${tilesHtml}</div>`;
    }

    state.renderedCount = end;
    const remaining = items.length - end;
    if (remaining > 0) {
      els.loadMoreWrap.hidden = false;
      els.loadMoreBtn.textContent = `載入更多相片（還有 ${remaining} 張）`;
    } else {
      els.loadMoreWrap.hidden = true;
    }
  }

  function attachVideoFallbacks(container) {
    container.querySelectorAll('.video-wrap video').forEach((video) => {
      if (video.dataset.bound) return;
      video.dataset.bound = '1';
      video.addEventListener('error', () => {
        const wrap = video.closest('.video-wrap');
        if (!wrap) return;
        const tgUrl = wrap.dataset.tgUrl || 'https://t.me/mark014blog';
        const thumb = wrap.dataset.thumb || '';
        const dur = wrap.dataset.dur ? ` (${wrap.dataset.dur})` : '';
        wrap.innerHTML = `
          <a class="video-fallback-card" href="${escapeHtml(tgUrl)}" target="_blank" rel="noopener noreferrer">
            ${thumb ? `<img src="${escapeHtml(thumb)}" alt="影片縮圖" referrerpolicy="no-referrer">` : ''}
            <div class="video-play-overlay">
              <div class="video-play-circle">▶</div>
              <span class="video-overlay-label">Telegram 影片連結已過期，點擊前往原貼文觀看${escapeHtml(dur)} ↗</span>
            </div>
          </a>
        `;
      });
    });
  }

  function renderSidebar() {
    const s = state.site;
    if (!s) return;

    if (s.title) els.title.textContent = s.title;
    if (s.username) els.handle.textContent = s.username;
    if (s.url) els.handle.href = s.url;
    if (s.description_html) els.bio.innerHTML = s.description_html;
    if (s.avatar_local || s.avatar_url) {
      els.avatar.src = s.avatar_local || s.avatar_url;
    }
  }

  function syncSidebarButtons() {
    els.viewFilters.querySelectorAll('.filter-btn').forEach((btn) => {
      btn.classList.toggle('active', btn.dataset.filter === state.filter);
    });
  }

  function resetFilters() {
    state.filter = 'all';
    state.tag = null;
    state.search = '';
    els.searchInput.value = '';
    els.searchClear.hidden = true;
    syncSidebarButtons();
    applyFilters();
  }

  function openLightbox(items, index) {
    if (!items || !items.length) return;
    state.lightboxItems = items;
    state.lightboxIndex = Math.max(0, Math.min(index, items.length - 1));
    updateLightboxView();
    els.lightbox.hidden = false;
    document.body.style.overflow = 'hidden';
  }

  function updateLightboxView() {
    const item = state.lightboxItems[state.lightboxIndex];
    if (!item) return;
    els.lightboxImg.src = item.src;
    const counter = state.lightboxItems.length > 1 ? `[${state.lightboxIndex + 1}/${state.lightboxItems.length}] ` : '';
    els.lightboxCaption.textContent = `${counter}${item.caption || ''}`;
    const showNav = state.lightboxItems.length > 1;
    els.lightboxPrev.hidden = !showNav;
    els.lightboxNext.hidden = !showNav;
  }

  function closeLightbox() {
    els.lightbox.hidden = true;
    els.lightboxImg.src = '';
    document.body.style.overflow = '';
  }

  function openPostModal(postId) {
    const post = state.allPosts.find((p) => p.id === Number(postId));
    if (!post) return;
    els.postModalTitle.textContent = formatDateHeading(post.date_local);
    els.postModalBody.innerHTML = renderPostCard(post, true);
    attachVideoFallbacks(els.postModalBody);
    els.postModal.hidden = false;
    document.body.style.overflow = 'hidden';

    const url = new URL(window.location.href);
    url.searchParams.set('post', String(post.id));
    history.replaceState(null, '', url.toString());
  }

  function closeModal(modalEl) {
    if (!modalEl) return;
    modalEl.hidden = true;
    if (els.lightbox.hidden && els.postModal.hidden) {
      document.body.style.overflow = '';
    }
    if (modalEl === els.postModal) {
      const url = new URL(window.location.href);
      if (url.searchParams.has('post')) {
        url.searchParams.delete('post');
        history.replaceState(null, '', url.toString());
      }
    }
  }

  function copyPostLink(postId) {
    const url = new URL(window.location.href);
    url.searchParams.set('post', String(postId));
    const link = url.toString();
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(link).then(
        () => showToast('已複製分享連結'),
        () => showToast(link)
      );
    } else {
      showToast(link);
    }
  }

  function bindEvents() {
    els.themeToggle.addEventListener('click', toggleTheme);

    els.mobileFilterToggle?.addEventListener('click', () => {
      const open = els.sidebarCollapsible.classList.toggle('open');
      els.mobileFilterToggle.setAttribute('aria-expanded', String(open));
    });

    els.viewFilters.addEventListener('click', (e) => {
      const btn = e.target.closest('.filter-btn');
      if (!btn) return;
      state.filter = btn.dataset.filter || 'all';
      syncSidebarButtons();
      applyFilters();
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });

    let searchTimer = null;
    els.searchInput.addEventListener('input', () => {
      const val = els.searchInput.value;
      els.searchClear.hidden = !val;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.search = val;
        applyFilters();
      }, 150);
    });

    els.searchClear.addEventListener('click', () => {
      els.searchInput.value = '';
      els.searchClear.hidden = true;
      state.search = '';
      applyFilters();
      els.searchInput.focus();
    });

    els.sortToggle.addEventListener('click', () => {
      state.sort = state.sort === 'desc' ? 'asc' : 'desc';
      els.sortLabel.textContent = state.sort === 'desc' ? '最新' : '最舊';
      applyFilters();
    });

    els.clearFiltersBtn.addEventListener('click', resetFilters);
    els.loadMoreBtn.addEventListener('click', () => renderFeed(true));

    document.addEventListener('click', (e) => {
      const spoiler = e.target.closest('.tg-spoiler');
      if (spoiler) {
        spoiler.classList.toggle('revealed');
        return;
      }

      const inlineTag = e.target.closest('.inline-tag');
      if (inlineTag) {
        const tag = inlineTag.dataset.tag;
        if (tag) {
          closeModal(els.postModal);
          state.tag = tag;
          applyFilters();
          window.scrollTo({ top: 0, behavior: 'smooth' });
        }
        return;
      }

      const openPostBtn = e.target.closest('[data-open-post]');
      if (openPostBtn) {
        openPostModal(openPostBtn.dataset.openPost);
        return;
      }

      const copyBtn = e.target.closest('[data-copy-post]');
      if (copyBtn) {
        copyPostLink(copyBtn.dataset.copyPost);
        return;
      }

      const lbBtn = e.target.closest('[data-lightbox-post]');
      if (lbBtn) {
        const pid = Number(lbBtn.dataset.lightboxPost);
        const idx = Number(lbBtn.dataset.lightboxIndex || 0);
        const post = state.allPosts.find((p) => p.id === pid);
        if (post && post.photos?.length) {
          const items = post.photos.map((ph) => ({
            src: mediaUrl(ph),
            caption: `${post.date_local || ''} · ${(post.text || '').slice(0, 100)}`.trim(),
          }));
          openLightbox(items, idx);
        }
        return;
      }

      const galTile = e.target.closest('[data-gallery-index]');
      if (galTile) {
        const idx = Number(galTile.dataset.galleryIndex || 0);
        openLightbox(state.galleryItems, idx);
        return;
      }

      const tgToggle = e.target.closest('[data-toggle-telegraph]');
      if (tgToggle) {
        const card = tgToggle.closest('.telegraph-card');
        const body = card?.querySelector('.telegraph-body');
        if (body) {
          const collapsed = body.classList.toggle('is-collapsed');
          tgToggle.textContent = collapsed ? '展開全文 ▾' : '收起全文 ▴';
        }
        return;
      }

      const tgImg = e.target.closest('.telegraph-body img');
      if (tgImg) {
        const card = tgImg.closest('.telegraph-card');
        const imgs = Array.from(card?.querySelectorAll('.telegraph-body img') || []);
        const idx = Math.max(0, imgs.indexOf(tgImg));
        const title = card?.querySelector('.telegraph-title')?.textContent?.trim() || '';
        openLightbox(
          imgs.map((img) => ({ src: img.src, caption: title })),
          idx
        );
        return;
      }

      const closeTarget = e.target.closest('[data-close-modal]');
      if (closeTarget) {
        closeModal(document.getElementById(closeTarget.dataset.closeModal));
      }
    });

    els.lightboxBackdrop.addEventListener('click', closeLightbox);
    els.lightboxClose.addEventListener('click', closeLightbox);
    els.lightboxPrev.addEventListener('click', () => {
      state.lightboxIndex = (state.lightboxIndex - 1 + state.lightboxItems.length) % state.lightboxItems.length;
      updateLightboxView();
    });
    els.lightboxNext.addEventListener('click', () => {
      state.lightboxIndex = (state.lightboxIndex + 1) % state.lightboxItems.length;
      updateLightboxView();
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === '/' && document.activeElement !== els.searchInput && els.lightbox.hidden && els.postModal.hidden) {
        e.preventDefault();
        els.searchInput.focus();
      } else if (e.key === 'Escape') {
        if (!els.lightbox.hidden) closeLightbox();
        else if (!els.postModal.hidden) closeModal(els.postModal);
      } else if (!els.lightbox.hidden) {
        if (e.key === 'ArrowLeft' && state.lightboxItems.length > 1) {
          state.lightboxIndex = (state.lightboxIndex - 1 + state.lightboxItems.length) % state.lightboxItems.length;
          updateLightboxView();
        } else if (e.key === 'ArrowRight' && state.lightboxItems.length > 1) {
          state.lightboxIndex = (state.lightboxIndex + 1) % state.lightboxItems.length;
          updateLightboxView();
        }
      }
    });

    window.addEventListener('scroll', () => {
      els.backToTop.hidden = window.scrollY < 480;
    }, { passive: true });

    els.backToTop.addEventListener('click', () => {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    });
  }

  async function init() {
    updateThemeUI();
    bindEvents();

    try {
      const [siteRes, postsRes] = await Promise.all([
        fetch('data/site.json', { cache: 'no-cache' }),
        fetch('data/posts.json', { cache: 'no-cache' }),
      ]);
      if (!siteRes.ok || !postsRes.ok) {
        throw new Error('無法載入頻道資料');
      }
      const siteData = await siteRes.json();
      const postsData = await postsRes.json();

      state.site = siteData;
      state.allPosts = postsData.filter((p) => !p.is_service);

      renderSidebar();
      applyFilters();

      const params = new URLSearchParams(window.location.search);
      const targetPost = params.get('post');
      if (targetPost) {
        openPostModal(targetPost);
      }
    } catch (err) {
      els.feedContainer.innerHTML = `
        <div class="empty-state">
          <p>讀取貼文資料時發生錯誤：${escapeHtml(err.message)}</p>
        </div>
      `;
    }
  }

  init();
})();
