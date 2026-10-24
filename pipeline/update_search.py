#!/usr/bin/env python3
"""Extend the January 2026 FDA and EMA screen through 24 October 2026.

EMA. The January script kept human medicines authorised from 2015 to 2025.
The index captured on that search contained three authorisations dated
8–9 January 2026 and no later ones. This run screens every human medicine
authorised from 1 January 2026 through 24 October 2026, downloads the matched
European public assessment report, and keeps a document only when a passage
describes a study or a judgement, not a passing use of an RWE term.

FDA. The January search was a public-site query on 19 January 2026. This run
reads the FDA novel-drug list for 2026, resolves each application on
Drugs@FDA, and reads the integrated, medical, or statistical review when one
is posted.

Outputs:
  data/search_update/manifest.json
  data/search_update/hits.json

Curated January files are not modified. Re-running skips PDFs already saved
under data/cache/pdfs/.
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import classify_passage, norm_space, relevant_snippets  # noqa: E402

try:
    from pypdf import PdfReader
except ImportError as exc:  # pragma: no cover
    raise SystemExit("pypdf is required for the October screen.") from exc

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data" / "cache"
PDF_DIR = CACHE / "pdfs"
OUT_DIR = ROOT / "data" / "search_update"
SEARCH_DATE = datetime(2026, 10, 24)
WINDOW_START = datetime(2026, 1, 1)
PREVIOUS_SEARCH = "2026-01-19"

EMA_BASE = "https://www.ema.europa.eu"
FDA_NOVEL = "https://www.fda.gov/drugs/novel-drug-approvals-fda/novel-drug-approvals-2026"
OPENFDA = "https://api.fda.gov/drug/drugsfda.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

REVIEW_FLAGS = [
    ("integratedR", "IntegratedR.pdf"),
    ("medR", "MedR.pdf"),
    ("statR", "StatR.pdf"),
    ("sumR", "SumR.pdf"),
    ("multidisciplineR", "MultidisciplineR.pdf"),
]
FALLBACK_FLAGS = [
    ("otherR", "OtherR.pdf"),
    ("riskR", "RiskR.pdf"),
]
REVIEW_NAME = re.compile(r"(IntegratedR|MedR|StatR|SumR|MultidisciplineR|OtherR|RiskR)\.pdf", re.I)


def fetch(url: str, dest: Path | None = None, timeout: int = 120, limit: int = 80_000_000) -> bytes:
    if dest and dest.exists() and dest.stat().st_size > 1000:
        head = dest.read_bytes()[:5]
        if not dest.suffix == ".pdf" or head == b"%PDF-":
            return dest.read_bytes()
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except Exception:
        time.sleep(1.5)
        response = urllib.request.urlopen(request, timeout=timeout)
    with response:
        chunks = []
        total = 0
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise RuntimeError(f"larger than {limit} bytes")
            chunks.append(chunk)
    data = b"".join(chunks)
    if dest and data:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return data


def parse_date(value: str, formats: tuple[str, ...] = ("%d/%m/%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%SZ")) -> datetime | None:
    if not value:
        return None
    text = value[:10] if "T" in value else value
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def normalize_name(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def safe_name(value: str) -> str:
    value = re.sub(r"[^\w\-]+", "_", value.strip())
    return re.sub(r"_+", "_", value).strip("_") or "document"


def pdf_text(path: Path) -> str:
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n".join(parts)


def best_snippet(snippets: list[str]) -> str:
    def score(text: str) -> tuple:
        low = text.lower()
        return (
            sum(word in low for word in (
                "external control", "historical control", "natural history study",
                "natural history data", "real-world", "chart review", "registry",
            )),
            text[:1].isupper(),
        )
    return max(snippets, key=score)


def hit_record(agency: str, drug: str, application: str, year: str, indication: str,
               quote: str, source_url: str, document_url: str, screen_note: str) -> dict:
    fields = classify_passage(quote)
    return {
        "id": f"{agency}-2026-{safe_name(application or drug)[:40]}",
        "agency": agency,
        "Drug_Name": drug,
        "Application_Number": application,
        "Year": year,
        "Indication": indication,
        "RWE_Type": fields["rwe_type"],
        "Data_Source": "Not specified by the screen",
        "Study_Design": fields["design"],
        "Comparator": "Not specified by the screen",
        "Role_of_RWE": fields["role"],
        "FDA_Assessment_Summary": (
            "October 2026 machine screen. Passage met the study-or-judgement gate. "
            "Not a curated assessment."
        ),
        "Key_Methodological_Issues": fields["issues"],
        "Jansen_Theme1_Alignment": fields["theme1"],
        "Jansen_Theme2_Alignment": "Not specified",
        "Confidence_Score": "",
        "Key_Quote": quote[:700],
        "SLR_Relevance": "October 2026 screen — not yet curated",
        "source_url": source_url,
        "document_url": document_url,
        "screen_note": screen_note,
    }


# ---------------------------------------------------------------- EMA


def ema_candidates() -> list[dict]:
    medicines = json.loads((CACHE / "medicines.json").read_text())["data"]
    docs = json.loads((CACHE / "epar_documents.json").read_text())["data"]
    human = []
    for row in medicines:
        if str(row.get("category", "")).lower() != "human":
            continue
        authorised = parse_date(row.get("marketing_authorisation_date") or "")
        if authorised and WINDOW_START <= authorised <= SEARCH_DATE:
            human.append(row)
    by_name: dict[str, list] = {}
    for doc in docs:
        if doc.get("type") != "assessment-report":
            continue
        prefix = (doc.get("name") or "").split(" : EPAR")[0].strip()
        by_name.setdefault(normalize_name(prefix), []).append(doc)

    matched = []
    for med in human:
        key = normalize_name(med.get("name_of_medicine"))
        candidates = list(by_name.get(key, []))
        if not candidates:
            for doc_name, doc_list in by_name.items():
                if doc_name.startswith(key) or key.startswith(doc_name):
                    candidates.extend(doc_list)
        if not candidates:
            continue

        def doc_date(doc: dict) -> datetime:
            return parse_date(doc.get("last_updated_date") or "") or parse_date(doc.get("first_published_date") or "") or datetime.min

        best = sorted(candidates, key=doc_date, reverse=True)[0]
        matched.append({"medicine": med, "document": best})
    return matched


def screen_ema_one(item: dict) -> dict:
    med, doc = item["medicine"], item["document"]
    url = doc.get("document_url") or ""
    if url and not url.startswith("http"):
        url = EMA_BASE + url
    product = med.get("ema_product_number") or ""
    filename = safe_name(f"{product}_{doc.get('id')}") + ".pdf"
    path = PDF_DIR / "ema" / filename
    result = {
        "drug": med.get("name_of_medicine"),
        "application": product,
        "authorised": med.get("marketing_authorisation_date"),
        "pdf": url,
        "status": "",
    }
    try:
        fetch(url, path, timeout=180)
        text = pdf_text(path)
    except Exception as exc:
        result["status"] = f"failed: {exc.__class__.__name__}"
        return result
    if not text.strip():
        result["status"] = "no extractable text"
        return result
    snippets = relevant_snippets(text)
    result["status"] = "hit" if snippets else "no study-or-judgement passage"
    if snippets:
        authorised = parse_date(med.get("marketing_authorisation_date") or "")
        result["hit"] = hit_record(
            "EMA",
            med.get("name_of_medicine") or "",
            product,
            str(authorised.year if authorised else ""),
            norm_space(med.get("therapeutic_indication") or ""),
            best_snippet(snippets),
            med.get("medicine_url") or "",
            url,
            "EMA assessment report for a medicine authorised in 2026.",
        )
    return result


# ---------------------------------------------------------------- FDA


def novel_drugs() -> list[dict]:
    html = fetch(FDA_NOVEL).decode("utf-8", "replace")
    tables = re.findall(r"<table[\s\S]*?</table>", html, flags=re.I)
    if not tables:
        raise RuntimeError("FDA novel-approval table was not found")
    drugs = []
    for row in re.findall(r"<tr[\s\S]*?</tr>", tables[0], flags=re.I)[1:]:
        cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row, flags=re.I)
        clean = []
        for cell in cells:
            cell = re.sub(r"<[^>]+>", " ", cell)
            cell = cell.replace("&nbsp;", " ").replace("&amp;", "&")
            clean.append(norm_space(cell))
        if len(clean) < 4:
            continue
        approved = parse_date(clean[3], ("%m/%d/%Y", "%m/%d/%y"))
        if not approved or approved > SEARCH_DATE or approved.year != 2026:
            continue
        drugs.append({
            "number": clean[0].rstrip("."),
            "drug": clean[1],
            "ingredient": clean[2],
            "approved": approved.strftime("%Y-%m-%d"),
            "use": clean[4] if len(clean) > 4 else "",
            "before_previous_search": approved < datetime(2026, 1, 20),
        })
    return drugs


def openfda_application(brand: str) -> dict | None:
    query = urllib.parse.quote(f'products.brand_name:"{brand}"')
    url = f"{OPENFDA}?search={query}&limit=5"
    try:
        payload = json.loads(fetch(url, timeout=60))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    results = payload.get("results") or []
    if not results:
        return None
    brand_key = normalize_name(brand)
    for result in results:
        for product in result.get("products") or []:
            if normalize_name(product.get("brand_name")) == brand_key:
                return result
    return results[0]


TOC_REVIEW_KEYS = {"medr", "statr", "integratedr", "sumr", "multidiscipliner", "otherr", "riskr", "crossr"}


def review_links(toc_url: str, html: str) -> list[str]:
    directory = toc_url.rsplit("/", 1)[0] + "/"
    named = []
    filenames = re.search(r"var pdfFilenames = \{([\s\S]*?)\};", html)
    if filenames:
        for key, filename in re.findall(r'(\w+)\s*:\s*"([^"]+\.pdf)"', filenames.group(1), flags=re.I):
            if key.lower() in TOC_REVIEW_KEYS and " " not in filename and "," not in filename:
                named.append(urllib.parse.urljoin(directory, filename))
    if named:
        return named[:4]

    flags = {}
    block = re.search(r"var pdfFiles = \{([\s\S]*?)\};", html)
    if block:
        for key, value in re.findall(r"(\w+)\s*:\s*([01])", block.group(1)):
            flags[key] = value == "1"
    base_match = re.search(r'var pdfBaseName = "([^"]+)"', html)
    if base_match:
        prefix = toc_url.rsplit("/", 1)[0] + "/" + base_match.group(1)
    elif toc_url.endswith("TOC.html"):
        prefix = toc_url[:-len("TOC.html")]
    else:
        prefix = ""
    chosen = [prefix + suffix for key, suffix in REVIEW_FLAGS if prefix and flags.get(key)]
    if not chosen and prefix:
        chosen = [prefix + suffix for key, suffix in FALLBACK_FLAGS if flags.get(key)]
    if chosen:
        return chosen[:3]

    direct = []
    for href in re.findall(r'href="([^"]+\.pdf)"', html, flags=re.I):
        if "pdfBaseName" in href or "+" in href or " " in href:
            continue
        if not REVIEW_NAME.search(href):
            continue
        if href.startswith("http"):
            direct.append(href)
        else:
            direct.append(urllib.parse.urljoin(toc_url, href))
    return direct[:3]


def _is_review_pdf(url: str) -> bool:
    low = url.lower()
    if not low.endswith(".pdf") or " " in url or "," in url:
        return False
    if any(token in low for token in ("lbl", "label", "appletter", "ltr.pdf", "admincorres")):
        return False
    if REVIEW_NAME.search(url):
        return True
    return bool(re.search(r"orig\d*s\d+\.pdf$", low))


def screen_fda_one(drug: dict) -> dict:
    result = dict(drug)
    result["status"] = ""
    given = drug.get("application") or ""
    if given:
        appl = given
        digits = re.sub(r"\D", "", given)
        application = {"application_number": given}
    else:
        try:
            application = openfda_application(drug["drug"])
        except Exception as exc:
            result["status"] = f"lookup failed: {exc.__class__.__name__}"
            return result
        if not application:
            result["status"] = "application number not found"
            return result
        appl = application.get("application_number") or ""
        digits = re.sub(r"\D", "", appl)
    result["application"] = appl
    overview = (
        "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm"
        f"?event=overview.process&ApplNo={digits}"
    )
    result["source_url"] = overview
    try:
        page = fetch(overview, timeout=60).decode("utf-8", "replace")
    except Exception as exc:
        result["status"] = f"overview failed: {exc.__class__.__name__}"
        return result
    hrefs = []
    for href in re.findall(r'href="([^"]+)"', page, flags=re.I):
        full = href if href.startswith("http") else urllib.parse.urljoin("https://www.accessdata.fda.gov", href)
        hrefs.append(full.split("#")[0])
    tocs = [href for href in hrefs if re.search(r"toc\.html$", href, re.I)]
    tocs += [
        href for href in hrefs
        if href not in tocs and re.search(r"/drugsatfda_docs/.+\.html$", href, re.I)
    ]
    links: list[str] = []
    seen = set()
    for toc in tocs:
        try:
            toc_html = fetch(toc, timeout=60).decode("utf-8", "replace")
        except Exception:
            continue
        for link in review_links(toc, toc_html):
            if link not in seen and _is_review_pdf(link):
                seen.add(link)
                links.append(link)
    for href in hrefs:
        if href not in seen and _is_review_pdf(href):
            seen.add(href)
            links.append(href)
    action_year = int((drug.get("approved") or "0")[:4] or 0)

    def prefer(url: str) -> tuple:
        match = re.search(r"/(19|20)(\d{2})/", url)
        posted = int(match.group(0).strip("/")) if match else 0
        distance = abs(posted - action_year) if posted and action_year else 40
        name = url.lower()
        clinical = 0 if any(token in name for token in ("integratedr", "medr", "multidiscipliner")) else 1
        return (distance, clinical, name)

    links.sort(key=prefer)
    links = links[:4]
    result["reviews"] = links
    if not links:
        result["status"] = "no review PDF posted"
        return result

    snippets = []
    read_url = ""
    read_any = False
    for link in links[:3]:
        path = PDF_DIR / "fda" / safe_name(link.rsplit("/", 1)[-1])
        try:
            fetch(link, path, timeout=180, limit=250_000_000)
            text = pdf_text(path)
        except Exception as exc:
            result.setdefault("errors", []).append(f"{link}: {exc.__class__.__name__}")
            continue
        read_any = True
        found = relevant_snippets(text)
        if found:
            snippets = found
            read_url = link
            break
    if not read_any:
        result["status"] = "review PDF could not be read"
        return result
    if not snippets:
        result["status"] = "reviews read; no study-or-judgement passage"
        return result
    result["status"] = "hit"
    result["hit"] = hit_record(
        "FDA",
        drug["drug"],
        appl,
        drug["approved"][:4],
        drug["use"],
        best_snippet(snippets),
        overview,
        read_url,
        "FDA novel-drug approval in 2026. Review text screened on 24 October 2026.",
    )
    return result


def write_outputs(ema_results: list[dict], fda_results: list[dict]) -> None:
    hits = []
    for result in ema_results + fda_results:
        if result.get("hit"):
            hits.append(result["hit"])
    # Stable unique ids if two documents share an application.
    seen = {}
    for hit in hits:
        base = hit["id"]
        seen[base] = seen.get(base, 0) + 1
        if seen[base] > 1:
            hit["id"] = f"{base}-{seen[base]}"
    manifest = {
        "searched_on": SEARCH_DATE.strftime("%Y-%m-%d"),
        "previous_search": PREVIOUS_SEARCH,
        "gate": (
            "A document is kept only when an RWE term sits in a passage that also "
            "describes a study design or a regulatory judgement. Term-only mentions are counted and dropped."
        ),
        "ema": {
            "method": "Human medicines with a marketing authorisation from 1 January 2026 through 24 October 2026. Latest matched assessment report.",
            "medicines": len(ema_results),
            "hits": sum(1 for row in ema_results if row.get("status") == "hit"),
            "no_passage": sum(1 for row in ema_results if row.get("status") == "no study-or-judgement passage"),
            "failed": sum(1 for row in ema_results if str(row.get("status", "")).startswith("failed") or row.get("status") == "no extractable text"),
            "results": [{k: v for k, v in row.items() if k != "hit"} for row in ema_results],
        },
        "fda": {
            "method": "FDA novel drug approvals for 2026, plus products on FDA’s own RWE example tables that are not already in the curated extract. The review nearest the action year is read, including supplement reviews.",
            "listed": len(fda_results),
            "approved_before_previous_search": sum(1 for row in fda_results if row.get("before_previous_search")),
            "hits": sum(1 for row in fda_results if row.get("status") == "hit"),
            "no_review": sum(1 for row in fda_results if row.get("status") == "no review PDF posted"),
            "no_passage": sum(1 for row in fda_results if row.get("status") == "reviews read; no study-or-judgement passage"),
            "unresolved": sum(1 for row in fda_results if "not found" in str(row.get("status")) or "failed" in str(row.get("status"))),
            "results": [{k: v for k, v in row.items() if k != "hit"} for row in fda_results],
        },
        "hit_count": len(hits),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (OUT_DIR / "hits.json").write_text(json.dumps(hits, indent=2))
    print(
        f"EMA hits {manifest['ema']['hits']} of {manifest['ema']['medicines']}; "
        f"FDA hits {manifest['fda']['hits']} of {manifest['fda']['listed']}"
    )


def published_example_drugs() -> list[dict]:
    """Products on FDA’s own RWE tables that the novel-approval list does not contain."""
    path = ROOT / "data" / "fda_examples.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    curated_numbers = set()
    curated = ROOT.parent / "SLR_Execution/data_extraction/FDA_RWE_Complete_Extraction_All_Documents.csv"
    if curated.exists():
        import csv
        with curated.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                for number in re.findall(r"\d{5,6}", row.get("Application_Number") or ""):
                    curated_numbers.add(int(number))
    drugs = []
    for example in payload.get("fda_only") or []:
        product = example.get("product") or ""
        if re.search(r"\bMultiple\b", product):
            continue
        pairs = re.findall(r"(NDA|BLA)\s*(\d{5,6})", product, flags=re.I)
        if not pairs:
            continue
        if any(int(number) in curated_numbers for _kind, number in pairs):
            continue
        name = re.split(r"\b(?:NDA|BLA)\b", product, maxsplit=1, flags=re.I)[0]
        name = re.sub(r"[®™]", "", name)
        name = re.sub(r"\([^)]*\)", " ", name)
        name = norm_space(name).strip(" ,")
        years = re.findall(r"(20\d{2})", example.get("action") or "")
        drugs.append({
            "number": pairs[0][1].zfill(6),
            "drug": name.split(",")[0].strip() or name,
            "ingredient": "",
            "approved": f"{years[-1]}-01-01" if years else "",
            "use": example.get("summary") or "",
            "before_previous_search": False,
            "application": f"{pairs[0][0].upper()} {pairs[0][1].zfill(6)}",
        })
    return drugs


def main() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    print("EMA: matching 2026 authorisations to assessment reports")
    candidates = ema_candidates()
    print(f"EMA medicines to screen: {len(candidates)}")
    ema_results = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(screen_ema_one, item) for item in candidates]
        for done, future in enumerate(as_completed(futures), 1):
            result = future.result()
            ema_results.append(result)
            if done % 5 == 0 or result.get("status") == "hit":
                print(f"  EMA {done}/{len(candidates)} {result.get('drug')}: {result.get('status')}", flush=True)
    ema_results.sort(key=lambda row: row.get("drug") or "")

    print("FDA: reading the 2026 novel-approval list and FDA’s published RWE examples")
    drugs = novel_drugs()
    listed = {normalize_name(drug["drug"]) for drug in drugs}
    for extra in published_example_drugs():
        if normalize_name(extra["drug"]) in listed:
            continue
        listed.add(normalize_name(extra["drug"]))
        drugs.append(extra)
    print(f"FDA products to screen: {len(drugs)}")
    fda_results = []
    for index, drug in enumerate(drugs, 1):
        print(f"  FDA {index}/{len(drugs)} {drug['drug']}", flush=True)
        fda_results.append(screen_fda_one(drug))
        time.sleep(0.25)
        if index % 5 == 0:
            write_outputs(ema_results, fda_results)
    write_outputs(ema_results, fda_results)


if __name__ == "__main__":
    main()
