"""Parse a Letterboxd "Rushes" weekly digest email into structured JSON.

Input: a saved .eml (preferred), or a raw .html/.mhtml file containing the email body.
Output: one JSON object written to --out (default .tmp/rushes.json) and echoed to stdout.

The Rushes email has three stable sections, each with a plain-text header:
  "Popular films this week"   - poster grid, no commentary
  "Popular reviews this week" - film + reviewer + star rating + one-line excerpt
  "Popular lists this week"   - list title + curator + description excerpt + 4 sample posters

Letterboxd tags every link with a utm_source token (popular-films, review-title,
review-byline, filmlist-title, ...). We slice the HTML by the section headers and key on
those tokens rather than walking the deeply nested layout tables.
"""
from __future__ import annotations

import argparse
import email
import html
import re
from email import policy
from pathlib import Path

from lib.common import emit, fail, tmp_path

SECTION_HEADERS = {
    "films": "Popular films this week",
    "reviews": "Popular reviews this week",
    "lists": "Popular lists this week",
}
FOOTER_MARKERS = ("Happy watching", "Unsubscribe from Letterboxd Rushes")


def read_html_and_meta(path: Path) -> tuple[str, dict]:
    """Return (html_body, {subject, sent_date}). Works for .eml or a raw HTML file."""
    raw = path.read_bytes()
    meta: dict = {"subject": None, "sent_date": None}
    try:
        msg = email.message_from_bytes(raw, policy=policy.default)
    except Exception:
        msg = None

    if msg is not None and msg.get_content_type().startswith("multipart"):
        htmls = [p for p in msg.walk() if p.get_content_type() == "text/html"]
        if htmls:
            meta["subject"] = str(msg.get("subject") or "").strip() or None
            date = msg.get("date")
            if date:
                try:
                    meta["sent_date"] = email.utils.parsedate_to_datetime(date).date().isoformat()
                except Exception:
                    meta["sent_date"] = str(date)
            # Largest html part is the newsletter body.
            return max((p.get_content() for p in htmls), key=len), meta

    # Fall back: treat the file as a raw HTML (or MHTML) blob.
    text = raw.decode("utf-8", errors="replace")
    if "MIME-Version" in text[:2000] and "text/html" in text:
        # crude MHTML: grab the biggest quoted-printable/base64-free html-looking chunk
        parts = re.split(r"\r?\n--+\S+\r?\n", text)
        html_parts = [p for p in parts if "<html" in p.lower() or "<td" in p.lower()]
        if html_parts:
            return max(html_parts, key=len), meta
    return text, meta


def strip_tags(s: str) -> str:
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def week_of(sent_date: str | None) -> str | None:
    if not sent_date or len(sent_date) < 10:
        return None
    try:
        import datetime as dt

        d = dt.date.fromisoformat(sent_date[:10])
        return (d - dt.timedelta(days=d.weekday())).isoformat()  # Monday of that week
    except Exception:
        return None


def section_slice(body: str, key: str) -> str:
    """HTML between this section's header and the next section header / footer."""
    start = body.find(SECTION_HEADERS[key])
    if start == -1:
        return ""
    ends = []
    for other_key, header in SECTION_HEADERS.items():
        if other_key == key:
            continue
        pos = body.find(header, start + 1)
        if pos != -1:
            ends.append(pos)
    for marker in FOOTER_MARKERS:
        pos = body.find(marker, start + 1)
        if pos != -1:
            ends.append(pos)
    return body[start : min(ends)] if ends else body[start:]


def parse_alt_title_year(alt: str) -> tuple[str, str | None]:
    """'The Odyssey (2026) film poster artwork' -> ('The Odyssey', '2026')."""
    alt = alt.replace(" film poster artwork", "").strip()
    m = re.match(r"^(.*)\s\((\d{4})\)\s*$", alt)
    if m:
        return m.group(1).strip(), m.group(2)
    return alt, None


def rating_to_number(stars: str) -> float | None:
    if not stars:
        return None
    return stars.count("★") + (0.5 if "½" in stars else 0.0)


def parse_films(seg: str) -> list[dict]:
    out = []
    for m in re.finditer(
        r'<a href="https://letterboxd\.com/film/([^/"?]+)/[^"]*utm_source=popular-films[^"]*"[^>]*>\s*'
        r'<img[^>]*alt="([^"]+)"',
        seg,
    ):
        slug, alt = m.group(1), html.unescape(m.group(2))
        title, year = parse_alt_title_year(alt)
        out.append(
            {"title": title, "year": year, "slug": slug, "url": f"https://letterboxd.com/film/{slug}/"}
        )
    return out


def _count_near(seg: str, label: str) -> int | None:
    # markup: <img ... alt="Likes icon" style="..." /><font ...>34,625</font>
    m = re.search(r'alt="' + re.escape(label) + r'"[^>]*>\s*<font[^>]*>([\d,]+)</font>', seg)
    return int(m.group(1).replace(",", "")) if m else None


def parse_reviews(seg: str) -> list[dict]:
    # Each review block begins at a review-poster or review-title anchor for a /<user>/film/<slug>/ URL.
    anchors = list(
        re.finditer(
            r'<a href="https://letterboxd\.com/([^/"]+)/film/([^/"?]+)/(\d+/)?[^"]*'
            r'utm_source=review-title[^"]*"[^>]*>\s*<font[^>]*>([^<]+)</font></a>'
            r'(?:&nbsp;|\s)*<font[^>]*>\s*(\d{4})?',
            seg,
        )
    )
    out = []
    for i, m in enumerate(anchors):
        user, film_slug = m.group(1), m.group(2)
        block = seg[m.start() : anchors[i + 1].start() if i + 1 < len(anchors) else len(seg)]
        title = html.unescape(m.group(4)).strip()
        year = m.group(5)

        dir_m = re.search(r"Directed by\s*<a[^>]*>([^<]+)</a>", block)
        byline_m = re.search(
            r'<a href="https://letterboxd\.com/([^/"?]+)/\?[^"]*utm_source=review-byline[^"]*"[^>]*>([^<]+)</a>',
            block,
        )
        rating_m = re.search(r'<img[^>]*alt="([★½]+)"', block)
        p_m = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)

        stars = rating_m.group(1) if rating_m else None
        out.append(
            {
                "title": title,
                "year": year,
                "director": html.unescape(dir_m.group(1)).strip() if dir_m else None,
                "reviewer": html.unescape(byline_m.group(2)).strip() if byline_m else None,
                "reviewer_url": f"https://letterboxd.com/{byline_m.group(1)}/" if byline_m else None,
                "rating_stars": stars,
                "rating": rating_to_number(stars),
                "likes": _count_near(block, "Likes icon"),
                "comments": _count_near(block, "Comments icon"),
                "excerpt": strip_tags(p_m.group(1)) if p_m else None,
                "url": f"https://letterboxd.com/{user}/film/{film_slug}/",
            }
        )
    return out


def parse_lists(seg: str) -> list[dict]:
    anchors = list(
        re.finditer(
            r'<a href="https://letterboxd\.com/([^/"?]+)/list/([^/"?]+)/[^"]*'
            r'utm_source=filmlist-title[^"]*"[^>]*>([^<]+)</a>',
            seg,
        )
    )
    out = []
    for i, m in enumerate(anchors):
        user, list_slug, title = m.group(1), m.group(2), html.unescape(m.group(3)).strip()
        block = seg[m.start() : anchors[i + 1].start() if i + 1 < len(anchors) else len(seg)]

        count_m = re.search(r">\s*([\d,]+)\s+Films?\s*<", block)
        byline_m = re.search(
            r'<a href="https://letterboxd\.com/([^/"?]+)/\?[^"]*utm_source=filmlist-byline[^"]*"[^>]*>([^<]+)</a>',
            block,
        )
        p_m = re.search(r"<p[^>]*>(.*?)</p>", block, re.S)
        excerpt = strip_tags(re.sub(r"(?is)<a[^>]*>read more</a>", "", p_m.group(1))) if p_m else None

        # sample posters live just BEFORE the title anchor, inside the filmlist-posters wrapper
        pre = seg[max(0, m.start() - 4000) : m.start()]
        poster_wrap = pre.rfind("utm_source=filmlist-posters")
        sample = []
        if poster_wrap != -1:
            for pm in re.finditer(r'<img[^>]*alt="([^"]+)"', pre[poster_wrap:]):
                t, y = parse_alt_title_year(html.unescape(pm.group(1)))
                sample.append({"title": t, "year": y})

        out.append(
            {
                "title": title,
                "film_count": int(count_m.group(1).replace(",", "")) if count_m else None,
                "curator": html.unescape(byline_m.group(2)).strip() if byline_m else None,
                "curator_url": f"https://letterboxd.com/{byline_m.group(1)}/" if byline_m else None,
                "excerpt": excerpt.strip("… ").strip() if excerpt else None,
                "url": f"https://letterboxd.com/{user}/list/{list_slug}/",
                "sample_films": sample,
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eml", required=True, help="Path to the saved Rushes email (.eml, .html, .mhtml)")
    ap.add_argument("--out", default=None, help="Where to write rushes.json (default .tmp/rushes.json)")
    ap.add_argument(
        "--sent-date",
        default=None,
        help="Override the email date (YYYY-MM-DD). Use when the input is a bare HTML "
        "body with no headers, so week_of is still populated.",
    )
    args = ap.parse_args()

    src = Path(args.eml)
    if not src.exists():
        fail(f"Input not found: {src}")

    body, meta = read_html_and_meta(src)
    if "Rushes" not in body and "Popular films this week" not in body:
        fail("This does not look like a Letterboxd Rushes email (no known markers found).")

    if args.sent_date and not meta.get("sent_date"):
        meta["sent_date"] = args.sent_date[:10]

    warnings: list[str] = []
    films = parse_films(section_slice(body, "films"))
    reviews = parse_reviews(section_slice(body, "reviews"))
    lists_ = parse_lists(section_slice(body, "lists"))

    for name, rows in (("popular_films", films), ("popular_reviews", reviews), ("popular_lists", lists_)):
        if not rows:
            warnings.append(f"{name}: parsed 0 items - the email layout may have changed")

    result = {
        "source_subject": meta["subject"],
        "sent_date": meta["sent_date"],
        "week_of": week_of(meta["sent_date"]),
        "popular_films": films,
        "popular_reviews": reviews,
        "popular_lists": lists_,
        "warnings": warnings,
    }

    out_path = Path(args.out) if args.out else tmp_path("rushes.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(__import__("json").dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    emit(
        {
            "status": "ok",
            "out": str(out_path),
            "counts": {
                "popular_films": len(films),
                "popular_reviews": len(reviews),
                "popular_lists": len(lists_),
            },
            "warnings": warnings,
            "rushes": result,
        }
    )


if __name__ == "__main__":
    main()
