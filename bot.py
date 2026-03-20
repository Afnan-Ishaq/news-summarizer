import os
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# =========================
# PATHS / ENV
# =========================
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
os.makedirs("data", exist_ok=True)

# Explicitly load .env from the same folder as this script
load_dotenv(dotenv_path=ENV_PATH)

# =========================
# CONFIG
# =========================
NEWS_SITEMAP_URL = "https://www.aljazeera.com/news-sitemap.xml"
HOURS_BACK = 6
MAX_ARTICLES_PER_RUN = 30
MAX_CHARS_PER_ARTICLE = 3000

OUTPUT_DIR = BASE_DIR / "data"
SUMMARIES_TXT_PATH = OUTPUT_DIR / "summaries.txt"
SUMMARIES_JSON_PATH = OUTPUT_DIR / "summaries.json"
SEEN_URLS_PATH = OUTPUT_DIR / "seen_urls.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    )
}

# =========================
# FILE HELPERS
# =========================
def ensure_output_dir():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: Path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def prepend_txt(path, text):
    if not path.exists():
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return

    with open(path, "r", encoding="utf-8") as f:
        existing = f.read()

    with open(path, "w", encoding="utf-8") as f:
        f.write(text + existing)


# =========================
# TIME HELPERS
# =========================
def now_utc():
    return datetime.now(timezone.utc)


def parse_date(s: str):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def iso_z(dt: datetime):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# =========================
# FILTER URLs
# =========================
def is_valid_url(url: str):
    blocked = [
        "/video/",
        "/podcasts/",
        "/liveblog/",
        "/features/liveblog/",
        "/program/",
    ]
    return not any(b in url for b in blocked)


# =========================
# FETCH URLs
# =========================
def fetch_recent_urls():
    r = requests.get(NEWS_SITEMAP_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    root = ET.fromstring(r.content)

    ns = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "news": "http://www.google.com/schemas/sitemap-news/0.9",
    }

    cutoff = now_utc() - timedelta(hours=HOURS_BACK)
    results = []

    for url_node in root.findall("sm:url", ns):
        loc = url_node.find("sm:loc", ns)
        pub = url_node.find("news:news/news:publication_date", ns)
        title = url_node.find("news:news/news:title", ns)

        if loc is None or pub is None:
            continue

        dt = parse_date((pub.text or "").strip())
        if not dt:
            continue

        if dt >= cutoff:
            results.append({
                "url": (loc.text or "").strip(),
                "published": iso_z(dt),
                "title_from_sitemap": (title.text or "").strip() if title is not None else ""
            })

    results.sort(key=lambda x: x["published"])
    return results


# =========================
# SCRAPE ARTICLE
# =========================
def clean_text(text: str):
    return re.sub(r"\s+", " ", text).strip()


def get_article(url: str):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "lxml")

    title = soup.title.get_text(" ", strip=True) if soup.title else ""

    text_parts = []
    seen = set()

    containers = [
        soup.find("main"),
        soup.find("article"),
        soup.find(attrs={"role": "main"}),
    ]

    for container in containers:
        if not container:
            continue
        for tag in container.find_all(["p", "h1", "h2", "li"]):
            t = clean_text(tag.get_text(" ", strip=True))
            if len(t) > 40 and t not in seen:
                seen.add(t)
                text_parts.append(t)

    if len(text_parts) < 5:
        for p in soup.find_all("p"):
            t = clean_text(p.get_text(" ", strip=True))
            if len(t) > 40 and t not in seen:
                seen.add(t)
                text_parts.append(t)

    return {
        "title": title,
        "text": "\n".join(text_parts)[:MAX_CHARS_PER_ARTICLE]
    }


# =========================
# DEEPSEEK
# =========================
def summarize(articles):
    api_key = os.getenv("DEEPSEEK_API_KEY")

    print(f".env path checked: {ENV_PATH}")
    print(f".env exists: {ENV_PATH.exists()}")
    print(f"DEEPSEEK_API_KEY loaded: {bool(api_key)}")

    if not api_key:
        raise RuntimeError(
            "Missing DEEPSEEK_API_KEY. Make sure the .env file is in the same folder as bot.py "
            "and the filename is exactly .env"
        )

    prompt = f"""
Summarize the following Al Jazeera articles from the last {HOURS_BACK} hours.

Instructions:
- Do NOT merge all stories into a few broad bullets.
- Keep the output article-by-article.
- For each article, write a concise 2-4 sentence summary of what that specific article says.
- Preserve the same article order provided below.
- Keep the summaries factual and readable.
- Return ONLY valid JSON.
- Do not include markdown fences.
- Do NOT infer or assume facts not explicitly stated in the article.
- If something is unclear, describe it cautiously.

Return this exact JSON structure:
{{
  "overall_summary": "A short 2-3 sentence overview of the full batch",
  "articles": [
    {{
      "title": "article title",
      "url": "article url",
      "published": "published timestamp",
      "summary": "2-4 sentence summary of this specific article"
    }}
  ]
}}

Articles:
""".strip()

    for i, a in enumerate(articles, start=1):
        prompt += (
            f"\n\nARTICLE {i}"
            f"\nTITLE: {a['title']}"
            f"\nURL: {a['url']}"
            f"\nPUBLISHED: {a['published']}"
            f"\nTEXT:\n{a['text']}"
        )

    response = requests.post(
        "https://api.deepseek.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a precise news summarization assistant."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        },
        timeout=90,
    )

    if not response.ok:
        raise RuntimeError(
            f"DeepSeek API error {response.status_code}:\n{response.text}"
        )

    data = response.json()
    raw = data["choices"][0]["message"]["content"].strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError("DeepSeek returned invalid JSON:\n\n" + raw)

    cleaned_articles = []
    for original, item in zip(articles, parsed.get("articles", [])):
        cleaned_articles.append({
            "title": str(item.get("title", original["title"])).strip(),
            "url": str(item.get("url", original["url"])).strip(),
            "published": str(item.get("published", original["published"])).strip(),
            "summary": str(item.get("summary", "")).strip(),
        })

    return {
        "overall_summary": str(parsed.get("overall_summary", "")).strip(),
        "articles": cleaned_articles,
    }


# =========================
# MAIN
# =========================
def run():
    ensure_output_dir()

    seen = set(load_json(SEEN_URLS_PATH, []))
    history = load_json(SUMMARIES_JSON_PATH, [])

    print("Fetching URLs...")
    recent_urls = fetch_recent_urls()
    print(f"Recent URLs in last {HOURS_BACK} hours: {len(recent_urls)}")

    unseen_urls = [u for u in recent_urls if u["url"] not in seen]
    print(f"After removing seen URLs: {len(unseen_urls)}")

    filtered_urls = [u for u in unseen_urls if is_valid_url(u["url"])]
    print(f"After removing video/liveblog/etc: {len(filtered_urls)}")

    urls = filtered_urls[:MAX_ARTICLES_PER_RUN]
    print(f"After applying cap ({MAX_ARTICLES_PER_RUN}): {len(urls)}")

    if not urls:
        print("No articles to process.")
        return

    articles = []

    for i, u in enumerate(urls, start=1):
        print(f"[{i}/{len(urls)}] Fetching: {u['url']}")
        try:
            art = get_article(u["url"])

            if not art["text"].strip():
                print("  -> skipped, empty text")
                continue

            articles.append({
                "url": u["url"],
                "published": u["published"],
                "title": art["title"] or u.get("title_from_sitemap", ""),
                "text": art["text"],
            })
        except Exception as e:
            print(f"  -> error: {e}")

    if not articles:
        print("No usable articles found.")
        return

    print("Summarizing...")
    summary = summarize(articles)

    entry = {
    "time": iso_z(now_utc()),
    "window_hours": HOURS_BACK,
    "article_count": len(articles),
    "overall_summary": summary.get("overall_summary", ""),
    "articles": summary.get("articles", []),
    }

    history.insert(0, entry)
    save_json(SUMMARIES_JSON_PATH, history)

    txt = []
    txt.append("=" * 80)
    txt.append(f"RUN TIME UTC: {entry['time']}")
    txt.append(f"WINDOW: Last {entry['window_hours']} hours")
    txt.append(f"ARTICLES USED: {entry['article_count']}")
    txt.append("")

    txt.append("OVERALL SUMMARY")
    txt.append(entry["overall_summary"] or "No overall summary generated.")
    txt.append("")

    txt.append("ARTICLE BREAKDOWN")
    for i, article in enumerate(entry["articles"], start=1):
        txt.append(f"[{i}] {article['title']}")
        txt.append(f"Published: {article['published']}")
        txt.append(f"URL: {article['url']}")
        txt.append(f"Summary: {article['summary']}")
        txt.append("")
    txt.append("")

    text_block = "\n".join(txt) + "\n\n"
    prepend_txt(SUMMARIES_TXT_PATH, "\n".join(txt))

    for a in articles:
        seen.add(a["url"])

    save_json(SEEN_URLS_PATH, sorted(seen))

    print("Done")
    print(f"Saved: {SUMMARIES_TXT_PATH}")
    print(f"Saved: {SUMMARIES_JSON_PATH}")
    print(f"Saved: {SEEN_URLS_PATH}")


if __name__ == "__main__":
    run()