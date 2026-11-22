#!/usr/bin/env python3
"""
Telegram Public Channel -> Static Personal Website Sync Engine
Zero external dependencies (Python 3.9+ stdlib only).

Fetches posts from https://t.me/s/<channel>, parses rich text, photo albums,
videos, documents, stickers, link previews, replies, forwards, and reactions,
and generates data/site.json, data/posts.json, feed.xml, and sitemap.xml.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import html as html_lib
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape

# Force IPv4 to avoid sporadic IPv6 "Network is unreachable" on some runners/sandboxes
_ORIG_GETADDRINFO = socket.getaddrinfo


def _ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    return _ORIG_GETADDRINFO(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _ipv4_getaddrinfo

VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

ALLOWED_RICH_TAGS = {
    "a", "b", "strong", "i", "em", "u", "ins", "s", "del", "strike",
    "code", "pre", "blockquote", "br", "tg-spoiler", "span", "p",
}

TAIPEI_TZ = timezone(timedelta(hours=8))


class Node:
    __slots__ = ("tag", "attrs", "children", "text")

    def __init__(self, tag: Optional[str] = None, attrs: Optional[Dict[str, str]] = None, text: str = ""):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: List[Node] = []
        self.text = text

    def classes(self) -> List[str]:
        cls = self.attrs.get("class", "")
        return cls.split() if cls else []

    def has_class(self, name: str) -> bool:
        return name in self.classes()

    def find_all(self, predicate) -> List["Node"]:
        out: List[Node] = []
        if predicate(self):
            out.append(self)
        for ch in self.children:
            if ch.tag is not None:
                out.extend(ch.find_all(predicate))
        return out

    def find_first(self, predicate) -> Optional["Node"]:
        if predicate(self):
            return self
        for ch in self.children:
            if ch.tag is not None:
                found = ch.find_first(predicate)
                if found is not None:
                    return found
        return None

    def find_by_class(self, class_name: str, first: bool = False):
        pred = lambda n: n.tag is not None and n.has_class(class_name)
        return self.find_first(pred) if first else self.find_all(pred)

    def inner_text(self) -> str:
        if self.tag is None:
            return self.text
        if self.tag == "br":
            return "\n"
        return "".join(ch.inner_text() for ch in self.children)

    def render_rich_html(self) -> str:
        if self.tag is None:
            return html_lib.escape(self.text, quote=False)

        tag = self.tag.lower()
        if tag == "br":
            return "<br>"

        inner = "".join(ch.render_rich_html() for ch in self.children)

        if tag == "tg-spoiler" or (tag == "span" and self.has_class("tg-spoiler")):
            return f'<span class="tg-spoiler" tabindex="0" title="點擊顯示劇透">{inner}</span>'

        if tag == "a":
            href = self.attrs.get("href", "").strip()
            if href.startswith("?q=%23") or href.startswith("?q=#"):
                tag_text = self.inner_text().strip()
                clean_tag = tag_text.lstrip("#")
                return f'<button type="button" class="inline-tag" data-tag="{html_lib.escape(clean_tag)}">{html_lib.escape(tag_text)}</button>'
            if href.startswith("/"):
                href = "https://t.me" + href
            if not href:
                return inner
            safe_href = html_lib.escape(href, quote=True)
            return f'<a href="{safe_href}" target="_blank" rel="noopener noreferrer">{inner}</a>'

        if tag == "i" and self.has_class("emoji"):
            # Telegram custom emoji markup wraps the fallback emoji in <b>...</b>; return plain text
            return html_lib.escape(self.inner_text(), quote=False)

        if tag in ALLOWED_RICH_TAGS:
            if tag == "span":
                return inner
            return f"<{tag}>{inner}</{tag}>"

        return inner


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack: List[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = {k: (v if v is not None else "") for k, v in attrs}
        node = Node(tag.lower(), attr_dict)
        self.stack[-1].children.append(node)
        if tag.lower() not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        attr_dict = {k: (v if v is not None else "") for k, v in attrs}
        node = Node(tag.lower(), attr_dict)
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag: str):
        tag_l = tag.lower()
        for idx in range(len(self.stack) - 1, 0, -1):
            if self.stack[idx].tag == tag_l:
                del self.stack[idx:]
                break

    def handle_data(self, data: str):
        if data:
            self.stack[-1].children.append(Node(None, text=data))


def parse_html_tree(raw_html: str) -> Node:
    parser = TreeBuilder()
    parser.feed(raw_html)
    parser.close()
    return parser.root


def extract_bg_url(style: str) -> Optional[str]:
    if not style:
        return None
    m = re.search(r"background-image\s*:\s*url\(\s*(['\"]?)(.+?)\1\s*\)", style)
    if not m:
        return None
    url = html_lib.unescape(m.group(2).strip())
    if url.startswith("//"):
        url = "https:" + url
    return url


def extract_ratio(node: Node, fallback: Optional[float] = None) -> Optional[float]:
    dr = node.attrs.get("data-ratio")
    if dr:
        try:
            return round(float(dr), 4)
        except ValueError:
            pass
    style = node.attrs.get("style", "")
    m = re.search(r"padding-top\s*:\s*([0-9.]+)%", style)
    if m:
        try:
            pct = float(m.group(1))
            if pct > 0:
                return round(100.0 / pct, 4)
        except ValueError:
            pass
    return fallback


def parse_views_count(raw: str) -> Tuple[Optional[int], str]:
    txt = raw.strip()
    if not txt:
        return None, ""
    m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*([KMB])?$", txt, re.I)
    if not m:
        return None, txt
    num = float(m.group(1))
    suffix = (m.group(2) or "").upper()
    mult = {"": 1, "K": 1000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
    return int(round(num * mult)), txt


def extract_hashtags(text: str, text_node: Optional[Node]) -> List[str]:
    tags: List[str] = []
    seen = set()

    if text_node is not None:
        for a in text_node.find_all(lambda n: n.tag == "a"):
            href = a.attrs.get("href", "")
            if href.startswith("?q=%23") or href.startswith("?q=#"):
                t = a.inner_text().strip().lstrip("#")
                if t and t.lower() not in seen:
                    seen.add(t.lower())
                    tags.append(t)

    # Also catch plain #tags not inside URLs (including chrome://, about://, etc.)
    clean = re.sub(r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+", " ", text)
    for m in re.finditer(r"(?:^|[\s(（\[「『])#([\w\u4e00-\u9fff\u3040-\u30ff\-]{2,30})", clean):
        t = m.group(1)
        # Skip pure numeric or hex color codes
        if re.fullmatch(r"[0-9]+", t) or re.fullmatch(r"[0-9a-fA-F]{3,8}", t):
            continue
        if t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)

    return tags


def parse_channel_info(tree: Node, channel: str) -> Dict[str, Any]:
    info_node = tree.find_by_class("tgme_channel_info", first=True)
    title = channel
    username = f"@{channel}"
    avatar_url = None
    description_html = ""
    description_text = ""
    counters: Dict[str, str] = {}

    if info_node:
        t_node = info_node.find_by_class("tgme_channel_info_header_title", first=True)
        if t_node:
            title = t_node.inner_text().strip()
        u_node = info_node.find_by_class("tgme_channel_info_header_username", first=True)
        if u_node:
            username = u_node.inner_text().strip()
        photo_node = info_node.find_by_class("tgme_page_photo_image", first=True)
        if photo_node:
            img = photo_node.find_first(lambda n: n.tag == "img")
            if img and img.attrs.get("src"):
                avatar_url = img.attrs["src"]
        desc_node = info_node.find_by_class("tgme_channel_info_description", first=True)
        if desc_node:
            description_html = desc_node.render_rich_html()
            description_text = desc_node.inner_text().strip()
        for c_node in info_node.find_by_class("tgme_channel_info_counter"):
            val_node = c_node.find_by_class("counter_value", first=True)
            type_node = c_node.find_by_class("counter_type", first=True)
            if val_node and type_node:
                counters[type_node.inner_text().strip().lower()] = val_node.inner_text().strip()

    if not avatar_url:
        og_img = tree.find_first(lambda n: n.tag == "meta" and n.attrs.get("property") == "og:image")
        if og_img:
            avatar_url = og_img.attrs.get("content")

    return {
        "channel": channel,
        "title": title,
        "username": username,
        "url": f"https://t.me/{channel}",
        "avatar_url": avatar_url,
        "description_html": description_html,
        "description_text": description_text,
        "counters": counters,
    }


def parse_messages_from_tree(tree: Node, channel: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    posts: List[Dict[str, Any]] = []
    next_before: Optional[str] = None

    more_node = tree.find_first(lambda n: n.tag == "a" and n.has_class("js-messages_more"))
    if more_node and more_node.attrs.get("data-before"):
        next_before = more_node.attrs["data-before"]
    else:
        prev_link = tree.find_first(lambda n: n.tag == "link" and n.attrs.get("rel") == "prev")
        if prev_link and "before=" in prev_link.attrs.get("href", ""):
            next_before = prev_link.attrs["href"].split("before=")[-1]

    for msg_node in tree.find_by_class("tgme_widget_message"):
        data_post = msg_node.attrs.get("data-post", "")
        if "/" not in data_post:
            continue
        try:
            post_id = int(data_post.split("/")[-1])
        except ValueError:
            continue

        is_service = msg_node.has_class("service_message")
        bubble = msg_node.find_by_class("tgme_widget_message_bubble", first=True) or msg_node

        # Date, URL, Edited, Views
        date_link = bubble.find_by_class("tgme_widget_message_date", first=True)
        post_url = date_link.attrs.get("href", f"https://t.me/{channel}/{post_id}") if date_link else f"https://t.me/{channel}/{post_id}"
        time_node = date_link.find_first(lambda n: n.tag == "time") if date_link else None
        dt_iso = time_node.attrs.get("datetime", "") if time_node else ""

        meta_node = bubble.find_by_class("tgme_widget_message_meta", first=True)
        meta_text = meta_node.inner_text().lower() if meta_node else ""
        edited = "edited" in meta_text

        views_node = bubble.find_by_class("tgme_widget_message_views", first=True)
        views_num, views_label = parse_views_count(views_node.inner_text() if views_node else "")

        # Forwarded info
        forwarded_from = None
        fwd_node = bubble.find_by_class("tgme_widget_message_forwarded_from", first=True)
        if fwd_node:
            name_node = fwd_node.find_by_class("tgme_widget_message_forwarded_from_name", first=True)
            author_node = fwd_node.find_by_class("tgme_widget_message_forwarded_from_author", first=True)
            via_node = fwd_node.find_by_class("tgme_widget_message_via_bot", first=True)
            fwd_name = name_node.inner_text().strip() if name_node else ""
            fwd_url = name_node.attrs.get("href") if name_node and name_node.tag == "a" else None
            fwd_author = author_node.inner_text().strip() if author_node else ""
            via_bot = via_node.inner_text().strip() if via_node else None
            via_url = via_node.attrs.get("href") if via_node and via_node.tag == "a" else None
            if not fwd_name and not fwd_author:
                # Fallback parse
                raw_fwd = re.sub(r"^Forwarded from\s*", "", fwd_node.inner_text().strip())
                fwd_name = raw_fwd
            forwarded_from = {
                "name": fwd_name,
                "url": fwd_url,
                "author": fwd_author,
                "via_bot": via_bot,
                "via_bot_url": via_url,
            }

        # Reply info
        reply_to = None
        reply_node = bubble.find_by_class("tgme_widget_message_reply", first=True)
        if reply_node:
            r_author = reply_node.find_by_class("tgme_widget_message_author_name", first=True)
            r_text = reply_node.find_by_class("js-message_reply_text", first=True)
            r_thumb = reply_node.find_by_class("tgme_widget_message_reply_thumb", first=True)
            r_quote = reply_node.find_by_class("tgme_widget_message_reply_quote", first=True)
            reply_to = {
                "url": reply_node.attrs.get("href"),
                "author": r_author.inner_text().strip() if r_author else "",
                "text": (r_quote or r_text).inner_text().strip() if (r_quote or r_text) else "",
                "thumb": extract_bg_url(r_thumb.attrs.get("style", "")) if r_thumb else None,
            }

        # Main message text (must NOT pick js-message_reply_text!)
        text_nodes = [
            n for n in bubble.find_by_class("tgme_widget_message_text")
            if n.has_class("js-message_text") and not n.has_class("js-message_reply_text")
        ]
        # Avoid double-counting nested js-message_text divs
        outer_text_node = None
        for tn in text_nodes:
            outer_text_node = tn
            break

        text_html = ""
        text_plain = ""
        if outer_text_node:
            # If Telegram wrapped another div.js-message_text directly inside, unwrap cleanly via render_rich_html
            text_html = outer_text_node.render_rich_html().strip()
            text_plain = outer_text_node.inner_text().strip()

        # Photos (single or grouped)
        photos: List[Dict[str, Any]] = []
        seen_photo_urls = set()
        for p_node in bubble.find_by_class("tgme_widget_message_photo_wrap"):
            bg_url = extract_bg_url(p_node.attrs.get("style", ""))
            if bg_url and bg_url not in seen_photo_urls:
                seen_photo_urls.add(bg_url)
                photos.append({
                    "url": bg_url,
                    "ratio": extract_ratio(p_node),
                    "post_url": p_node.attrs.get("href", post_url),
                })

        # Videos (exclude those inside link_preview)
        videos: List[Dict[str, Any]] = []
        lp_node = bubble.find_by_class("tgme_widget_message_link_preview", first=True)
        lp_video_ids = set()
        if lp_node:
            for v in lp_node.find_by_class("tgme_widget_message_video_player"):
                lp_video_ids.add(id(v))
            for v in lp_node.find_by_class("js-message_video_player"):
                lp_video_ids.add(id(v))

        for v_node in bubble.find_by_class("tgme_widget_message_video_player"):
            if id(v_node) in lp_video_ids:
                continue
            thumb_node = v_node.find_by_class("tgme_widget_message_video_thumb", first=True)
            video_el = v_node.find_first(lambda n: n.tag == "video")
            wrap_node = v_node.find_by_class("tgme_widget_message_video_wrap", first=True)
            dur_node = v_node.find_by_class("message_video_duration", first=True)
            v_src = video_el.attrs.get("src") if video_el else None
            v_thumb = extract_bg_url(thumb_node.attrs.get("style", "")) if thumb_node else None
            videos.append({
                "url": v_src,
                "thumb": v_thumb,
                "duration": dur_node.inner_text().strip() if dur_node else "",
                "ratio": extract_ratio(wrap_node) if wrap_node else None,
                "is_round": v_node.has_class("tgme_widget_message_roundvideo_player"),
            })

        # Stickers
        stickers: List[Dict[str, Any]] = []
        for s_node in bubble.find_by_class("tgme_widget_message_sticker"):
            webp = s_node.attrs.get("data-webp")
            if webp:
                if webp.startswith("//"):
                    webp = "https:" + webp
                stickers.append({"url": webp})

        # Documents
        documents: List[Dict[str, Any]] = []
        for d_node in bubble.find_by_class("tgme_widget_message_document_wrap"):
            d_title = d_node.find_by_class("tgme_widget_message_document_title", first=True)
            d_extra = d_node.find_by_class("tgme_widget_message_document_extra", first=True)
            documents.append({
                "title": d_title.inner_text().strip() if d_title else "Document",
                "extra": d_extra.inner_text().strip() if d_extra else "",
                "url": d_node.attrs.get("href", post_url),
            })

        # Link Preview
        link_preview = None
        if lp_node:
            lp_site = lp_node.find_by_class("link_preview_site_name", first=True)
            lp_title = lp_node.find_by_class("link_preview_title", first=True)
            lp_desc = lp_node.find_by_class("link_preview_description", first=True)
            lp_img = (
                lp_node.find_by_class("link_preview_image", first=True)
                or lp_node.find_by_class("link_preview_right_image", first=True)
                or lp_node.find_by_class("link_preview_video_thumb", first=True)
            )
            lp_href = lp_node.attrs.get("href", "")
            if lp_href.startswith("//"):
                lp_href = "https:" + lp_href
            link_preview = {
                "url": lp_href,
                "site_name": lp_site.inner_text().strip() if lp_site else "",
                "title": lp_title.inner_text().strip() if lp_title else "",
                "description": lp_desc.inner_text().strip() if lp_desc else "",
                "image": extract_bg_url(lp_img.attrs.get("style", "")) if lp_img else None,
            }

        # Reactions
        reactions: List[Dict[str, Any]] = []
        for r_node in bubble.find_by_class("tgme_reaction"):
            b_node = r_node.find_first(lambda n: n.tag == "b")
            emoji = b_node.inner_text().strip() if b_node else ""
            full_r = r_node.inner_text().strip()
            count_str = full_r[len(emoji):].strip() if emoji and full_r.startswith(emoji) else full_r
            count_num, _ = parse_views_count(count_str)
            if emoji or count_str:
                reactions.append({
                    "emoji": emoji or "👍",
                    "count": count_num if count_num is not None else count_str,
                })

        # Unsupported media notice only if no media extracted
        has_unsupported = bool(
            bubble.find_by_class("message_media_not_supported_wrap", first=True)
            and not photos and not videos and not stickers and not documents
        )

        # Extract hashtags & URLs in post
        tags = extract_hashtags(text_plain, outer_text_node)
        urls_in_text = re.findall(r"https?://[^\s<>\"']+", text_plain)
        has_links = bool(link_preview or urls_in_text)

        # Month key in Taipei timezone (UTC+8)
        month_key = ""
        date_taipei = ""
        if dt_iso:
            try:
                dt_obj = datetime.fromisoformat(dt_iso.replace("Z", "+00:00")).astimezone(TAIPEI_TZ)
                month_key = dt_obj.strftime("%Y-%m")
                date_taipei = dt_obj.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                month_key = dt_iso[:7]

        posts.append({
            "id": post_id,
            "url": post_url,
            "datetime": dt_iso,
            "date_local": date_taipei,
            "month": month_key,
            "edited": edited,
            "is_service": is_service,
            "views": views_num,
            "views_label": views_label,
            "text": text_plain,
            "text_html": text_html,
            "tags": tags,
            "photos": photos,
            "videos": videos,
            "stickers": stickers,
            "documents": documents,
            "link_preview": link_preview,
            "forwarded_from": forwarded_from,
            "reply_to": reply_to,
            "reactions": reactions,
            "has_links": has_links,
            "has_unsupported_media": has_unsupported,
        })

    return posts, next_before


def fetch_url_with_retry(url: str, retries: int = 5, timeout: int = 20) -> bytes:
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:
            last_err = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed fetching {url}: {last_err}")


def download_file_if_needed(url: str, dest_path: Path) -> bool:
    if dest_path.exists() and dest_path.stat().st_size > 0:
        return True
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = fetch_url_with_retry(url, retries=3, timeout=15)
        if data:
            dest_path.write_bytes(data)
            return True
    except Exception as exc:
        print(f"  [warn] media download skipped ({url[:60]}): {exc}", file=sys.stderr)
    return False


def ext_from_url(url: str, default_ext: str = ".jpg") -> str:
    parsed = urllib.parse.urlparse(url)
    _, ext = os.path.splitext(parsed.path)
    if ext.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4"}:
        return ext.lower()
    return default_ext


def cache_media_locally(posts: List[Dict[str, Any]], site_info: Dict[str, Any], root_dir: Path, download_all: bool) -> None:
    media_dir = root_dir / "media"
    media_dir.mkdir(parents=True, exist_ok=True)

    # Always cache channel avatar locally so profile photo never breaks
    if site_info.get("avatar_url") and site_info["avatar_url"].startswith("http"):
        avatar_file = media_dir / "avatar.jpg"
        if download_file_if_needed(site_info["avatar_url"], avatar_file):
            site_info["avatar_local"] = "media/avatar.jpg"

    if not download_all:
        return

    total = len(posts)
    print(f"Caching media locally for {total} posts (already-cached files will be skipped)...", flush=True)
    for idx, p in enumerate(posts):
        pid = p["id"]
        for i, ph in enumerate(p.get("photos", [])):
            u = ph.get("url", "")
            if u.startswith("http"):
                ext = ext_from_url(u, ".jpg")
                rel = f"media/posts/{pid}_p{i}{ext}"
                if download_file_if_needed(u, root_dir / rel):
                    ph["local_url"] = rel

        for i, st in enumerate(p.get("stickers", [])):
            u = st.get("url", "")
            if u.startswith("http"):
                rel = f"media/posts/{pid}_s{i}.webp"
                if download_file_if_needed(u, root_dir / rel):
                    st["local_url"] = rel

        for i, vd in enumerate(p.get("videos", [])):
            tu = vd.get("thumb") or ""
            if tu.startswith("http"):
                rel = f"media/posts/{pid}_vt{i}.jpg"
                if download_file_if_needed(tu, root_dir / rel):
                    vd["local_thumb"] = rel
            vu = vd.get("url") or ""
            if vu.startswith("http"):
                # Check size first, only cache videos <= 10 MB to keep repo git-friendly
                try:
                    head_req = urllib.request.Request(vu, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(head_req, timeout=10) as r:
                        clen = int(r.headers.get("Content-Length") or "0")
                    if 0 < clen <= 10 * 1024 * 1024:
                        rel_v = f"media/posts/{pid}_v{i}.mp4"
                        if download_file_if_needed(vu, root_dir / rel_v):
                            vd["local_url"] = rel_v
                except Exception:
                    pass

        lp = p.get("link_preview")
        if lp and lp.get("image") and lp["image"].startswith("http"):
            ext = ext_from_url(lp["image"], ".jpg")
            rel = f"media/posts/{pid}_lp{ext}"
            if download_file_if_needed(lp["image"], root_dir / rel):
                lp["local_image"] = rel

        if (idx + 1) % 100 == 0:
            print(f"  Processed media for {idx + 1}/{total} posts...", flush=True)


def generate_rss(site_info: Dict[str, Any], posts: List[Dict[str, Any]], site_url: str, out_path: Path) -> None:
    base = site_url.rstrip("/") if site_url else f"https://t.me/{site_info['channel']}"
    now_rfc = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items_xml: List[str] = []

    for p in [x for x in posts if not x.get("is_service")][:40]:
        title_raw = (p.get("text") or "").splitlines()[0].strip() if p.get("text") else ""
        if not title_raw and p.get("link_preview"):
            title_raw = p["link_preview"].get("title", "")
        if not title_raw:
            title_raw = f"{site_info['title']} #{p['id']}"
        if len(title_raw) > 80:
            title_raw = title_raw[:77] + "..."

        link = f"{base}/?post={p['id']}" if site_url else p["url"]
        pub_rfc = now_rfc
        if p.get("datetime"):
            try:
                dt = datetime.fromisoformat(p["datetime"].replace("Z", "+00:00"))
                pub_rfc = dt.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
            except ValueError:
                pass

        body_parts = []
        for ph in p.get("photos", []):
            img_u = f"{base}/{ph['local_url']}" if (site_url and ph.get("local_url")) else ph["url"]
            body_parts.append(f'<p><img src="{html_lib.escape(img_u)}" alt="photo"></p>')
        if p.get("text_html"):
            body_parts.append(f"<div>{p['text_html']}</div>")
        if p.get("link_preview") and p["link_preview"].get("url"):
            lp = p["link_preview"]
            body_parts.append(
                f'<blockquote><a href="{html_lib.escape(lp["url"])}">{html_lib.escape(lp.get("title") or lp["url"])}</a>'
                f'<br>{html_lib.escape(lp.get("description", ""))}</blockquote>'
            )

        desc_html = "\n".join(body_parts) or html_lib.escape(p.get("text", ""))
        items_xml.append(
            f"""  <item>
    <title>{xml_escape(title_raw)}</title>
    <link>{xml_escape(link)}</link>
    <guid isPermaLink="false">{xml_escape(f"{site_info['channel']}-{p['id']}")}</guid>
    <pubDate>{pub_rfc}</pubDate>
    <description><![CDATA[{desc_html}]]></description>
  </item>"""
        )

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">
<channel>
  <title>{xml_escape(site_info['title'])}</title>
  <link>{xml_escape(base)}</link>
  <description>{xml_escape(site_info.get('description_text') or site_info['title'])}</description>
  <language>zh-Hant</language>
  <lastBuildDate>{now_rfc}</lastBuildDate>
  <atom:link href="{xml_escape(base)}/feed.xml" rel="self" type="application/rss+xml" />
{chr(10).join(items_xml)}
</channel>
</rss>
"""
    out_path.write_text(rss, encoding="utf-8")


def generate_sitemap(posts: List[Dict[str, Any]], site_url: str, out_path: Path) -> None:
    if not site_url:
        site_url = "https://example.github.io"
    base = site_url.rstrip("/")
    urls = [f"  <url><loc>{xml_escape(base)}/</loc><changefreq>hourly</changefreq><priority>1.0</priority></url>"]
    for p in [x for x in posts if not x.get("is_service")][:200]:
        lastmod = p["datetime"][:10] if p.get("datetime") else ""
        lm_tag = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        urls.append(f"  <url><loc>{xml_escape(base)}/?post={p['id']}</loc>{lm_tag}</url>")
    sitemap = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>
"""
    out_path.write_text(sitemap, encoding="utf-8")


def sync_from_live(
    channel: str,
    full: bool,
    max_pages: int,
    existing_posts: Dict[int, Dict[str, Any]],
    wait_post_id: int = 0,
) -> Tuple[Dict[str, Any], Dict[int, Dict[str, Any]]]:
    before: Optional[str] = None
    seen_before = set()
    site_info: Optional[Dict[str, Any]] = None
    merged = dict(existing_posts)

    limit = 200 if full else max_pages
    for page_idx in range(1, limit + 1):
        url = f"https://t.me/s/{channel}" + (f"?before={before}" if before else "")

        # When triggered immediately by a Bot webhook, t.me/s/<channel> can take 1-6s to reflect the brand-new post
        attempts = 5 if (page_idx == 1 and wait_post_id > 0) else 1
        page_posts: List[Dict[str, Any]] = []
        next_before: Optional[str] = None
        for w_try in range(attempts):
            raw_html = fetch_url_with_retry(url).decode("utf-8")
            tree = parse_html_tree(raw_html)
            site_info = parse_channel_info(tree, channel)
            page_posts, next_before = parse_messages_from_tree(tree, channel)
            live_ids = {p["id"] for p in page_posts}
            if wait_post_id <= 0 or wait_post_id in live_ids or (page_posts and max(live_ids) > wait_post_id):
                break
            if w_try < attempts - 1:
                print(f"Waiting for post #{wait_post_id} to appear on t.me/s/{channel} (retry {w_try + 1}/{attempts - 1})...", flush=True)
                time.sleep(3)

        if not page_posts:
            break

        # Prune posts in this page's ID window if they were deleted on Telegram
        if len(page_posts) >= 10:
            live_ids = {p["id"] for p in page_posts}
            min_pid, max_pid = min(live_ids), max(live_ids)
            for eid in list(merged.keys()):
                if min_pid <= eid <= max_pid and eid not in live_ids:
                    del merged[eid]

        new_count = 0
        for p in page_posts:
            if p["id"] not in merged:
                new_count += 1
            merged[p["id"]] = p

        print(
            f"Page {page_idx}: parsed {len(page_posts)} posts "
            f"({page_posts[0]['id']}..{page_posts[-1]['id']}), new={new_count}",
            flush=True,
        )

        # In incremental mode, stop once we've walked at least 2 pages AND all posts on this page already existed
        if not full and page_idx >= 2 and new_count == 0:
            break

        if not next_before or next_before in seen_before:
            break
        seen_before.add(next_before)
        before = next_before
        time.sleep(0.25)

    if site_info is None:
        raise RuntimeError(f"Could not fetch channel {channel}")
    return site_info, merged


def sync_from_html_dir(channel: str, html_dir: Path) -> Tuple[Dict[str, Any], Dict[int, Dict[str, Any]]]:
    files = sorted(html_dir.glob("*.html"))
    if not files:
        raise RuntimeError(f"No .html files found in {html_dir}")
    site_info: Optional[Dict[str, Any]] = None
    merged: Dict[int, Dict[str, Any]] = {}
    for f in files:
        tree = parse_html_tree(f.read_text(encoding="utf-8"))
        if site_info is None:
            site_info = parse_channel_info(tree, channel)
        page_posts, _ = parse_messages_from_tree(tree, channel)
        for p in page_posts:
            merged[p["id"]] = p
    if site_info is None:
        raise RuntimeError("Could not extract site info")
    return site_info, merged


def build_site_summary(site_info: Dict[str, Any], sorted_posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    non_service = [p for p in sorted_posts if not p.get("is_service")]
    month_counts: Dict[str, int] = {}
    tag_counts: Dict[str, int] = {}
    photo_count = 0
    video_count = 0
    link_count = 0
    fwd_count = 0

    for p in non_service:
        if p.get("month"):
            month_counts[p["month"]] = month_counts.get(p["month"], 0) + 1
        for t in p.get("tags", []):
            tag_counts[t] = tag_counts.get(t, 0) + 1
        photo_count += len(p.get("photos", []))
        video_count += len(p.get("videos", []))
        if p.get("has_links"):
            link_count += 1
        if p.get("forwarded_from"):
            fwd_count += 1

    months = [{"month": m, "count": month_counts[m]} for m in sorted(month_counts.keys(), reverse=True)]
    tags = [
        {"tag": t, "count": c}
        for t, c in sorted(tag_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:40]
    ]

    earliest = non_service[-1]["date_local"][:10] if non_service and non_service[-1].get("date_local") else ""
    latest = non_service[0]["date_local"][:10] if non_service and non_service[0].get("date_local") else ""

    return {
        **site_info,
        "last_synced_at": datetime.now(TAIPEI_TZ).isoformat(),
        "stats": {
            "total_posts": len(non_service),
            "total_photos": photo_count,
            "total_videos": video_count,
            "total_with_links": link_count,
            "total_forwarded": fwd_count,
            "earliest_date": earliest,
            "latest_date": latest,
        },
        "months": months,
        "tags": tags,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync public Telegram channel to static website JSON + RSS")
    parser.add_argument("--channel", default="mark014blog", help="Telegram channel username (without @)")
    parser.add_argument("--root", default=".", help="Website root directory")
    parser.add_argument("--full", action="store_true", help="Crawl entire channel history")
    parser.add_argument("--max-pages", type=int, default=5, help="Max pages in incremental mode (default: 5)")
    parser.add_argument("--wait-post-id", type=int, default=0, help="Wait briefly until this post ID appears on Page 1 (for webhook triggers)")
    parser.add_argument("--html-dir", default=None, help="Optional directory of pre-downloaded HTML pages")
    parser.add_argument("--download-media", action="store_true", help="Cache photos, stickers, and video thumbs into media/")
    parser.add_argument("--site-url", default="", help="Public website base URL for RSS and sitemap")
    args = parser.parse_args()

    root_dir = Path(args.root).resolve()
    data_dir = root_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    posts_path = data_dir / "posts.json"
    site_path = data_dir / "site.json"

    existing_posts: Dict[int, Dict[str, Any]] = {}
    if posts_path.exists() and not args.full:
        try:
            loaded = json.loads(posts_path.read_text(encoding="utf-8"))
            for item in loaded:
                existing_posts[int(item["id"])] = item
        except Exception as exc:
            print(f"[warn] Could not load existing posts.json: {exc}", file=sys.stderr)

    if args.html_dir:
        site_info, merged = sync_from_html_dir(args.channel, Path(args.html_dir))
    else:
        # Auto-fallback to full crawl if posts.json doesn't exist yet
        do_full = args.full or (len(existing_posts) == 0)
        site_info, merged = sync_from_live(
            args.channel, do_full, args.max_pages, existing_posts, wait_post_id=args.wait_post_id
        )

    sorted_posts = [merged[pid] for pid in sorted(merged.keys(), reverse=True)]

    # Preserve previously cached local_url fields when incremental sync refreshes a post object
    for p in sorted_posts:
        old = existing_posts.get(p["id"])
        if old:
            for i, ph in enumerate(p.get("photos", [])):
                if i < len(old.get("photos", [])) and old["photos"][i].get("local_url"):
                    if (root_dir / old["photos"][i]["local_url"]).exists():
                        ph["local_url"] = old["photos"][i]["local_url"]
            for i, st in enumerate(p.get("stickers", [])):
                if i < len(old.get("stickers", [])) and old["stickers"][i].get("local_url"):
                    if (root_dir / old["stickers"][i]["local_url"]).exists():
                        st["local_url"] = old["stickers"][i]["local_url"]

    cache_media_locally(sorted_posts, site_info, root_dir, download_all=args.download_media)

    site_summary = build_site_summary(site_info, sorted_posts)
    new_posts_str = json.dumps(sorted_posts, ensure_ascii=False, indent=2)
    old_posts_str = posts_path.read_text(encoding="utf-8") if posts_path.exists() else ""

    content_changed = (new_posts_str != old_posts_str)
    if site_path.exists() and not content_changed:
        try:
            old_site = json.loads(site_path.read_text(encoding="utf-8"))
            old_cmp = {k: v for k, v in old_site.items() if k != "last_synced_at"}
            new_cmp = {k: v for k, v in site_summary.items() if k != "last_synced_at"}
            if old_cmp == new_cmp and (root_dir / "feed.xml").exists() and (root_dir / "sitemap.xml").exists():
                print("No post or profile changes detected; skipping timestamp-only file writes.", flush=True)
                return 0
        except Exception:
            pass

    posts_path.write_text(new_posts_str, encoding="utf-8")
    site_path.write_text(json.dumps(site_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    generate_rss(site_summary, sorted_posts, args.site_url, root_dir / "feed.xml")
    generate_sitemap(sorted_posts, args.site_url, root_dir / "sitemap.xml")

    print(
        f"Synced {site_summary['stats']['total_posts']} posts, "
        f"{site_summary['stats']['total_photos']} photos, "
        f"{len(site_summary['tags'])} tags -> {data_dir}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
