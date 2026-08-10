"""JavBus and JavDB metadata adapters and merge policy."""

import html
import re


JAVBUS = "https://www.javbus.com"
JAVDB = "https://javdb.com"
KANA = re.compile(r"[぀-ヿ]")


def _clean(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _same_code(left, right):
    """Compare catalog numbers without case, separators, or numeric padding."""

    def normalize(value):
        match = re.match(r"^([A-Za-z]+)[-_]?0*(\d+)$", (value or "").strip())
        if match:
            return f"{match.group(1).upper()}-{int(match.group(2))}"
        return (value or "").upper()

    return normalize(left) == normalize(right)


def parse_javbus(page_html, code):
    """Parse a JavBus title page, rejecting pages without a cover or matching ID."""
    if '<a class="bigImage"' not in page_html:
        return None

    data = {"source": "javbus", "code": code}

    match = re.search(r"<h3>(.*?)</h3>", page_html, re.S)
    data["title"] = _clean(match.group(1)) if match else code

    match = re.search(r'<a class="bigImage" href="([^"]+)"', page_html)
    if match:
        url = match.group(1)
        data["cover"] = url if url.startswith("http") else JAVBUS + url

    start = page_html.find('class="col-md-3 info"')
    block = page_html[start : start + 6000] if start > 0 else page_html

    def field(label):
        match = re.search(
            r'<span class="header">%s:</span>\s*(?:<[^>]+>\s*)?([^<]+)' % label,
            block,
        )
        return _clean(match.group(1)) if match and _clean(match.group(1)) else None

    page_id = field("識別碼")
    if page_id and not _same_code(page_id, code):
        return None
    data["dvdid"] = page_id or code
    data["release"] = field("發行日期")
    data["studio"] = field("製作商")
    data["label"] = field("發行商")
    data["series"] = field("系列")
    data["director"] = field("導演")

    runtime = field("長度")
    if runtime:
        match = re.search(r"(\d+)", runtime)
        data["runtime"] = int(match.group(1)) if match else None

    genres = re.findall(
        r'<span class="genre">(?:(?!</span>).)*?<a href="[^"]*/genre/[^"]*">([^<]+)</a>',
        block,
        re.S,
    )
    data["genres"] = [_clean(genre) for genre in genres if _clean(genre)]

    actors = []
    for match in re.finditer(
        r'<a class="avatar-box" href="[^"]*">\s*<div class="photo-frame">\s*'
        r'<img src="([^"]+)"[^>]*>\s*</div>\s*<span>([^<]+)</span>',
        page_html,
        re.S,
    ):
        thumb, name = match.group(1), _clean(match.group(2))
        if not thumb.startswith("http"):
            thumb = JAVBUS + thumb
        if "nowprinting" in thumb.lower():
            thumb = ""
        actors.append({"name": name, "thumb": thumb})
    if not actors:
        for match in re.finditer(r'<a href="[^"]*/star/[^"]*">([^<]+)</a>', page_html):
            name = _clean(match.group(1))
            if name and name not in [actor["name"] for actor in actors]:
                actors.append({"name": name, "thumb": ""})
    data["actors"] = actors

    samples = re.findall(r'<a class="sample-box" href="([^"]+)"', page_html)
    data["samples"] = [
        sample if sample.startswith("http") else JAVBUS + sample for sample in samples
    ]
    return data


def fetch_javbus(fetcher, code):
    status, page = fetcher.get(f"{JAVBUS}/{code}")
    if status != 200 or not page:
        return None
    return parse_javbus(page, code)


def _javdb_field(page, *labels):
    for label in labels:
        match = re.search(r"<strong>%s\s*:?\s*</strong>(.*?)</div>" % label, page, re.S)
        if match:
            value = _clean(re.sub(r"<[^>]+>", " ", match.group(1))).replace(
                "&nbsp;", " "
            ).strip()
            value = re.sub(r"\s{2,}", " ", value)
            if value:
                return value
    return None


def javdb_find(fetcher, code):
    """Return the detail path of the exact catalog-number match."""
    status, page = fetcher.get(f"{JAVDB}/search?q={code}&f=all")
    if status != 200 or not page:
        return None
    for chunk in page.split('<a href="/v/')[1:]:
        path = chunk.split('"', 1)[0]
        head = chunk[:600]
        for found in re.findall(r"<strong>([A-Za-z0-9\-_]+)</strong>", head):
            if _same_code(found, code):
                return f"/v/{path}"
    return None


def fetch_javdb(fetcher, code):
    path = javdb_find(fetcher, code)
    if not path:
        return None
    status, page = fetcher.get(f"{JAVDB}{path}?locale=zh")
    if status != 200 or not page:
        return None

    data = {"source": "javdb", "code": code}
    match = re.search(r'<h2 class="title[^"]*">(.*?)</h2>', page, re.S)
    if not match:
        return None
    parts = re.findall(r"<strong[^>]*>(.*?)</strong>", match.group(1), re.S)
    page_id = _clean(parts[0]) if parts else None
    if page_id and not _same_code(page_id, code):
        return None
    data["dvdid"] = page_id or code
    data["title"] = _clean(parts[1]) if len(parts) > 1 else code

    data["release"] = _javdb_field(page, "日期")
    data["studio"] = _javdb_field(page, "片商")
    data["label"] = _javdb_field(page, "發行", "发行")
    data["series"] = _javdb_field(page, "系列")
    data["director"] = _javdb_field(page, "導演", "导演")

    runtime = _javdb_field(page, "時長", "时长")
    if runtime:
        match = re.search(r"(\d+)", runtime)
        data["runtime"] = int(match.group(1)) if match else None

    categories = _javdb_field(page, "類別", "类别") or ""
    data["genres"] = [value.strip() for value in categories.split(",") if value.strip()]

    actors = []
    seen = set()
    block = re.search(r"<strong>演員\s*:?\s*</strong>(.*?)</div>", page, re.S)
    if block:
        for match in re.finditer(r">([^<>]+)</a>\s*<strong[^>]*>\s*♀", block.group(1)):
            name = _clean(match.group(1))
            if name and name not in seen:
                seen.add(name)
                actors.append({"name": name, "thumb": ""})
    data["actors"] = actors

    match = re.search(r"(https://c\d\.jdbstatic\.com/covers/[^\"']+)", page)
    if match:
        data["cover"] = match.group(1)
    sample_numbers = sorted(
        set(re.findall(r"https://c\d\.jdbstatic\.com/samples/[^\"']*_l_(\d+)\.jpg", page)),
        key=int,
    )
    base = re.search(r"(https://c\d\.jdbstatic\.com/samples/[^\"']*)_l_\d+\.jpg", page)
    data["samples"] = (
        [f"{base.group(1)}_l_{number}.jpg" for number in sample_numbers] if base else []
    )
    return data


def merge_sources(bus, db):
    """Merge sources using JavBus as the base and JavDB as enrichment."""
    if not bus:
        return db
    data = dict(bus)
    if not db:
        return data

    db_title = (db.get("title") or "").strip()
    if db_title and not KANA.search(db_title):
        data["title_cn"] = db_title

    for field in ("release", "runtime", "studio", "label", "series", "director"):
        if not data.get(field) and db.get(field):
            data[field] = db[field]

    data["genres"] = list(
        dict.fromkeys(list(data.get("genres", [])) + db.get("genres", []))
    )
    if not data.get("actors"):
        data["actors"] = db.get("actors", [])

    if db.get("cover"):
        data["cover_alt"] = db["cover"]
    if db.get("samples"):
        if data.get("samples"):
            data["samples_alt"] = db["samples"]
        else:
            data["samples"] = db["samples"]
    return data
