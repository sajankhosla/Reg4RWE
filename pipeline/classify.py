"""Shared labels for FDA reviews and EMA European public assessment reports.

The decision groups are the same presentational groups used for the Chapter 2
figures. Question groups collapse the free-text Jansen theme 1 labels. Setting
and judgement tags are read off the extracted text so a document can be opened
from more than one layer.
"""

from __future__ import annotations

import re

# "Sentinel subjects" and "natural history of the disease" are ordinary clinical
# language. The screen asks for a study, a data source, or a designed comparison.
RWE_TERMS = [
    r"\bRWE\b",
    r"\bRWD\b",
    r"real[-\s]?world evidence",
    r"real[-\s]?world data",
    r"real world matched",
    r"external control",
    r"historical controls?(?!\s+(?:range|limit))",
    r"synthetic control",
    r"natural history (?:study|data|control|cohort|comparison)",
    r"chart review",
    r"electronic health record",
    r"\bEHR\b",
    r"Sentinel (?:System|Initiative|study)",
    r"Mini-Sentinel",
]
TERM_RE = re.compile("|".join(RWE_TERMS), re.IGNORECASE)

# A passing passage has to describe a study or a judgement. A bare mention of
# patients in a guidance paragraph does not.
PASSAGE_MARKERS = [
    "external control",
    "historical control",
    "synthetic control",
    "natural history",
    "registry",
    "claims",
    "sentinel",
    "electronic health record",
    "chart review",
    "observational",
    "retrospective",
    "confound",
    "bias",
    "limitation",
    "fit for use",
    "supportive",
    "insufficient",
    "not generalizable",
    "not generalisable",
    "propensity",
]

DECISIONS = [
    ("pivotal", "Effectiveness: pivotal or substantial evidence"),
    ("supportive", "Effectiveness: supportive or contextual"),
    ("safety", "Safety, labelling or REMS action"),
    ("other", "Other (PMR/PMC, policy evaluation)"),
    ("unclear", "Role unclear"),
    ("none", "No RWE content identified"),
]

QUESTIONS = [
    ("safety", "Post-approval safety and labelling"),
    ("benefit", "Benefit–risk, including external comparators"),
    ("context", "Disease context, natural history and generalisability"),
    ("trial", "Support to a clinical trial"),
    ("other", "Other question"),
    ("none", "No question recorded"),
]

SETTINGS = [
    ("pregnancy", "Pregnancy", ["pregnan"]),
    ("paediatric", "Paediatric use", ["pediatric", "paediatric"]),
    ("vaccine", "Vaccines", ["vaccine"]),
    ("rare", "Rare disease", ["rare disease", "orphan", "ultra-rare", "natural history"]),
    ("rems", "REMS", ["rems"]),
    ("class_risk", "Class-wide or boxed warning", ["class-wide", "class effect", "boxed warning"]),
    ("oncology", "Oncology", [
        "carcinoma", "lymphoma", "leukemia", "leukaemia", "myeloma", "melanoma",
        "cancer", "tumour", "tumor", "nsclc", "glioma", "sarcoma", "oncolog",
    ]),
]

JUDGEMENTS = [
    ("confounding", "Confounding and comparability",
     ["confound", "comparab", "not comparable", "imbalance", "propensity", "residual"]),
    ("missing", "Missing or thin information",
     ["missing", "limited exposed", "small sample", "no pk data"]),
    ("selection", "Selection",
     ["selection bias", "matched analysis", "heterogeneous data"]),
    ("ascertainment", "Outcome ascertainment and validation",
     ["ascertain", "validation", "vital status", "outcome ascertainment"]),
    ("generalisability", "Generalisability",
     ["generali", "not representative", "population difference", "population not comparable"]),
    ("provenance", "Data provenance and patient-level data",
     ["patient-level", "individual patient", "aggregate data", "provenance"]),
    ("accepted", "Weighed and accepted for the decision",
     ["fit for use", "do not outweigh", "adequate and well-controlled",
      "confirmatory evidence", "primary evidence", "primary comparative", "exemplary"]),
    ("insufficient", "Not relied on, or judged insufficient",
     ["insufficient", "not generalizable", "not generalisable", "threaten the validity",
      "should not be considered", "disagreed", "validity questionable",
      "prognostic value uncertain", "unlikely to be generalizable"]),
]

NA_ISSUES = {"", "n/a", "not specified", "not recorded", "none", "none identified"}


def norm_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def decision_group(agency: str, role: str, theme1: str) -> tuple[str, str]:
    """Return (id, label). FDA rules match the Chapter 2 figure grouping."""
    labels = dict(DECISIONS)
    if agency == "EMA":
        mapped = {
            "Pivotal/primary evidence": "pivotal",
            "Confirmatory evidence": "supportive",
            "Supportive evidence": "supportive",
            "Safety/labeling assessment": "safety",
        }.get((role or "").strip(), "unclear")
        return mapped, labels[mapped]

    t1, role_l = (theme1 or "").lower(), (role or "").lower()
    if role_l in ("n/a", "") or t1 == "n/a":
        key = "none"
    elif "safety" in t1 or any(w in role_l for w in ("label", "boxed", "dsc", "rems", "warning", "safety")):
        key = "safety"
    elif any(w in role_l for w in ("pivotal", "substantial evidence", "adequate and well-controlled")):
        key = "pivotal"
    elif any(w in role_l for w in (
        "supportive", "historical control", "context", "extrapolation",
        "external control", "representativeness", "conversion",
    )):
        key = "supportive"
    else:
        key = "other"
    return key, labels[key]


def question_group(theme1: str) -> tuple[str, str]:
    labels = dict(QUESTIONS)
    low = (theme1 or "").strip().lower()
    if low in ("", "n/a", "not specified"):
        key = "none"
    elif "safety" in low or "post-approval" in low:
        key = "safety"
    elif any(w in low for w in ("external", "confirmatory", "benefit-risk", "benefit–risk", "supportive evidence")):
        key = "benefit"
    elif any(w in low for w in ("epidemi", "natural history", "generali", "context", "extrapolation")):
        key = "context"
    elif any(w in low for w in ("endpoint", "clinical trial")):
        key = "trial"
    else:
        key = "other"
    return key, labels[key]


def setting_tags(*parts: str) -> list[dict]:
    blob = " ".join(parts).lower()
    found = []
    for sid, label, keys in SETTINGS:
        if any(k in blob for k in keys):
            found.append({"id": sid, "label": label})
    if not found:
        found.append({"id": "other", "label": "Other or not specified"})
    return found


def judgement_tags(issues: str, assessment: str, quote: str) -> list[dict]:
    blob = " ".join([issues or "", assessment or "", quote or ""]).lower()
    found = []
    for jid, label, keys in JUDGEMENTS:
        if any(k in blob for k in keys):
            found.append({"id": jid, "label": label})
    if found:
        return found
    low = norm_space(issues).lower()
    if "none significant" in low or low.startswith("none —") or low.startswith("none -"):
        return [{"id": "none_major", "label": "No major methodological critique recorded"}]
    return [{"id": "not_recorded", "label": "No methodological critique recorded"}]


NONCLINICAL = (
    "foetus", "fetus", "embryo", "rabbit", "mg/kg", "carcinogenicity",
    "resorption", "litter", "rats", "mice", "mouse", "spermat", "maternal animal",
)
STRONG_CLINICAL = (
    "real-world", "real world", "chart review", "natural history study",
    "natural history data", "natural history cohort", "natural history control",
    "registry", "external control arm", "historical control group",
    "historical control arm", "sentinel system", "sentinel study",
)


def is_nonclinical(snippet: str) -> bool:
    low = snippet.lower()
    strong = any(marker in low for marker in STRONG_CLINICAL)
    if any(marker in low for marker in NONCLINICAL) and not strong:
        return True
    # Laboratory and animal "historical controls" are not an external comparator.
    if "historical control" in low and not strong:
        clinical = any(word in low for word in ("patient", "efficacy", "survival", "progression", "cohort"))
        animal = any(word in low for word in ("animal", "sperm", "whole blood", "neoplastic", "donor"))
        if animal or not clinical:
            return True
    return False


def is_not_a_study_passage(snippet: str) -> bool:
    """Drop software mentions of an electronic record and bibliography lines."""
    low = snippet.lower()
    study_language = (
        "external control", "historical control", "natural history study",
        "natural history data", "natural history cohort", "real-world evidence",
        "real-world data", "real world evidence", "real world data",
        "chart review study", "observational study", "the applicant", "the study will",
    )
    if "electronic health record" in low and not any(phrase in low for phrase in study_language):
        return True
    citation = "doi" in low or "accessed " in low or "et al" in low
    if citation and not any(phrase in low for phrase in study_language):
        return True
    return False


def is_boilerplate(snippet: str) -> bool:
    """The EPAR template asks, as an unchecked box, whether observational RWD were submitted."""
    low = snippet.lower()
    if "designed to capture patient experience" in low:
        return True
    if "patient experience data" in low and "real-world evidence" not in low and "real-world data" not in low and "external control" not in low:
        return True
    if "☐" in snippet or "□" in snippet:
        return True
    return False


def relevant_snippets(text: str, window: int = 320, limit: int = 4) -> list[str]:
    snippets = []
    seen = set()
    for match in TERM_RE.finditer(text or ""):
        start = max(match.start() - window, 0)
        end = min(match.end() + window, len(text))
        snippet = norm_space(text[start:end])
        low = snippet.lower()
        if is_boilerplate(snippet) or is_nonclinical(snippet):
            continue
        if snippet.count("..") > 3 or snippet.count(".") > 25:
            continue
        if is_not_a_study_passage(snippet):
            continue
        if not any(marker in low for marker in PASSAGE_MARKERS):
            continue
        key = snippet[:180]
        if key in seen:
            continue
        seen.add(key)
        snippets.append(snippet[:700])
        if len(snippets) >= limit:
            break
    return snippets


def classify_passage(text: str) -> dict:
    """Rule-based fields for a newly screened document. Curated rows are not re-coded."""
    low = (text or "").lower()

    if "external control" in low or "historical control" in low or "synthetic control" in low:
        rwe_type = "External control from RWD"
    elif "natural history" in low:
        rwe_type = "Natural history study"
    elif "registry" in low:
        rwe_type = "Registry data"
    elif "claims" in low or "sentinel" in low:
        rwe_type = "Claims or Sentinel data"
    elif "electronic health record" in low or re.search(r"\behr\b", low):
        rwe_type = "EHR data"
    elif "observational" in low or "retrospective" in low:
        rwe_type = "Observational real-world data"
    else:
        rwe_type = "RWE mentioned (unspecified)"

    if "retrospective cohort" in low:
        design = "Retrospective cohort study"
    elif "externally controlled" in low or "external control" in low:
        design = "Externally controlled trial"
    elif "prospective" in low and "registry" in low:
        design = "Prospective registry study"
    elif "registry" in low:
        design = "Registry-based observational study"
    elif "observational" in low or "retrospective" in low:
        design = "Observational study"
    else:
        design = "Not specified by the screen"

    if "pivotal" in low or "primary evidence" in low or "adequate and well-controlled" in low:
        role = "Pivotal or substantial evidence"
    elif "confirmatory" in low:
        role = "Confirmatory evidence"
    elif "support" in low:
        role = "Supportive evidence"
    elif any(w in low for w in ("label", "warning", "safety", "rems")):
        role = "Safety or labelling assessment"
    else:
        role = "RWE mentioned (role unclear)"

    if "natural history" in low:
        theme1 = "Epidemiology - natural history"
    elif "external control" in low or "historical control" in low:
        theme1 = "Benefit-risk assessment; External control"
    elif any(w in low for w in ("label", "warning", "rems", "safety")):
        theme1 = "Post-approval safety monitoring"
    else:
        theme1 = "Not specified"

    issue = "Not specified"
    for sentence in re.split(r"(?<=[.!?])\s+", norm_space(text)):
        if any(w in sentence.lower() for w in ("confound", "bias", "limitation", "missing", "insufficient", "not generaliz")):
            issue = sentence[:320]
            break

    return {
        "rwe_type": rwe_type,
        "design": design,
        "role": role,
        "theme1": theme1,
        "issues": issue,
    }
