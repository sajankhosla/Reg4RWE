#!/usr/bin/env python3
"""Point each navigator record at the public review or assessment report.

The January curation stored a Drugs@FDA or EMA medicine page and a short note.
This script resolves the review PDF or European public assessment report,
searches that file for the extracted wording, and records the page and heading.

It also reads the three tables FDA publishes as its own RWE examples and
writes a comparison the app can show.

Curated January extracts are not modified. Re-running skips PDFs already saved
under data/cache/pdfs/ and location rows already completed at this version.
"""

from __future__ import annotations

import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import norm_space  # noqa: E402
from update_search import REVIEW_NAME, fetch, review_links, safe_name  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError as exc:  # pragma: no cover
    raise SystemExit("pypdf is required to locate passages.") from exc

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
PDF_DIR = CACHE / "pdfs"
CORPUS = ROOT / "data" / "corpus.json"
EPAR = CACHE / "epar_documents.json"
LOCATIONS = ROOT / "data" / "locations.json"
EXAMPLES = ROOT / "data" / "fda_examples.json"
VERSION = 2

FDA_TABLES = [
    (
        "cder-approvals",
        "CDER drug approvals",
        "https://www.fda.gov/science-research/real-world-evidence/cder-drug-approvals-used-real-world-evidence",
        0,
    ),
    (
        "cder-postmarketing",
        "CDER postmarketing studies",
        "https://www.fda.gov/science-research/real-world-evidence/cder-postmarketing-studies-used-real-world-evidence",
        0,
    ),
    (
        "cber-safety",
        "CBER safety labeling",
        "https://www.fda.gov/science-research/real-world-evidence/cber-labeling-changes-related-safety-findings-used-real-world-evidence-fda-and-sponsor-conducted",
        1,
    ),
]

TITLE_MARKERS = [
    ("IntegratedR", "integrated review"),
    ("MultidisciplineR", "multidisciplinary review"),
    ("MedR", "clinical review"),
    ("StatR", "statistical review"),
    ("SumR", "summary review"),
    ("OtherR", "other review"),
    ("RiskR", "risk assessment review"),
]
CLASS_PHRASES = [
    "proton pump",
    "hydroxyethyl starch",
    "immune globulin",
    "immunoglobulin",
    "beta blocker",
    "oral anticoagulant",
    "anticoagulant",
    "methotrexate",
    "hydrochlorothiazide",
    "gadolinium",
    "olmesartan",
    "benicar",
    "angiotensin-converting",
    "ace inhibitor",
    "erythropoietin",
    "epogen",
    "parenteral iron",
    "glucagon-like",
    "glp-1",
    "sglt2",
    "sodium-glucose",
    "mrna",
    "comirnaty",
    "spikevax",
    "allergenic extract",
    "car t",
    "sumatriptan",
    "imitrex",
    "azithromycin",
    "zithromax",
]
BRAND_SKIP = {
    "oral", "products", "multiple", "vaccine", "vaccines", "inhibitors",
    "agonists", "containing", "various", "human", "safety", "class",
    "cell", "therapies", "therapy", "based", "contrast", "agents",
}


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def save_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def compact(text: str) -> str:
    text = (text or "").replace("\u00ad", "")
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def needles(quote: str) -> list[str]:
    raw = (quote or "").strip()
    raw = re.sub(r"^[^A-Za-z0-9]+", "", raw)
    words = compact(raw).split()
    if raw[:1].islower() and words:
        words = words[1:]
    if words and not re.search(r"[.!?]\s*$", quote or "") and len(words[-1]) < 4:
        words = words[:-1]
    found = []
    for size in (8, 6, 5):
        if len(words) < size:
            continue
        for start in range(0, len(words) - size + 1):
            window = words[start:start + size]
            if sum(len(word) >= 4 for word in window) < 2:
                continue
            found.append(" ".join(window))
        if found:
            return found[:8]
    if len(words) >= 4:
        return [" ".join(words)]
    return []


def is_heading(line: str) -> bool:
    line = norm_space(line)
    if not line or len(line) < 6 or len(line) > 90:
        return False
    low = line.lower()
    if re.search(r"\bpage\s+\d+|emea/h|nda\s*\d|bla\s*\d", low):
        return False
    if re.search(r"\b\d{1,2}\s+(january|february|march|april|may|june|july|august|september|october|november|december)\b", low):
        return False
    words = line.split()
    if len(words) > 14 or line.endswith((",", ";")):
        return False
    numbered = bool(re.match(r"^\d+(\.\d+)*\.?\s+[A-Za-z]", line))
    keywords = (
        "efficacy", "safety", "external", "control", "conclusion", "discussion",
        "assessment", "evidence", "study", "results", "limitation", "population",
        "history", "compar", "benefit", "risk", "indication", "clinical",
    )
    topical = any(word in low for word in keywords) and not line.endswith(".")
    if numbered and 2 <= len(words) <= 14:
        return True
    return topical and 2 <= len(words) <= 8


def document_title(url: str, agency: str) -> str:
    if agency == "EMA":
        return "European public assessment report"
    name = url.rsplit("/", 1)[-1]
    for marker, title in TITLE_MARKERS:
        if marker.lower() in name.lower():
            return title
    if re.search(r"orig\d*s(?!000)\d+\.pdf$", name, re.I):
        return "supplement review"
    return "public review"


def cache_path(url: str, agency: str) -> Path:
    filename = url.rsplit("/", 1)[-1].split("?")[0]
    legacy = PDF_DIR / agency / safe_name(filename)
    if legacy.exists() and legacy.stat().st_size > 1000:
        return legacy
    stem = safe_name(re.sub(r"\.pdf$", "", filename, flags=re.I))
    modern = PDF_DIR / agency / f"{stem}.pdf"
    if modern.exists() and modern.stat().st_size > 1000:
        return modern
    return modern


def ema_cached(application: str) -> Path | None:
    key = safe_name(application or "")
    if not key:
        return None
    matches = sorted((PDF_DIR / "ema").glob(key + "*"))
    matches = [path for path in matches if path.stat().st_size > 1000]
    return matches[-1] if matches else None


def read_pages(path: Path) -> list[tuple[int, str]]:
    reader = PdfReader(str(path))
    pages = []
    for index, page in enumerate(reader.pages, 1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        pages.append((index, text))
    return pages


def find_passage(path: Path, quote: str) -> dict | None:
    wanted = needles(quote)
    if not wanted or not path.exists():
        return None
    try:
        pages = read_pages(path)
    except Exception:
        return None
    heading = ""
    for page_no, text in pages:
        folded_so_far = ""
        for line in text.splitlines():
            if is_heading(line):
                heading = norm_space(line)
            folded_so_far = compact(folded_so_far + " " + line)
            for needle in wanted:
                if needle in folded_so_far:
                    return {"page": page_no, "section": heading, "needle": needle}
    return None


def location_note(title: str, page: int | None, section: str, kind: str) -> str:
    if kind == "class":
        return (
            "This entry covers a class of products. FDA describes the action in its "
            "published examples of real-world evidence, and there is no single review PDF for the class."
        )
    if page and section:
        return f"The extracted wording is on page {page} of the {title}, under the heading “{section}”."
    if page:
        return f"The extracted wording is on page {page} of the {title}."
    if kind == "summary" and title:
        return (
            f"The linked file is the {title} posted for this application. "
            "The wording in this navigator summarises the assessment."
        )
    if title:
        return (
            f"The linked file is the {title}. "
            "The extracted passage was not aligned to a single page in the copies that were read."
        )
    return "A public review file was not posted for this application on the product page that was read."


def result(url: str, title: str, page: int | None, section: str, kind: str, note: str | None = None) -> dict:
    return {
        "version": VERSION,
        "document_url": url,
        "document_title": title,
        "page": page,
        "section": section or "",
        "location_kind": kind,
        "location_note": note or location_note(title, page, section, kind),
    }


def is_pdf(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 1000:
        return False
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def ensure_pdf(url: str, path: Path) -> bool:
    if is_pdf(path):
        return True
    if path.exists():
        path.unlink()
    try:
        fetch(url, dest=path, timeout=180, limit=250_000_000)
    except Exception as exc:
        print(f"    download failed {url[:90]} ({exc.__class__.__name__})")
        return False
    if not is_pdf(path):
        if path.exists():
            path.unlink()
        print(f"    not a PDF {url[:90]}")
        return False
    return True


def search_urls(quote: str, urls: list[tuple[str, Path]], agency: str, summary_if_missing: bool) -> dict | None:
    last = None
    seen = set()
    for url, path in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        title = document_title(url, agency)
        if not ensure_pdf(url, path):
            continue
        found = find_passage(path, quote)
        last = (url, title)
        if found:
            return result(url, title, found["page"], found["section"], "page")
    if last and summary_if_missing:
        url, title = last
        kind = "summary" if agency == "FDA" else "unaligned"
        return result(url, title, None, "", kind)
    return None


def ema_candidates(record: dict, documents: list[dict]) -> list[str]:
    product = (record.get("application") or "").strip()
    year = (record.get("year") or "")[:4]
    rows = [
        doc for doc in documents
        if (doc.get("ema_product_number") or "").strip() == product
        and doc.get("type") == "assessment-report"
        and doc.get("document_url")
    ]

    def rank(doc: dict) -> tuple:
        name = (doc.get("name") or "").lower()
        published = (doc.get("first_published_date") or "")[:4]
        return (
            published != year,
            "variation" in name,
            "public assessment report" not in name,
            published,
        )

    urls = []
    seen = set()
    own = record.get("document_url") or ""
    if own:
        urls.append(own if own.startswith("http") else "https://www.ema.europa.eu" + own)
        seen.add(urls[0])
    for doc in sorted(rows, key=rank)[:4]:
        url = doc["document_url"]
        if not url.startswith("http"):
            url = "https://www.ema.europa.eu" + url
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls[:4]


TOC_KEYS = {"medr", "statr", "integratedr", "sumr", "multidiscipliner", "otherr", "riskr", "crossr"}


def path_year(url: str) -> int:
    match = re.search(r"/(19\d{2}|20\d{2})/", url)
    return int(match.group(1)) if match else 0


def is_review_pdf(url: str) -> bool:
    low = url.lower()
    if not low.endswith(".pdf") or " " in url or "," in url:
        return False
    if any(token in low for token in ("lbl", "label", "appletter", "ltr.pdf", "admincorres", "/approv")):
        return False
    if REVIEW_NAME.search(url):
        return True
    if re.search(r"(medr|statr|integratedr|sumr|multidiscipliner|crossr)\.pdf$", low):
        return True
    return bool(re.search(r"orig\d*s\d+\.pdf$", low))


def toc_review_urls(toc_url: str) -> list[str]:
    try:
        page = fetch(toc_url, timeout=60).decode("utf-8", "replace")
    except Exception:
        return []
    directory = toc_url.rsplit("/", 1)[0] + "/"
    named = []
    block = re.search(r"var pdfFilenames = \{([\s\S]*?)\};", page)
    if block:
        for key, filename in re.findall(r'(\w+)\s*:\s*"([^"]+\.pdf)"', block.group(1), flags=re.I):
            if key.lower() in TOC_KEYS and " " not in filename and "," not in filename:
                named.append(urllib.parse.urljoin(directory, filename))
    if named:
        return named
    return [link for link in review_links(toc_url, page) if " " not in link and "," not in link]


def fda_candidates(application: str, year: str) -> list[str]:
    digits = re.findall(r"\d{5,6}", application or "")
    if not digits:
        return []
    overview = (
        "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm"
        f"?event=overview.process&ApplNo={digits[0]}"
    )
    try:
        page = fetch(overview, timeout=60).decode("utf-8", "replace")
    except Exception as exc:
        print(f"    overview failed ({exc.__class__.__name__})")
        return []
    hrefs = []
    for href in re.findall(r'href="([^"]+)"', page, flags=re.I):
        if href.startswith("http"):
            hrefs.append(href.split("#")[0])
        else:
            hrefs.append(urllib.parse.urljoin("https://www.accessdata.fda.gov/", href).split("#")[0])
    found = []
    seen = set()
    tocs = [href for href in hrefs if re.search(r"toc\.(html|cfm)$", href, re.I)]
    indexes = [
        href for href in hrefs
        if href not in tocs and re.search(r"/drugsatfda_docs/.+\.html$", href, re.I)
    ]
    for toc in tocs + indexes:
        for link in toc_review_urls(toc):
            if link not in seen and is_review_pdf(link):
                seen.add(link)
                found.append(link)
    for href in hrefs:
        if href not in seen and is_review_pdf(href):
            seen.add(href)
            found.append(href)
    year_i = int(year) if str(year).isdigit() else 0

    def prefer(url: str) -> tuple:
        distance = abs(path_year(url) - year_i) if path_year(url) and year_i else 40
        name = url.lower()
        clinical = 0 if any(token in name for token in ("integratedr", "medr", "multidiscipliner")) else 1
        return (distance, clinical, name)

    found.sort(key=prefer)
    return found[:4]


def locate_record(record: dict, documents: list[dict]) -> dict:
    agency = record["agency"]
    quote = record.get("quote") or ""
    if agency == "FDA" and not re.search(r"\d{5,6}", record.get("application") or ""):
        return result("", "", None, "", "class")
    if agency == "EMA":
        cached = ema_cached(record.get("application") or "")
        urls = ema_candidates(record, documents)
        pairs = []
        for index, url in enumerate(urls):
            screened = record.get("document_url") or ""
            if cached and index == 0 and (not screened or url == screened):
                path = cached
            else:
                path = cache_path(url, "ema")
            pairs.append((url, path))
        found = search_urls(quote, pairs[:4], "EMA", summary_if_missing=True)
        return found or result("", "European public assessment report", None, "", "unresolved")
    urls = []
    own = record.get("document_url") or ""
    if own:
        urls.append(own)
    for url in fda_candidates(record.get("application") or "", (record.get("year") or "")[:4]):
        if url not in urls:
            urls.append(url)
    pairs = [(url, cache_path(url, "fda")) for url in urls[:4]]
    found = search_urls(quote, pairs, "FDA", summary_if_missing=True)
    return found or result("", "", None, "", "unresolved")


def strip_tags(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return norm_space(html.unescape(value))


def parse_fda_table(page: str, name_index: int) -> list[dict]:
    table = re.search(r"<table[\s\S]*?</table>", page, flags=re.I)
    if not table:
        return []
    rows = re.findall(r"<tr[\s\S]*?</tr>", table.group(0), flags=re.I)
    parsed = []
    for row in rows[1:]:
        cells = [strip_tags(cell) for cell in re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row, flags=re.I)]
        if len(cells) <= name_index:
            continue
        summary = max(cells, key=len)
        parsed.append({
            "product": cells[name_index],
            "summary": summary[:500],
            "action": cells[-1][:240],
        })
    return parsed


def fetch_fda_examples() -> list[dict]:
    examples = []
    for table_id, label, url, name_index in FDA_TABLES:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        page = urllib.request.urlopen(request, timeout=60).read().decode("utf-8", "replace")
        for index, row in enumerate(parse_fda_table(page, name_index), 1):
            examples.append({
                "id": f"{table_id}-{index:02d}",
                "table_id": table_id,
                "table": label,
                "url": url,
                **row,
            })
    return examples


def appl_numbers(text: str) -> set[int]:
    found = set()
    for raw in re.findall(r"\d{5,6}", text or ""):
        found.add(int(raw))
    return found


def brand_tokens(text: str) -> set[str]:
    head = re.split(r"\b(?:NDA|BLA|Multiple)\b", text or "", flags=re.I)[0]
    head = head.replace("®", " ")
    head = re.sub(r"\([^)]*\)", " ", head)
    tokens = set()
    for part in re.split(r"[,;/]|\band\b", head, flags=re.I):
        words = [
            word.lower() for word in re.findall(r"[A-Za-z][A-Za-z0-9\-]{3,}", part)
            if word.lower() not in BRAND_SKIP
        ]
        if words:
            tokens.add(words[0])
            if len(words) >= 2:
                tokens.add(" ".join(words[:3]))
    return {token for token in tokens if len(token) >= 5 or " " in token}


def class_hits(text: str) -> set[str]:
    folded = compact(text)
    return {phrase for phrase in CLASS_PHRASES if phrase in folded}


def compare(examples: list[dict], records: list[dict]) -> dict:
    fda_records = [record for record in records if record["agency"] == "FDA"]
    prepared = []
    for record in fda_records:
        blob = " ".join([record.get("drug") or "", record.get("application") or ""])
        prepared.append((record, appl_numbers(blob), brand_tokens(record.get("drug") or ""), class_hits(blob)))
    matched_ids = set()
    in_both = []
    fda_only = []
    for example in examples:
        blob = example["product"]
        numbers = appl_numbers(blob)
        brands = brand_tokens(blob)
        classes = class_hits(blob)
        hits = []
        for record, rec_numbers, rec_brands, rec_classes in prepared:
            basis = ""
            if numbers and rec_numbers and numbers & rec_numbers:
                basis = "application number"
            elif brands and rec_brands and brands & rec_brands:
                basis = "product name"
            elif classes and rec_classes and classes & rec_classes:
                basis = "class"
            if basis:
                hits.append({"id": record["id"], "drug": record["drug"], "basis": basis})
                matched_ids.add(record["id"])
        row = {
            "id": example["id"],
            "table": example["table"],
            "table_id": example["table_id"],
            "url": example["url"],
            "product": example["product"],
            "action": example["action"],
            "summary": example["summary"],
            "matches": hits,
        }
        (in_both if hits else fda_only).append(row)
    corpus_only = []
    for record, _numbers, _brands, _classes in prepared:
        if record["id"] in matched_ids:
            continue
        corpus_only.append({
            "id": record["id"],
            "drug": record["drug"],
            "application": record.get("application") or "",
            "year": record.get("year") or "",
            "decision": record.get("decision") or "",
            "origin": record.get("origin") or "",
        })
    return {
        "checked_on": datetime.now().strftime("%Y-%m-%d"),
        "sources": [{"id": item[0], "label": item[1], "url": item[2]} for item in FDA_TABLES],
        "counts": {
            "examples": len(examples),
            "in_both": len(in_both),
            "fda_only": len(fda_only),
            "corpus_only": len(corpus_only),
            "corpus_fda": len(fda_records),
        },
        "in_both": in_both,
        "fda_only": fda_only,
        "corpus_only": corpus_only,
    }


def attach_example_links(locations: dict, comparison: dict) -> None:
    by_id: dict[str, str] = {}
    for example in comparison["in_both"]:
        for match in example["matches"]:
            by_id.setdefault(match["id"], example["url"])
    for record_id, url in by_id.items():
        row = locations.get(record_id)
        if row:
            row["fda_example_url"] = url


def main() -> None:
    only = {arg for arg in sys.argv[1:] if not arg.startswith("-")}
    corpus = load_json(CORPUS, {})
    records = corpus.get("records") or []
    if not records:
        raise SystemExit("Corpus is missing. Run pipeline/build_corpus.py first.")
    documents = load_json(EPAR, {"data": []}).get("data") or []
    locations = load_json(LOCATIONS, {})
    pending = [
        record for record in records
        if (not only or record["id"] in only)
        and (locations.get(record["id"]) or {}).get("version") != VERSION
    ]
    print(f"Locating {len(pending)} of {len(records)} records")
    for index, record in enumerate(pending, 1):
        print(f"[{index}/{len(pending)}] {record['id']} {record['drug'][:48]}", flush=True)
        try:
            located = locate_record(record, documents)
        except Exception as exc:
            print(f"    failed {exc.__class__.__name__}: {exc}")
            located = result("", "", None, "", "unresolved")
        locations[record["id"]] = located
        page = located.get("page")
        print(f"    {located.get('location_kind')} {located.get('document_title') or ''} page {page or '-'}")
        if index % 5 == 0:
            save_json(LOCATIONS, locations)
    save_json(LOCATIONS, locations)
    examples = fetch_fda_examples()
    comparison = compare(examples, records)
    attach_example_links(locations, comparison)
    save_json(LOCATIONS, locations)
    save_json(EXAMPLES, comparison)
    counts = comparison["counts"]
    print(
        f"FDA examples {counts['examples']}: shared {counts['in_both']}, "
        f"FDA only {counts['fda_only']}, corpus only {counts['corpus_only']}"
    )


if __name__ == "__main__":
    main()
