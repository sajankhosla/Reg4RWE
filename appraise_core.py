"""Match a proposed real-world study to regulatory precedent in the corpus."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "data" / "corpus.json"

STOP = {
    "the", "and", "for", "with", "from", "that", "this", "were", "was", "are",
    "been", "have", "has", "had", "not", "but", "its", "their", "they", "into",
    "using", "used", "use", "data", "study", "studies", "patients", "patient",
    "real", "world", "evidence", "rwe", "rwd",
}

PHRASES = (
    "external control", "historical control", "natural history", "chart review",
    "registry", "claims", "sentinel", "electronic health", "pregnancy",
    "pediatric", "paediatric", "oncolog", "rare disease", "single-arm",
    "single arm", "confounding", "propensity", "matching", "vaccine",
)


def load_corpus(path: Path | None = None) -> dict:
    return json.loads((path or CORPUS).read_text())


def tokens(text: str) -> set[str]:
    return {
        word for word in re.findall(r"[a-z0-9]{4,}", (text or "").lower())
        if word not in STOP
    }


def record_blob(record: dict) -> str:
    settings = " ".join(item.get("label", "") for item in record.get("settings") or [])
    judgements = " ".join(item.get("label", "") for item in record.get("judgements") or [])
    return " ".join(
        str(record.get(key) or "")
        for key in (
            "drug", "indication", "assessment", "issues", "quote", "role",
            "design", "data_source", "comparator", "rwe_type", "decision",
            "question", "summary", "location_note", "theme1", "theme2",
        )
    ) + " " + settings + " " + judgements


def score_record(record: dict, query_tokens: set[str], query_text: str) -> int:
    blob = record_blob(record).lower()
    overlap = query_tokens & tokens(blob)
    score = len(overlap)
    for phrase in PHRASES:
        if phrase in query_text and phrase in blob:
            score += 4
    return score


def precedent_lines(record: dict) -> list[str]:
    where = record.get("location_note") or ""
    if record.get("page") and record.get("document_title"):
        place = f"Page {record['page']} of the {record['document_title']}"
        if record.get("section"):
            place += f", under “{record['section']}”"
        where = place
    link = record.get("document_url") or record.get("fda_example_url") or record.get("source_url") or ""
    if record.get("page") and record.get("document_url"):
        link = f"{record['document_url']}#page={record['page']}"
    judgements = ", ".join(item.get("label", "") for item in record.get("judgements") or [])
    lines = [
        f"### {record.get('drug') or 'Unnamed product'} — {record.get('agency') or ''}, {record.get('year') or 'year not recorded'}",
        f"- Application: {record.get('application') or 'not recorded'}",
        f"- How the evidence was used: {record.get('decision') or 'not recorded'}",
        f"- Question: {record.get('question') or 'not recorded'}",
        f"- Feedback tags: {judgements or 'none recorded'}",
    ]
    if record.get("needs_manual_review"):
        lines.append("- This entry still needs manual review.")
    if where:
        lines.append(f"- Where this sits: {where}")
    if record.get("issues") and record["issues"].lower() not in ("n/a", "not specified", ""):
        lines.append(f"- Methodological note: {record['issues']}")
    quote = (record.get("quote") or "").strip()
    if quote:
        lines.append(f"- Regulator’s words: {quote}")
    if link:
        lines.append(f"- Document: {link}")
    return lines


def recurring_feedback(records: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for record in records:
        for item in record.get("judgements") or []:
            label = item.get("label") or ""
            if label:
                counts[label] = counts.get(label, 0) + 1
    if not counts:
        return ["The closest records do not carry a coded methodological critique."]
    ordered = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return [f"{label} ({count} of these precedents)" for label, count in ordered]


def appraise(design: str, limit: int = 8) -> str:
    text = re.sub(r"\s+", " ", design or "").strip()
    if len(text) < 20:
        return (
            "The design is too thin to match to regulatory precedent. "
            "Describe the question, the data source, the population, the comparator, "
            "and what decision the evidence is meant to support."
        )
    corpus = load_corpus()
    query_tokens = tokens(text)
    lowered = text.lower()
    ranked = []
    for record in corpus.get("records") or []:
        value = score_record(record, query_tokens, lowered)
        if value:
            ranked.append((value, record))
    ranked.sort(key=lambda item: (-item[0], item[1].get("drug") or ""))
    chosen = [record for _score, record in ranked[:limit]]
    if not chosen:
        return "No regulatory record in Reg4RWE shares enough language with this design to cite as precedent."
    lines = [
        "# Regulatory precedent for this design",
        "",
        "These points are drawn from public FDA reviews and EMA assessment reports in Reg4RWE. "
        "They are precedents to weigh. They are not a new regulatory opinion.",
        "",
        "## Closest precedents",
        "",
    ]
    for record in chosen:
        lines.extend(precedent_lines(record))
        lines.append("")
    lines.append("## Feedback that recurs in these precedents")
    lines.append("")
    for point in recurring_feedback(chosen):
        lines.append(f"- {point}")
    lines.append("")
    lines.append("## What to take into a critical appraisal")
    lines.append("")
    lines.append(
        "Compare the proposed data source, comparator, and analysis with the precedents above. "
        "Name which objections those regulators actually recorded, and which designs they still used."
    )
    return "\n".join(lines).strip() + "\n"
