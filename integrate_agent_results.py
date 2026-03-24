# ============================================================
# CAPTIVE ANIMAL MICROBIOME — SYSTEMATIC REVIEW
# Claude API Extraction Pipeline  (v3 — two-stage)
# ============================================================
#
# TWO-STAGE WORKFLOW:
#
#   Stage 1 — ABSTRACT SCREEN + EXTRACT
#     • Claude reads title + abstract only
#     • Decision: include / exclude / needs_full_text
#     • For includes: extracts what it can, flags gaps as NEEDS_FULL_TEXT
#     • For needs_full_text: couldn't even decide in/out from abstract
#
#   Stage 2 — HUMAN / FULL-TEXT REVIEW
#     • Pipeline generates a review queue CSV listing:
#         - Papers where screening itself is uncertain
#         - Included papers with NEEDS_FULL_TEXT fields
#     • Your team retrieves PDFs (via DOI + institutional access)
#       and fills in the gaps manually
#
# CALIBRATION:
#   Run the excluded collection first to verify Claude correctly
#   rejects papers it should. A sample of excluded-paper patterns
#   is also embedded in the prompt as few-shot examples.
#
# Usage:
#   python extract_pipeline.py                              # pilot (default)
#   python extract_pipeline.py --collection todo            # full run
#   python extract_pipeline.py --collection todo --resume   # resume
#   python extract_pipeline.py --collection excluded        # calibration
#   python extract_pipeline.py --collection todo --limit 20 # debug
# ============================================================

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from pyzotero import zotero
import anthropic

# ── LOAD .env ────────────────────────────────────────────────
load_dotenv()

ZOTERO_API_KEY    = os.environ.get("ZOTERO_API_KEY")
ZOTERO_LIBRARY_ID = os.environ.get("ZOTERO_LIBRARY_ID")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
LIBRARY_TYPE      = "group"

# ── ZOTERO COLLECTION KEYS ──────────────────────────────────
COLLECTIONS = {
    "pilot":    "P2W5GAWL",   # 10 manually-validated papers
    "included": "ZQS4ZZVG",   # 165 already-included papers
    "excluded": "C9G9MIC9",   # Known-excluded papers — calibration
    "todo":     "SALMNXDQ",   # 1,122 unprocessed papers
}

# ── MODEL ────────────────────────────────────────────────────
MODEL      = "claude-sonnet-4-6"
MAX_TOKENS = 4000

# ── RETRY SETTINGS ───────────────────────────────────────────
MAX_RETRIES    = 3
RETRY_BASE_SEC = 2
PAUSE_BETWEEN  = 0.6

# ── DIRECTORIES ──────────────────────────────────────────────
OUTPUT_DIR = Path("outputs")
OUTPUT_DIR.mkdir(exist_ok=True)


# ════════════════════════════════════════════════════════════
# CONTROLLED VOCABULARIES
# ════════════════════════════════════════════════════════════
VALID_CAPTIVITY = {
    "Zoo", "Wildlife Park", "Research Center", "Breeding Center",
    "Sanctuary", "Rehabilitation Center", "Other", "NEEDS_FULL_TEXT",
}
VALID_METHOD = {
    "16S", "Shotgun Metagenomics", "ITS", "Transcriptomics",
    "Other", "NEEDS_FULL_TEXT",
}
VALID_INTERVENTION = {
    "None", "Dietary", "Medication", "Fecal Transplant", "Other",
    "NEEDS_FULL_TEXT",
}
VALID_SAMPLE = {
    "Fecal", "Intestinal Content", "Mucosal", "Other",
    "NEEDS_FULL_TEXT",
}


# ════════════════════════════════════════════════════════════
# SYSTEM PROMPT  (v3 — two-stage with few-shot examples)
# ════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """You are a systematic review assistant for a study on gut microbiome \
research in captive animals. You screen papers and extract structured data with high \
accuracy. You will receive a paper's title and abstract ONLY (not the full text).

YOUR TASK:
1. Decide whether to INCLUDE, EXCLUDE, or flag as NEEDS_FULL_TEXT
2. If included, extract all fields possible from the abstract
3. For any field you cannot determine from the abstract, use the string "NEEDS_FULL_TEXT"

--- SCREENING DECISIONS ---

"include"  -- Paper clearly meets inclusion criteria based on abstract.
             Extract all data possible. Flag individual fields as NEEDS_FULL_TEXT
             when the abstract doesn't provide enough detail.

"exclude"  -- Paper clearly meets one or more exclusion criteria.
             Provide a one-sentence reason. Return rows as [].

"needs_full_text" -- You CANNOT determine inclusion/exclusion from the abstract alone.
             Common reasons: abstract is vague about whether animals are captive,
             unclear if the study is compositional, ambiguous species (could be
             domestic or wild), no abstract available.
             Return rows as []. The paper will be queued for human review.

--- EXCLUSION CRITERIA ---
Exclude if ANY of the following apply:
- Review article, meta-analysis, systematic review, or commentary (not primary research)
- Studies ONLY non-gut microbiomes (oral, skin, respiratory, vaginal) with no gut data
- Studies ONLY wild animals -- no captive animal data present
- Studies ONLY domestic animals (dogs, cats, cattle, pigs, sheep, goats, chickens, \
horses), laboratory mice, laboratory rats, or C. elegans
- Not a compositional microbiome study -- must measure relative abundance of multiple \
microbial taxa, not just detect/quantify a single strain or single species

IMPORTANT EDGE CASES -- DO NOT EXCLUDE:
- Metabolomics or metatranscriptomics alongside community composition -> INCLUDE
- Mix of domestic + non-domestic captive species -> INCLUDE (extract non-domestic only)
- Semi-wild or free-ranging animals compared to "wild" -> the semi-wild group is captive
- Aquaculture / farmed fish in non-domestic species -> INCLUDE, setting = "Breeding Center"
- Studies of zoo/sanctuary animals that also happen to include wild comparisons -> INCLUDE

WHEN IN DOUBT: Use "needs_full_text", never guess on exclusion.

--- FEW-SHOT EXAMPLES ---

EXAMPLE 1 -- EXCLUDE (review article):
Title: "The gut microbiome of captive wildlife: a global systematic review"
-> screening_decision: "exclude"
-> screening_reason: "Systematic review, not primary research"

EXAMPLE 2 -- EXCLUDE (only domestic animals):
Title: "Effects of probiotics on the fecal microbiota of dairy cattle"
-> screening_decision: "exclude"
-> screening_reason: "Studies only domestic cattle, no non-domestic captive species"

EXAMPLE 3 -- EXCLUDE (not compositional):
Title: "Detection of Salmonella enterica in captive reptiles using PCR"
-> screening_decision: "exclude"
-> screening_reason: "Detects a single pathogen, not compositional microbiome characterization"

EXAMPLE 4 -- EXCLUDE (only wild animals):
Title: "Gut bacterial diversity of wild migratory shorebirds across flyways"
-> screening_decision: "exclude"
-> screening_reason: "Studies only wild animals with no captive component"

EXAMPLE 5 -- EXCLUDE (non-gut microbiome):
Title: "Skin microbiome diversity in zoo-housed amphibians and its relationship to chytrid resistance"
-> screening_decision: "exclude"
-> screening_reason: "Studies skin microbiome only, no gut data"

EXAMPLE 6 -- INCLUDE (multi-species zoo study):
Title: "Variation on gut microbiota diversity of endangered red pandas living in captivity"
Abstract mentions: 22 captive red pandas across zoos in China, 16S rRNA, fecal samples
-> screening_decision: "include"
-> One row: Red panda, Ailurus fulgens, captive_n=22, Zoo, China Asia, 16S

EXAMPLE 7 -- INCLUDE (captive vs wild comparison):
Title: "Diet drives gut bacterial diversity of wild and semi-captive common cranes"
Abstract mentions: 6 semi-captive + 15 wild cranes, 16S, China
-> screening_decision: "include"
-> One row: Common Crane, Grus grus, captive_n=6, wild_n=15, mixed_captive_wild=true

EXAMPLE 8 -- NEEDS_FULL_TEXT:
Title: "Bacterial community analysis of an endangered primate species"
Abstract: vague, mentions "housed animals" but unclear if zoo/sanctuary/lab colony
-> screening_decision: "needs_full_text"
-> screening_reason: "Cannot determine captivity setting or if animals are domestic/lab colony from abstract"

--- ROW GENERATION RULES ---
A single paper may produce MULTIPLE rows:
- ONE ROW per animal species studied in captivity
- If the same species was sampled in DIFFERENT COUNTRIES -> one row per country
- If the same species was sampled at multiple sites in the SAME country -> ONE row
- Do NOT generate rows for species studied only in the wild
- Do NOT generate rows for purely domestic/laboratory species

--- CONTROLLED VOCABULARIES ---
Use ONLY these exact values. Spelling and capitalization must match.

captivity_setting (list -- select all that apply):
  "Zoo", "Wildlife Park", "Research Center", "Breeding Center",
  "Sanctuary", "Rehabilitation Center", "Other"
  - Use the paper's own description of the setting
  - If "semi-wild" is compared to "wild" -> use best-matching setting
  - If unclear from abstract -> ["NEEDS_FULL_TEXT"]

microbiome_method (list -- select all that apply):
  "16S", "Shotgun Metagenomics", "ITS", "Transcriptomics", "Other"
  - "16S" = any 16S rRNA amplicon approach (V3-V4, V4, etc.)
  - "Other" = 18S, culturomics, DGGE, T-RFLP, clone libraries, qPCR panels, etc.

interventions (list -- select all that apply):
  "None", "Dietary", "Medication", "Fecal Transplant", "Other"
  - Intervention = study TESTS THE EFFECT of a deliberate manipulation
  - NOT an intervention if animals were already on treatment before the study
  - Enrichment studies (environmental or dietary enrichment) -> "Other"
  - Translocation / relocation experiments -> "Other"
  - If unclear from abstract -> ["NEEDS_FULL_TEXT"]

sample_type (single value):
  "Fecal", "Intestinal Content", "Mucosal", "Other"
  - Fecal swabs = "Fecal"
  - Cloacal swabs (birds, reptiles) = "Fecal"
  - Whole-gut homogenized = "Other"

--- FIELD DEFINITIONS ---
publication_year       : integer
authors                : "Last, First; Last, First" -- all authors
title                  : full title, no HTML tags
journal                : journal name in UPPER CASE
doi                    : DOI without "https://doi.org/" prefix
citations              : null (filled separately)
animal_common_name     : common English name
animal_taxon_scientific: "Genus species" -- exactly two words
subspecies             : subspecies epithet if stated, else null
captive_n              : number of captive INDIVIDUALS (not samples).
                         Longitudinal studies = count unique individuals.
                         If unclear -> "NEEDS_FULL_TEXT"
wild_n                 : count ONLY if same species compared captive vs wild.
                         Different species wild comparison -> 0. No comparison -> 0.
captivity_setting      : list from vocabulary above
geographic_location    : "Country, Continent" where captive animals are housed.
                         NOT where researchers are based.
                         If unclear -> "NEEDS_FULL_TEXT"
mixed_captive_wild     : true only if same species compared captive vs wild
sample_type            : from vocabulary above
microbiome_method      : list from vocabulary above
interventions          : list from vocabulary above
longitudinal           : true ONLY if same individuals tracked over multiple timepoints.
                         Repeated cross-sections are NOT longitudinal.
healthy_vs_diseased    : true if study explicitly compares diseased vs non-diseased
notes                  : brief methodological notes or caveats
confidence_flags       : list of field names where you are uncertain or used NEEDS_FULL_TEXT

--- OUTPUT FORMAT ---
Respond with valid JSON ONLY. No preamble, no explanation, no markdown fences.

{
  "doi": "string or null",
  "screening_decision": "include",
  "screening_confidence": "high",
  "screening_reason": "one sentence",
  "rows": [
    {
      "publication_year": 2024,
      "authors": "Last, First; Last, First",
      "title": "string",
      "journal": "JOURNAL NAME",
      "doi": "10.xxxx/xxxxx",
      "citations": null,
      "animal_common_name": "Red panda",
      "animal_taxon_scientific": "Ailurus fulgens",
      "subspecies": null,
      "captive_n": 22,
      "wild_n": 0,
      "captivity_setting": ["Zoo"],
      "geographic_location": "China, Asia",
      "mixed_captive_wild": false,
      "sample_type": "Fecal",
      "microbiome_method": ["16S"],
      "interventions": ["None"],
      "longitudinal": false,
      "healthy_vs_diseased": false,
      "notes": null,
      "confidence_flags": []
    }
  ]
}

If screening_decision is "exclude" or "needs_full_text", return rows as [].
"""


# ════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ════════════════════════════════════════════════════════════

def format_authors(creators):
    """Convert Zotero creator list -> 'Last, First; Last, First'."""
    authors = [c for c in creators if c.get("creatorType") == "author"]
    parts = []
    for a in authors:
        last  = a.get("lastName", "").strip()
        first = a.get("firstName", "").strip()
        if last:
            parts.append(f"{last}, {first}" if first else last)
    return "; ".join(parts)


def build_user_message(item_data):
    """Construct the per-paper message sent to Claude."""
    title    = item_data.get("title", "").replace("<i>", "").replace("</i>", "")
    abstract = item_data.get("abstractNote", "").strip()
    authors  = format_authors(item_data.get("creators", []))
    year     = item_data.get("date", "")[:4]
    journal  = item_data.get("publicationTitle", "")
    doi      = item_data.get("DOI", "")

    if not abstract:
        abstract = (
            "[No abstract available. Screen based on title and metadata only. "
            "If you cannot confidently determine inclusion or exclusion, "
            "use screening_decision: \"needs_full_text\".]"
        )

    return (
        f"Please screen and extract data from this paper:\n\n"
        f"TITLE: {title}\n"
        f"AUTHORS: {authors}\n"
        f"YEAR: {year}\n"
        f"JOURNAL: {journal}\n"
        f"DOI: {doi}\n\n"
        f"ABSTRACT:\n{abstract}"
    )


# ────────────────────────────────────────────────────────────
# API CALL WITH RETRY
# ────────────────────────────────────────────────────────────

def call_claude(client, user_message, paper_key):
    """
    Send one paper to Claude and return parsed JSON.
    Retries up to MAX_RETRIES on transient failures.
    """
    last_error = None
    raw_text = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )

            raw_text = response.content[0].text.strip()

            # Strip accidental markdown fences
            if raw_text.startswith("```"):
                lines = raw_text.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                raw_text = "\n".join(lines)

            result = json.loads(raw_text)
            result["zotero_key"] = paper_key
            return result

        except json.JSONDecodeError as e:
            print(f"    warning: JSON parse error (attempt {attempt}): {e}")
            last_error = f"json_parse_error: {e}"
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_SEC ** attempt)

        except anthropic.RateLimitError:
            wait = RETRY_BASE_SEC ** attempt * 5
            print(f"    warning: Rate limited -- waiting {wait}s (attempt {attempt})")
            time.sleep(wait)
            last_error = "rate_limit"

        except anthropic.APIStatusError as e:
            print(f"    warning: API error {e.status_code} (attempt {attempt}): {e.message}")
            last_error = f"api_{e.status_code}: {e.message}"
            if e.status_code >= 500 and attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_SEC ** attempt)
            else:
                break

        except Exception as e:
            print(f"    warning: Unexpected error (attempt {attempt}): {e}")
            last_error = str(e)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BASE_SEC ** attempt)

    print(f"  FAILED after {MAX_RETRIES} attempts: {last_error}")
    return {
        "zotero_key": paper_key,
        "error": last_error,
        "raw_response": raw_text,
    }


# ────────────────────────────────────────────────────────────
# VALIDATION
# ────────────────────────────────────────────────────────────

def validate_row(row):
    """Check one row against controlled vocabularies. Returns warning list."""
    warnings = []

    for val in row.get("captivity_setting", []):
        if val not in VALID_CAPTIVITY:
            warnings.append(f"captivity_setting '{val}' not in vocabulary")

    for val in row.get("microbiome_method", []):
        if val not in VALID_METHOD:
            warnings.append(f"microbiome_method '{val}' not in vocabulary")

    for val in row.get("interventions", []):
        if val not in VALID_INTERVENTION:
            warnings.append(f"intervention '{val}' not in vocabulary")

    st = row.get("sample_type", "")
    if st and st not in VALID_SAMPLE:
        warnings.append(f"sample_type '{st}' not in vocabulary")

    taxon = row.get("animal_taxon_scientific", "")
    if taxon and taxon != "NEEDS_FULL_TEXT" and len(taxon.split()) != 2:
        warnings.append(f"taxon '{taxon}' not 'Genus species' format")

    return warnings


def validate_extraction(extraction):
    """Validate all rows. Mutates in-place to add warnings to confidence_flags."""
    if "error" in extraction or extraction.get("screening_decision") != "include":
        return

    for row in extraction.get("rows", []):
        warnings = validate_row(row)
        if warnings:
            existing = row.get("confidence_flags", [])
            row["confidence_flags"] = existing + [f"VALIDATION: {w}" for w in warnings]
            print(f"    validation: {'; '.join(warnings)}")


# ────────────────────────────────────────────────────────────
# CSV SCHEMA
# ────────────────────────────────────────────────────────────

CSV_COLUMNS = [
    "zotero_key",
    "screening_decision",
    "screening_confidence",
    "screening_reason",
    "publication_year",
    "authors",
    "title",
    "journal",
    "citations",
    "doi",
    "animal_common_name",
    "animal_taxon_scientific",
    "subspecies",
    "captive_n",
    "wild_n",
    "captivity_setting",
    "geographic_location",
    "mixed_captive_wild",
    "sample_type",
    "microbiome_method",
    "interventions",
    "longitudinal",
    "healthy_vs_diseased",
    "notes",
    "confidence_flags",
    "needs_full_text_fields",
]

REVIEW_QUEUE_COLUMNS = [
    "zotero_key",
    "doi",
    "pdf_url",
    "title",
    "authors",
    "review_type",
    "screening_reason",
    "needs_full_text_fields",
    "reviewer_assigned",
    "reviewer_decision",
    "reviewer_notes",
]


# ────────────────────────────────────────────────────────────
# FLATTEN + REVIEW QUEUE
# ────────────────────────────────────────────────────────────

def _find_nft_fields(row):
    """Return list of field names that contain NEEDS_FULL_TEXT."""
    nft = []
    for k, v in row.items():
        if v == "NEEDS_FULL_TEXT":
            nft.append(k)
        elif isinstance(v, list) and "NEEDS_FULL_TEXT" in v:
            nft.append(k)
    return nft


def flatten_to_rows(extraction):
    """Convert Claude's JSON into flat dicts for CSV output."""
    base = {
        "zotero_key":           extraction.get("zotero_key"),
        "doi":                  extraction.get("doi"),
        "screening_decision":   extraction.get("screening_decision"),
        "screening_confidence": extraction.get("screening_confidence"),
        "screening_reason":     extraction.get("screening_reason"),
    }

    rows = extraction.get("rows", [])
    if not rows:
        return [base]

    flat = []
    for row in rows:
        nft_fields = _find_nft_fields(row)

        fr = {**base}
        fr.update({
            "publication_year":        row.get("publication_year"),
            "authors":                 row.get("authors"),
            "title":                   row.get("title"),
            "journal":                 row.get("journal"),
            "citations":               row.get("citations"),
            "animal_common_name":      row.get("animal_common_name"),
            "animal_taxon_scientific":  row.get("animal_taxon_scientific"),
            "subspecies":              row.get("subspecies"),
            "captive_n":               row.get("captive_n"),
            "wild_n":                  row.get("wild_n"),
            "captivity_setting":       "; ".join(row.get("captivity_setting", [])),
            "geographic_location":     row.get("geographic_location"),
            "mixed_captive_wild":      row.get("mixed_captive_wild"),
            "sample_type":             row.get("sample_type"),
            "microbiome_method":       "; ".join(row.get("microbiome_method", [])),
            "interventions":           "; ".join(row.get("interventions", [])),
            "longitudinal":            row.get("longitudinal"),
            "healthy_vs_diseased":     row.get("healthy_vs_diseased"),
            "notes":                   row.get("notes"),
            "confidence_flags":        "; ".join(row.get("confidence_flags", [])),
            "needs_full_text_fields":  "; ".join(nft_fields),
        })
        flat.append(fr)

    return flat


def build_review_queue(all_extractions):
    """
    Build the review queue CSV for your undergrad team.

    Two categories of papers that need human attention:

      "screening"       — Claude couldn't decide include/exclude from abstract.
                          Reviewer needs the PDF to make a screening decision.

      "data_completion" — Claude included the paper but some fields need the
                          full text. Reviewer fills in the NEEDS_FULL_TEXT gaps.
    """
    queue = []

    for ext in all_extractions:
        if "error" in ext:
            continue

        doi     = ext.get("doi", "")
        zkey    = ext.get("zotero_key", "")
        rows    = ext.get("rows", [])
        title   = rows[0].get("title", "") if rows else ""
        authors = rows[0].get("authors", "") if rows else ""

        # Category 1: screening uncertain
        if ext.get("screening_decision") == "needs_full_text":
            queue.append({
                "zotero_key":            zkey,
                "doi":                   doi,
                "pdf_url":               f"https://doi.org/{doi}" if doi else "",
                "title":                 title or "[check Zotero]",
                "authors":               authors,
                "review_type":           "screening",
                "screening_reason":      ext.get("screening_reason", ""),
                "needs_full_text_fields": "",
                "reviewer_assigned":     "",
                "reviewer_decision":     "",
                "reviewer_notes":        "",
            })

        # Category 2: included but has data gaps
        elif ext.get("screening_decision") == "include":
            all_nft = set()
            for row in rows:
                all_nft.update(_find_nft_fields(row))

            if all_nft:
                queue.append({
                    "zotero_key":            zkey,
                    "doi":                   doi,
                    "pdf_url":               f"https://doi.org/{doi}" if doi else "",
                    "title":                 title,
                    "authors":               authors,
                    "review_type":           "data_completion",
                    "screening_reason":      "",
                    "needs_full_text_fields": "; ".join(sorted(all_nft)),
                    "reviewer_assigned":     "",
                    "reviewer_decision":     "",
                    "reviewer_notes":        "",
                })

    return queue


# ────────────────────────────────────────────────────────────
# CHECKPOINTING
# ────────────────────────────────────────────────────────────

def load_checkpoint(json_path):
    if not json_path.exists():
        return []
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_checkpoint(json_path, raw_extractions):
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(raw_extractions, f, indent=2, ensure_ascii=False)


def save_csv(csv_path, rows, columns):
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ════════════════════════════════════════════════════════════
# MAIN PIPELINE
# ════════════════════════════════════════════════════════════

def run_pipeline(collection_key, run_name, limit=None, resume=False):
    """
    Process a Zotero collection end-to-end.

    Stage 1: Claude screens each paper -> include / exclude / needs_full_text
    Stage 2: Generates review_queue.csv for papers needing human/PDF review
    """

    csv_path   = OUTPUT_DIR / f"{run_name}.csv"
    json_path  = OUTPUT_DIR / f"{run_name}_raw.json"
    queue_path = OUTPUT_DIR / f"{run_name}_review_queue.csv"

    # ── Initialize ────────────────────────────────────────
    zot    = zotero.Zotero(ZOTERO_LIBRARY_ID, LIBRARY_TYPE, ZOTERO_API_KEY)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # ── Fetch papers ──────────────────────────────────────
    print(f"Fetching papers from collection {collection_key}...")
    items = zot.everything(zot.collection_items(collection_key))
    articles = [i for i in items if i["data"].get("itemType") == "journalArticle"]

    if limit:
        articles = articles[:limit]

    print(f"Found {len(articles)} journal articles.\n")

    # ── Checkpoint ────────────────────────────────────────
    raw_extractions = []
    done_keys = set()

    if resume:
        raw_extractions = load_checkpoint(json_path)
        done_keys = {r.get("zotero_key") for r in raw_extractions if r.get("zotero_key")}
        print(f"Resuming -- {len(done_keys)} papers already processed.\n")

    # ══════════════════════════════════════════════════════
    # STAGE 1: ABSTRACT SCREEN + EXTRACT
    # ══════════════════════════════════════════════════════
    print("=" * 55)
    print("  STAGE 1: Abstract Screening + Extraction")
    print("=" * 55 + "\n")

    for i, item in enumerate(articles):
        data  = item["data"]
        key   = data["key"]
        title = data.get("title", "No title")[:80]

        if key in done_keys:
            continue

        print(f"[{i+1}/{len(articles)}] {title}")

        user_message = build_user_message(data)
        extraction   = call_claude(client, user_message, key)

        if "error" not in extraction:
            validate_extraction(extraction)

        raw_extractions.append(extraction)

        # Report
        if "error" in extraction:
            print(f"  -> ERROR: {extraction['error']}")
        else:
            decision = extraction.get("screening_decision", "?")
            n_rows   = len(extraction.get("rows", []))
            conf     = extraction.get("screening_confidence", "")
            print(f"  -> {decision.upper()} ({conf}) -- {n_rows} row(s)")

        save_checkpoint(json_path, raw_extractions)
        time.sleep(PAUSE_BETWEEN)

    # ── Build flat rows ───────────────────────────────────
    all_flat = []
    for ext in raw_extractions:
        if "error" in ext:
            all_flat.append({
                "zotero_key":         ext.get("zotero_key"),
                "screening_decision": "ERROR",
                "screening_reason":   ext.get("error"),
            })
        else:
            all_flat.extend(flatten_to_rows(ext))

    # ── Save CSVs ─────────────────────────────────────────
    save_csv(csv_path, all_flat, CSV_COLUMNS)

    included = [r for r in all_flat if r.get("screening_decision") == "include"]
    excluded = [r for r in all_flat if r.get("screening_decision") == "exclude"]
    needs_ft = [r for r in all_flat if r.get("screening_decision") == "needs_full_text"]
    errors   = [r for r in all_flat if r.get("screening_decision") == "ERROR"]

    if included:
        save_csv(OUTPUT_DIR / f"{run_name}_included.csv", included, CSV_COLUMNS)
    if excluded:
        save_csv(OUTPUT_DIR / f"{run_name}_excluded.csv", excluded, CSV_COLUMNS)
    if needs_ft:
        save_csv(OUTPUT_DIR / f"{run_name}_needs_fulltext.csv", needs_ft, CSV_COLUMNS)
    if errors:
        save_csv(OUTPUT_DIR / f"{run_name}_errors.csv", errors, CSV_COLUMNS)

    # ══════════════════════════════════════════════════════
    # STAGE 2: BUILD REVIEW QUEUE
    # ══════════════════════════════════════════════════════
    print("\n" + "=" * 55)
    print("  STAGE 2: Building Review Queue")
    print("=" * 55 + "\n")

    review_queue = build_review_queue(raw_extractions)
    save_csv(queue_path, review_queue, REVIEW_QUEUE_COLUMNS)

    n_screening  = sum(1 for r in review_queue if r["review_type"] == "screening")
    n_completion = sum(1 for r in review_queue if r["review_type"] == "data_completion")

    # ── Summary ───────────────────────────────────────────
    print(f"{'='*55}")
    print(f"  PIPELINE COMPLETE -- {run_name}")
    print(f"{'='*55}")
    print(f"  Total processed:     {len(raw_extractions)}")
    print(f"  |-- Included:        {len(included)} rows")
    print(f"  |-- Excluded:        {len(excluded)} rows")
    print(f"  |-- Needs full text: {len(needs_ft)} rows")
    print(f"  |-- Errors:          {len(errors)} rows")
    print(f"")
    print(f"  Review queue:        {len(review_queue)} papers")
    print(f"  |-- Screening:       {n_screening}  (need PDF to decide include/exclude)")
    print(f"  |-- Data completion: {n_completion}  (included, but missing fields)")
    print(f"{'='*55}")
    print(f"  Output files:")
    print(f"    {csv_path}")
    if included:
        print(f"    {OUTPUT_DIR / f'{run_name}_included.csv'}")
    if excluded:
        print(f"    {OUTPUT_DIR / f'{run_name}_excluded.csv'}")
    if needs_ft:
        print(f"    {OUTPUT_DIR / f'{run_name}_needs_fulltext.csv'}")
    if errors:
        print(f"    {OUTPUT_DIR / f'{run_name}_errors.csv'}")
    print(f"    {queue_path}  <-- hand this to your team")
    print(f"    {json_path}")
    print(f"{'='*55}\n")

    return all_flat, raw_extractions, review_queue


# ════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Captive Animal Microbiome -- Extraction Pipeline (two-stage)"
    )
    parser.add_argument(
        "--collection",
        choices=list(COLLECTIONS.keys()),
        default="pilot",
        help="Which Zotero collection to process (default: pilot)",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Only process first N papers",
    )
    parser.add_argument(
        "--resume", action="store_true",
        help="Resume from checkpoint",
    )
    args = parser.parse_args()

    # Validate credentials
    missing = []
    if not ZOTERO_API_KEY:    missing.append("ZOTERO_API_KEY")
    if not ZOTERO_LIBRARY_ID: missing.append("ZOTERO_LIBRARY_ID")
    if not ANTHROPIC_API_KEY: missing.append("ANTHROPIC_API_KEY")
    if missing:
        print(f"ERROR: Missing environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your keys.")
        sys.exit(1)

    collection_key = COLLECTIONS[args.collection]
    timestamp      = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name       = f"{args.collection}_{timestamp}"

    if args.resume:
        existing = sorted(OUTPUT_DIR.glob(f"{args.collection}_*_raw.json"))
        if existing:
            run_name = existing[-1].stem.replace("_raw", "")
            print(f"Resuming run: {run_name}")
        else:
            print("No previous run found -- starting fresh.")
            args.resume = False

    run_pipeline(
        collection_key=collection_key,
        run_name=run_name,
        limit=args.limit,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
