import json
import html
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = BASE_DIR / "docs"

DOCS_DIR.mkdir(exist_ok=True)

summaries_path = DATA_DIR / "summaries.json"
summaries_txt_path = DATA_DIR / "summaries.txt"

output_json_path = DOCS_DIR / "summaries.json"
output_txt_path = DOCS_DIR / "summaries.txt"
output_html_path = DOCS_DIR / "index.html"

if not summaries_path.exists():
    raise FileNotFoundError(f"Missing file: {summaries_path}")

with summaries_path.open("r", encoding="utf-8") as f:
    raw_data = json.load(f)


def normalize_runs(data):
    """
    Supported input formats:
    1) dict with metadata + articles
    2) list of runs, where each run is a dict with metadata + articles
    3) plain list of article dicts
    """
    if isinstance(data, dict):
        return [normalize_run(data)]

    if isinstance(data, list):
        if not data:
            return [empty_run()]

        first_item = data[0]

        if isinstance(first_item, dict) and "articles" in first_item:
            return [normalize_run(run) for run in data]

        if isinstance(first_item, dict):
            return [normalize_run({
                "time": "Unknown",
                "window_hours": "Unknown",
                "article_count": len(data),
                "overall_summary": "",
                "articles": data,
            })]

    raise ValueError(
        "Unsupported summaries.json structure. Expected a run object, "
        "a list of runs, or a list of article objects."
    )


def empty_run():
    return {
        "time": "Unknown",
        "window_hours": "Unknown",
        "article_count": 0,
        "overall_summary": "",
        "articles": [],
    }


def normalize_run(run):
    articles = run.get("articles", [])
    if not isinstance(articles, list):
        articles = []

    return {
        "time": run.get("time", "Unknown"),
        "window_hours": run.get("window_hours", "Unknown"),
        "article_count": run.get("article_count", len(articles)),
        "overall_summary": run.get("overall_summary", ""),
        "articles": articles,
    }


runs = normalize_runs(raw_data)

# Save normalized data to docs/summaries.json
with output_json_path.open("w", encoding="utf-8") as f:
    json.dump(runs, f, ensure_ascii=False, indent=2)

# Copy TXT if available
if summaries_txt_path.exists():
    shutil.copy2(summaries_txt_path, output_txt_path)


def render_run(run_data, is_latest=False):
    run_time = html.escape(str(run_data.get("time", "Unknown")))
    window_hours_raw = run_data.get("window_hours", "Unknown")
    article_count = html.escape(str(run_data.get("article_count", 0)))
    overall_summary = html.escape(str(run_data.get("overall_summary", "")))
    articles = run_data.get("articles", [])

    articles_html = []

    for article in articles:
        title = html.escape(str(article.get("title", "Untitled")))
        url = html.escape(str(article.get("url", "#")))
        published = html.escape(str(article.get("published", "Unknown")))
        summary = html.escape(str(article.get("summary", "")))

        article_html = f"""
        <details class="article-card">
          <summary>
            <div class="summary-row">
              <span class="article-title">{title}</span>
              <span class="article-date">{published}</span>
            </div>
          </summary>
          <div class="article-body">
            <p>{summary}</p>
            <p><a href="{url}" target="_blank" rel="noopener noreferrer">Read original article</a></p>
          </div>
        </details>
        """
        articles_html.append(article_html)

    overall_section = ""
    if overall_summary.strip():
        overall_section = f"""
        <div class="overall">
          <h3>Overall Summary</h3>
          <p>{overall_summary}</p>
        </div>
        """

    window_line = ""
    if str(window_hours_raw) != "Unknown":
        window_line = f"<strong>Window:</strong> Last {html.escape(str(window_hours_raw))} hours<br>"

    heading = "Latest Run" if is_latest else "Previous Run"

    return f"""
    <section class="run-block {'latest-run' if is_latest else 'previous-run'}">
      <h2>{heading}</h2>
      <div class="meta">
        <strong>Run time:</strong> {run_time}<br>
        {window_line}
        <strong>Articles used:</strong> {article_count}
      </div>

      {overall_section}

      <div class="articles-section">
        <h3>Articles</h3>
        {''.join(articles_html) if articles_html else '<p>No articles found for this run.</p>'}
      </div>
    </section>
    """


latest_run_html = render_run(runs[0], is_latest=True)

previous_runs_html = ""
if len(runs) > 1:
    previous_blocks = "".join(render_run(run, is_latest=False) for run in runs[1:])
    previous_runs_html = f"""
    <details class="previous-runs-wrapper">
      <summary>View Previous Runs ({len(runs) - 1})</summary>
      <div class="previous-runs-content">
        {previous_blocks}
      </div>
    </details>
    """

page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>News Summaries</title>
  <style>
    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #f5f7fb;
      color: #1f2937;
      line-height: 1.6;
    }}

    .page {{
      max-width: 1000px;
      margin: 40px auto;
      padding: 0 20px;
    }}

    .container {{
      background: #ffffff;
      padding: 32px;
      border-radius: 16px;
      box-shadow: 0 6px 24px rgba(0, 0, 0, 0.08);
    }}

    h1 {{
      margin: 0 0 8px 0;
      font-size: 2rem;
    }}

    h2 {{
      margin-top: 0;
      margin-bottom: 12px;
      font-size: 1.4rem;
    }}

    h3 {{
      margin-top: 0;
      margin-bottom: 10px;
      font-size: 1.1rem;
    }}

    .subtitle {{
      color: #6b7280;
      margin-bottom: 28px;
    }}

    .run-block {{
      margin-bottom: 32px;
      padding: 24px;
      border: 1px solid #e5e7eb;
      border-radius: 14px;
      background: #ffffff;
    }}

    .latest-run {{
      border: 2px solid #2563eb;
      background: #fcfdff;
    }}

    .meta {{
      color: #4b5563;
      margin-bottom: 18px;
    }}

    .overall {{
      background: #eef4ff;
      border-left: 4px solid #2563eb;
      padding: 16px;
      border-radius: 10px;
      margin-bottom: 22px;
    }}

    .articles-section {{
      margin-top: 10px;
    }}

    .article-card {{
      margin-bottom: 14px;
      border: 1px solid #e5e7eb;
      border-radius: 10px;
      background: #fff;
      overflow: hidden;
    }}

    .article-card summary {{
      list-style: none;
      cursor: pointer;
      padding: 16px;
      font-weight: 600;
    }}

    .article-card summary::-webkit-details-marker {{
      display: none;
    }}

    .summary-row {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      align-items: flex-start;
    }}

    .article-title {{
      flex: 1;
    }}

    .article-date {{
      color: #6b7280;
      white-space: nowrap;
      font-size: 0.92rem;
    }}

    .article-body {{
      padding: 0 16px 16px 16px;
      border-top: 1px solid #f0f0f0;
    }}

    .previous-runs-wrapper {{
      margin-top: 10px;
      border: 1px solid #dbe3f0;
      border-radius: 12px;
      background: #fafcff;
      overflow: hidden;
    }}

    .previous-runs-wrapper > summary {{
      cursor: pointer;
      padding: 18px 20px;
      font-weight: 700;
      background: #f3f7ff;
      list-style: none;
    }}

    .previous-runs-wrapper > summary::-webkit-details-marker {{
      display: none;
    }}

    .previous-runs-content {{
      padding: 20px;
    }}

    .footer {{
      margin-top: 28px;
      padding-top: 18px;
      border-top: 1px solid #e5e7eb;
      font-size: 0.95rem;
      color: #6b7280;
    }}

    .footer a {{
      margin-right: 16px;
      color: #2563eb;
      text-decoration: none;
    }}

    .footer a:hover {{
      text-decoration: underline;
    }}

    @media (max-width: 700px) {{
      .summary-row {{
        flex-direction: column;
      }}

      .article-date {{
        white-space: normal;
      }}

      .container {{
        padding: 22px;
      }}

      .run-block {{
        padding: 18px;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="container">
      <h1>News Summaries</h1>
      <div class="subtitle">Latest run first, with previous runs available below.</div>

      {latest_run_html}

      {previous_runs_html}

      <div class="footer">
        <a href="summaries.json" target="_blank" rel="noopener noreferrer">View JSON</a>
        <a href="summaries.txt" target="_blank" rel="noopener noreferrer">View TXT</a>
      </div>
    </div>
  </div>
</body>
</html>
"""

with output_html_path.open("w", encoding="utf-8") as f:
    f.write(page)

print(f"Generated: {output_html_path}")
print(f"Normalized JSON written to: {output_json_path}")
if summaries_txt_path.exists():
    print(f"TXT copied to: {output_txt_path}")