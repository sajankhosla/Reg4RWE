#!/usr/bin/env python3
"""Build data/corpus.json for the regulatory feedback navigator.

Reads the January 2026 curated FDA and EMA extracts without modifying them.
If pipeline/update_search.py has written data/search_update/hits.json, those
machine-screened records are appended and kept distinct.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from classify import (  # noqa: E402
    DECISIONS,
    JUDGEMENTS,
    QUESTIONS,
    SETTINGS,
    decision_group,
    judgement_tags,
    norm_space,
    question_group,
    setting_tags,
)

ROOT = Path(__file__).resolve().parents[1]
CHAPTER = ROOT.parent
CURATED = {
    "FDA": CHAPTER / "SLR_Execution/data_extraction/FDA_RWE_Complete_Extraction_All_Documents.csv",
    "EMA": CHAPTER / "SLR_Execution/data_extraction/ema/EMA_RWE_Complete_Extraction_2015_2025.csv",
}
HITS = ROOT / "data" / "search_update" / "hits.json"
MANIFEST = ROOT / "data" / "search_update" / "manifest.json"
MEDICINES = ROOT / "data" / "cache" / "medicines.json"
LOCATIONS = ROOT / "data" / "locations.json"
FDA_EXAMPLES = ROOT / "data" / "fda_examples.json"
OUT = ROOT / "data" / "corpus.json"
CURATED_DIR = ROOT / "data" / "curated"

LESSONS = {
    "decision": {
        "pivotal": "The regulator treated the real-world comparison as evidence that could carry the effectiveness decision. Read the quote for what had to be true: patient-level data, a large effect, or a disease where a randomised trial was not feasible.",
        "supportive": "Real-world evidence was used to interpret a trial, describe the disease, or support a subset. The decision did not rest on it alone, and the critique is often about whether the comparison was fair.",
        "safety": "This is the largest FDA group. A study informed a label, a warning, or a REMS. The extraction usually records the action and the data source. A methods critique was often not written down.",
        "other": "The evidence sits beside the decision: a post-marketing commitment, a policy evaluation, or a use the January coding did not place under effectiveness or safety.",
        "unclear": "The European public assessment report uses real-world language, but the January screen could not tell what job the evidence did. Start from the extracted passage and decide the role yourself.",
        "none": "These FDA rows were kept so the denominator stays honest. The curation did not find real-world evidence doing work in the decision.",
    },
    "question": {
        "safety": "The question was what happens after approval: a risk, a pregnancy outcome, a class effect, or the effect of a labelling change.",
        "benefit": "The question was whether the treated patients did better than a fair comparison, often an external or natural-history control, or whether the benefit–risk case was supported.",
        "context": "The question was descriptive. How does the disease behave, who is treated, and does the trial population look like practice?",
        "trial": "Real-world data were asked to supply something a trial needed, such as an endpoint the trial itself did not ascertain.",
        "other": "The coded question does not fall into safety, benefit–risk, or disease context.",
        "none": "No Jansen theme 1 was recorded. For the EMA rows this usually means the screen found a term and stopped.",
    },
    "setting": {
        "pregnancy": "Exposure and outcomes that a pre-approval trial could not enrol. Registries and Sentinel analyses are the usual sources.",
        "paediatric": "Adult evidence was being extended, or a paediatric safety or growth question was answered outside a new randomised trial.",
        "vaccine": "Post-authorisation vaccine safety, including temporal associations that later became warnings.",
        "rare": "Small populations, natural history, and external controls. This is where an imperfect comparison is sometimes still accepted.",
        "rems": "The question was whether a risk programme changed use or harm, not whether the drug worked.",
        "class_risk": "A signal was examined across a class, and the feedback is often that one drug’s finding did not automatically apply to the others.",
        "oncology": "Single-arm trials are common here, so real-world data are asked to describe prognosis or to stand in as a comparison.",
        "other": "The setting was not coded as pregnancy, paediatric use, vaccines, rare disease, REMS, a class warning, or oncology.",
    },
    "judgement": {
        "confounding": "The groups were not obviously alike, or something important was unmeasured. Look for ECOG, prognosis, and concomitant therapy.",
        "missing": "A variable, an outcome count, or a pharmacokinetic bridge was too thin to interpret.",
        "selection": "Who entered the real-world cohort, or who was left after matching, may have created the result.",
        "ascertainment": "The regulator asked how an outcome, often death or response, was actually known.",
        "generalisability": "The real-world cohort was not accepted as a picture of the patients the decision was about.",
        "provenance": "The feedback turns on whether the regulator could see patient-level data and where those data came from.",
        "accepted": "Limits were named, and the decision still used the evidence. The reason is usually the size of the effect or the rarity and seriousness of the disease.",
        "insufficient": "The evidence was described and then not relied on. The reason is specific: bias, a crude analysis, or a population that does not travel.",
        "none_major": "The curation recorded that the design did not attract a substantial methods critique.",
        "not_recorded": "The row records what the evidence was used for, and does not record a methodological objection. That is common for safety actions in the January file.",
    },
}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def fda_url(application: str) -> str:
    digits = re.findall(r"\d{5,6}", application or "")
    if not digits:
        return ""
    return (
        "https://www.accessdata.fda.gov/scripts/cder/daf/index.cfm"
        f"?event=overview.process&ApplNo={digits[0]}"
    )


def ema_urls() -> dict[str, str]:
    if not MEDICINES.exists():
        return {}
    data = json.loads(MEDICINES.read_text())["data"]
    urls = {}
    for row in data:
        number = (row.get("ema_product_number") or "").strip()
        url = (row.get("medicine_url") or "").strip()
        if number and url:
            urls[number] = url
    return urls


def clean_quote(value: str, limit: int = 520) -> str:
    text = norm_space(value)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    stop = max(cut.rfind(". "), cut.rfind("; "))
    if stop > 240:
        return cut[: stop + 1]
    return cut.rstrip() + "…"


def record_from_curated(agency: str, index: int, row: dict, urls: dict[str, str]) -> dict:
    application = norm_space(row.get("Application_Number"))
    assessment = norm_space(row.get("FDA_Assessment_Summary"))
    issues = norm_space(row.get("Key_Methodological_Issues"))
    quote = clean_quote(row.get("Key_Quote") or "")
    theme1 = norm_space(row.get("Jansen_Theme1_Alignment"))
    role = norm_space(row.get("Role_of_RWE"))
    decision_id, decision_label = decision_group(agency, role, theme1)
    question_id, question_label = question_group(theme1)
    indication = norm_space(row.get("Indication"))
    settings = setting_tags(theme1, norm_space(row.get("Jansen_Theme2_Alignment")), indication, role)
    judgements = judgement_tags(issues, assessment, quote)
    if assessment and not assessment.startswith("EMA EPAR mentions") and not assessment.startswith("October 2026 machine screen") and assessment.lower() not in ("n/a", "not specified") and len(assessment) > 40:
        summary = assessment
    elif quote[:1].isupper() and quote.count(" - ") < 3:
        summary = quote[:280]
    else:
        bits = [bit for bit in (role, norm_space(row.get("RWE_Type"))) if bit and bit.lower() not in ("n/a", "not specified")]
        summary = ". ".join(bits) + "." if bits else "No assessment text recorded."
    source_url = row.get("source_url") or ""
    if not source_url:
        source_url = urls.get(application, "") if agency == "EMA" else fda_url(application)
    year = norm_space(row.get("Year"))[:4]
    return {
        "id": f"{agency}-{index:03d}",
        "agency": agency,
        "origin": "january-2026-curated",
        "needs_manual_review": False,
        "curation": "",
        "drug": norm_space(row.get("Drug_Name")),
        "application": application,
        "year": year,
        "indication": indication,
        "rwe_type": norm_space(row.get("RWE_Type")),
        "data_source": norm_space(row.get("Data_Source")),
        "design": norm_space(row.get("Study_Design")),
        "comparator": norm_space(row.get("Comparator")),
        "role": role,
        "theme1": theme1,
        "theme2": norm_space(row.get("Jansen_Theme2_Alignment")),
        "assessment": assessment,
        "issues": issues,
        "quote": quote,
        "summary": summary,
        "confidence": norm_space(row.get("Confidence_Score")),
        "decision_id": decision_id,
        "decision": decision_label,
        "question_id": question_id,
        "question": question_label,
        "settings": settings,
        "judgements": judgements,
        "source_url": source_url,
        "document_url": row.get("document_url") or "",
    }


def record_from_hit(hit: dict, index: int) -> dict:
    agency = hit["agency"]
    row = record_from_curated(agency, index, hit, {})
    row["id"] = hit.get("id") or f"{agency}-U{index:03d}"
    row["origin"] = "october-2026-screen"
    row["needs_manual_review"] = True
    row["curation"] = (
        "Needs manual review. The fields were assembled from the public document "
        "and have not been checked line by line."
    )
    row["source_url"] = hit.get("source_url") or row["source_url"]
    row["document_url"] = hit.get("document_url") or ""
    row["screen_note"] = hit.get("screen_note") or ""
    return row


def apply_locations(records: list[dict]) -> None:
    if not LOCATIONS.exists():
        return
    locations = json.loads(LOCATIONS.read_text())
    for record in records:
        located = locations.get(record["id"]) or {}
        if located.get("document_url"):
            record["document_url"] = located["document_url"]
        for key in ("document_title", "page", "section", "location_note", "location_kind", "fda_example_url"):
            if located.get(key) not in (None, ""):
                record[key] = located[key]


        if "The January curation recorded a summary" in str(record.get("location_note") or ""):
            record["location_note"] = (
                f"The linked file is the {record.get('document_title') or 'public review'} posted for this application. "
                "The wording in this navigator summarises the assessment."
            )
        elif "The file is too large" in str(record.get("location_note") or ""):
            record["location_note"] = record["location_note"].replace(
                "The January curation recorded a summary of the assessment in its own words.",
                "The wording in this navigator summarises the assessment.",
            )


def example_drug_name(product: str) -> str:
    head = re.split(r"\b(?:NDA|BLA|Multiple)\b", product or "", maxsplit=1, flags=re.I)[0]
    head = head.replace("®", "").replace("™", "")
    return norm_space(head).strip(" ,;/") or norm_space(product)


def example_application(product: str) -> str:
    if re.search(r"\bMultiple\b", product or ""):
        return "Multiple BLAs" if re.search(r"\bBLA\b", product or "") else "Multiple NDAs"
    pairs = re.findall(r"(NDA|BLA)\s*(\d{5,6})", product or "", flags=re.I)
    return "; ".join(f"{kind.upper()} {number.zfill(6)}" for kind, number in pairs)


def record_from_fda_example(example: dict) -> dict:
    summary = norm_space(example.get("summary") or "")
    action = example.get("action") or ""
    text = f"{summary} {action}".lower()
    table = example.get("table_id") or ""
    if table == "cder-approvals" and any(word in text for word in (
        "confirmatory", "substantial evidence", "contributed to see", "effectiveness", "efficacy",
    )):
        role, theme1 = "supportive evidence", "Benefit-risk including external comparators"
    elif table in ("cder-postmarketing", "cber-safety") or "safety" in text or "labeling" in text:
        role, theme1 = "labeling", "Post-approval safety and labelling"
    else:
        role, theme1 = "supportive evidence", "Benefit-risk including external comparators"
    decision_id, decision_label = decision_group("FDA", role, theme1)
    question_id, question_label = question_group(theme1)
    drug = example_drug_name(example.get("product") or "")
    application = example_application(example.get("product") or "")
    dates = re.findall(r"(\d{1,2})/(\d{1,2})/(\d{4})", action)
    year = dates[-1][2] if dates else ""
    settings = setting_tags(theme1, summary, drug, role)
    judgements = judgement_tags("", summary, summary)
    return {
        "id": "FDA-EX-" + example["id"],
        "agency": "FDA",
        "origin": "fda-published-example",
        "needs_manual_review": True,
        "curation": (
            "Needs manual review. FDA published this example, and the review "
            "has not been checked line by line."
        ),
        "drug": drug,
        "application": application,
        "year": year,
        "indication": "",
        "rwe_type": "",
        "data_source": "",
        "design": "",
        "comparator": "",
        "role": role,
        "theme1": theme1,
        "theme2": "",
        "assessment": summary,
        "issues": "",
        "quote": summary,
        "summary": summary[:280],
        "confidence": "",
        "decision_id": decision_id,
        "decision": decision_label,
        "question_id": question_id,
        "question": question_label,
        "settings": settings,
        "judgements": judgements,
        "source_url": fda_url(application) if re.search(r"\d{5,6}", application) else "",
        "document_url": "",
        "fda_example_url": example.get("url") or "",
        "location_note": (
            "This wording is FDA’s published example. "
            "The page of the review has not been checked yet."
        ),
    }


def add_unmatched_fda_examples(records: list[dict], release: dict | None) -> dict | None:
    if not release:
        return None
    from locate_documents import compare

    examples = list(release.get("in_both") or []) + list(release.get("fda_only") or [])
    if not examples:
        return release
    current = compare(examples, records)
    existing = {record["id"] for record in records}
    for example in current["fda_only"]:
        record = record_from_fda_example(example)
        if record["id"] not in existing:
            records.append(record)
            existing.add(record["id"])
    return compare(examples, records)


def layer_block(key: str, records: list[dict], id_field: str, label_field: str, order: list[tuple[str, str]]) -> dict:
    grouped: dict[str, list[dict]] = {item_id: [] for item_id, _label in order}
    labels = dict(order)
    for record in records:
        if id_field == "settings":
            ids = [item["id"] for item in record["settings"]]
        elif id_field == "judgements":
            ids = [item["id"] for item in record["judgements"]]
        else:
            ids = [record[id_field]]
        for item_id in ids:
            grouped.setdefault(item_id, []).append(record)
            labels.setdefault(item_id, item_id)
    categories = []
    for item_id, _label in order:
        rows = grouped.get(item_id, [])
        if not rows and item_id not in labels:
            continue
        agencies = Counter(row["agency"] for row in rows)
        categories.append({
            "id": item_id,
            "label": labels.get(item_id, item_id),
            "lesson": LESSONS[key].get(item_id, ""),
            "count": len(rows),
            "fda": agencies.get("FDA", 0),
            "ema": agencies.get("EMA", 0),
        })
    extra = [item_id for item_id in grouped if item_id not in dict(order)]
    for item_id in extra:
        rows = grouped[item_id]
        agencies = Counter(row["agency"] for row in rows)
        categories.append({
            "id": item_id,
            "label": labels.get(item_id, item_id),
            "lesson": LESSONS[key].get(item_id, ""),
            "count": len(rows),
            "fda": agencies.get("FDA", 0),
            "ema": agencies.get("EMA", 0),
        })
    return {
        "id": key,
        "categories": [cat for cat in categories if cat["count"] or key == "decision"],
    }


def main() -> None:
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    urls = ema_urls()
    records = []
    for agency, path in CURATED.items():
        if not path.exists():
            sys.exit(f"Missing curated extract: {path}")
        shutil.copy2(path, CURATED_DIR / path.name)
        for index, row in enumerate(read_csv(path), 1):
            records.append(record_from_curated(agency, index, row, urls))

    screened = []
    if HITS.exists():
        screened = json.loads(HITS.read_text())
        for index, hit in enumerate(screened, 1):
            records.append(record_from_hit(hit, index))

    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else None
    prior_release = json.loads(FDA_EXAMPLES.read_text()) if FDA_EXAMPLES.exists() else None
    fda_release = add_unmatched_fda_examples(records, prior_release)
    curated = [row for row in records if row["origin"] == "january-2026-curated"]
    update = [row for row in records if row.get("needs_manual_review")]
    fda = [row for row in curated if row["agency"] == "FDA"]
    ema = [row for row in curated if row["agency"] == "EMA"]

    layers = {
        "decision": {
            **layer_block("decision", records, "decision_id", "decision", DECISIONS),
            "title": "How the evidence was used",
            "orientation": (
                "Start here. Each document is placed by what the regulator did with the "
                "real-world evidence. The groups are the ones used in the Chapter 2 figures. "
                "A document sits in one decision group."
            ),
        },
        "question": {
            **layer_block("question", records, "question_id", "question", QUESTIONS),
            "title": "What question it was asked to answer",
            "orientation": (
                "Jansen and colleagues separate the questions real-world evidence can answer. "
                "Theme 1 in the extraction is collapsed here so the same question can be read "
                "across both agencies. A document sits in one question group."
            ),
        },
        "setting": {
            **layer_block("setting", records, "settings", "settings", [(s, lab) for s, lab, _k in SETTINGS] + [("other", "Other or not specified")]),
            "title": "The setting that made it necessary",
            "orientation": (
                "The same document can appear in more than one setting. Tags are read from the "
                "indication, the role, and Jansen theme 2. Use this layer to see how feedback "
                "differs for pregnancy, children, rare disease, vaccines, and oncology."
            ),
        },
        "judgement": {
            **layer_block(
                "judgement",
                records,
                "judgements",
                "judgements",
                [(j, lab) for j, lab, _k in JUDGEMENTS] + [
                    ("none_major", "No major methodological critique recorded"),
                    ("not_recorded", "No methodological critique recorded"),
                ],
            ),
            "title": "What the regulator accepted or criticised",
            "orientation": (
                "This is the feedback layer. Tags are read from the assessment, the methodological "
                "issues, and the extracted passage. A document can carry more than one tag. "
                "Where the January file recorded no critique, that absence is kept visible."
            ),
        },
    }

    # Drop empty decision categories only if count is zero and they are not part of the fixed list.
    # Keep zeros for the fixed decision list so the chapter grouping stays visible.
    for layer in layers.values():
        if layer["id"] != "decision":
            layer["categories"] = [cat for cat in layer["categories"] if cat["count"]]

    apply_locations(records)

    corpus = {
        "title": "Real-world evidence feedback",
        "built_on": "2026-10-24",
        "previous_search": "2026-01-19",
        "intro": [
            f"{len(records)} public FDA reviews and EMA assessment reports are in this navigator.",
            f"{len(update)} of them still need manual review.",
            "Read a document in four layers: the decision, the question the evidence was asked to answer, the setting, and the judgement in the regulator’s own words where those words were extracted.",
        ],
        "counts": {
            "documents": len(records),
            "curated": len(curated),
            "screened": len(update),
            "needs_manual_review": len(update),
            "fda_curated": len(fda),
            "ema_curated": len(ema),
        },
        "layers": layers,
        "records": records,
        "search_update": manifest,
        "fda_release": fda_release,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(corpus, ensure_ascii=False, indent=2))
    print(f"Wrote {OUT} with {len(records)} records ({len(curated)} curated, {len(update)} screened)")
    for name, layer in layers.items():
        print(name, [(cat["id"], cat["count"]) for cat in layer["categories"]])


if __name__ == "__main__":
    main()
