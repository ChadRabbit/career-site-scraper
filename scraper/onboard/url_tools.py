"""Turn concrete URLs seen during onboarding into reusable templates."""

from __future__ import annotations

from collections.abc import Iterable
from urllib.parse import parse_qsl, quote_plus, unquote, unquote_plus, urlparse, urlunparse


def _rebuild_query(pairs: list[tuple[str, str]], placeholder_index: int, placeholder: str) -> str:
    parts = []
    for i, (k, v) in enumerate(pairs):
        parts.append(f"{quote_plus(k)}={placeholder if i == placeholder_index else quote_plus(v)}")
    return "&".join(parts)


def query_url_template(url: str, query: str) -> str | None:
    """'https://x/jobs?q=Software+Engineer&l=IN' + 'Software Engineer' → 'https://x/jobs?q={query}&l=IN'."""
    if not query:
        return None
    parsed = urlparse(url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    wanted = query.strip().lower()
    for i, (_, value) in enumerate(pairs):
        if value.strip().lower() == wanted:
            return urlunparse(parsed._replace(query=_rebuild_query(pairs, i, "{query}"), fragment=""))
    for encoded in (quote_plus(query.strip()), query.strip().replace(" ", "-")):
        if encoded and encoded.lower() in parsed.path.lower():
            start = parsed.path.lower().index(encoded.lower())
            path = parsed.path[:start] + "{query}" + parsed.path[start + len(encoded):]
            return urlunparse(parsed._replace(path=path, fragment=""))
    return None


def page_url_template(before: str, after: str) -> str | None:
    """Spot ?page=2 / &offset=20 / /page/2 style pagination between two listing URLs."""
    if not before or not after or before == after:
        return None
    b, a = urlparse(before), urlparse(after)
    if b.netloc != a.netloc:
        return None
    before_pairs = dict(parse_qsl(b.query, keep_blank_values=True))
    after_pairs = parse_qsl(a.query, keep_blank_values=True)
    for i, (key, value) in enumerate(after_pairs):
        if value.isdigit() and before_pairs.get(key) != value:
            placeholder = "{page}" if value == "2" else "{offset}"
            return urlunparse(a._replace(query=_rebuild_query(after_pairs, i, placeholder), fragment=""))
    b_segs, a_segs = b.path.rstrip("/").split("/"), a.path.rstrip("/").split("/")
    for i, seg in enumerate(a_segs):
        if seg.isdigit() and (i >= len(b_segs) or b_segs[i] != seg):
            a_segs[i] = "{page}"
            return urlunparse(a._replace(path="/".join(a_segs), fragment=""))
    return None


def _url_tokens(url: str) -> set[str]:
    parsed = urlparse(url)
    tokens = {unquote(s) for s in parsed.path.split("/") if s}
    tokens |= {unquote_plus(v) for _, v in parse_qsl(parsed.query)}
    return tokens


def template_from_attributes(detail_url: str, attributes: Iterable[dict]) -> tuple[str | None, dict | None]:
    """
    The card had no link, but opening it led to detail_url. Find a card attribute whose value
    appears in that URL (data-job-id="123" ↔ /jobs/123) and turn the URL into a template.
    Returns (template with {job_id}, field spec for job_id).
    """
    clean_url = urlunparse(urlparse(detail_url)._replace(fragment=""))
    tokens = _url_tokens(clean_url)
    path_and_query = clean_url.split("://", 1)[-1].split("/", 1)[-1]
    for attribute in sorted(attributes, key=lambda a: -len(a.get("value", ""))):
        value = (attribute.get("value") or "").strip()
        if len(value) < 3 or attribute.get("attr") in ("href", "class", "style"):
            continue
        if value in tokens or (len(value) >= 5 and value in path_and_query):
            template = clean_url.replace(value, "{job_id}", 1)
            return template, {"selectors": attribute.get("selectors", []), "attr": attribute.get("attr")}
    return None, None
