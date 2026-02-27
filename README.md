# Captive Animal Microbiome — Extraction Pipeline

Automated screening and data extraction for a systematic review of gut microbiome studies in captive animals. Uses the Anthropic Claude API to process papers stored in Zotero, outputting structured CSV files that match the project's Google Sheet schema.

## Two-Stage Workflow

```
┌──────────────────────────────────────────────────────────────┐
│  STAGE 1: Abstract Screen + Extract  (automated — Claude)    │
│                                                              │
│  For each paper in Zotero:                                   │
│    • Claude reads title + abstract                           │
│    • Decision: INCLUDE / EXCLUDE / NEEDS_FULL_TEXT           │
│    • Included papers: extract all fields possible             │
│    • Fields not in abstract: flagged as NEEDS_FULL_TEXT       │
│                                                              │
│  Outputs:                                                    │
│    _included.csv      ← ready for Google Sheets              │
│    _excluded.csv      ← with screening reasons               │
│    _needs_fulltext.csv ← couldn't screen from abstract       │
│    _review_queue.csv  ← hand this to your team               │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 2: Human / Full-Text Review  (your undergrad team)    │
│                                                              │
│  review_queue.csv has two types of entries:                   │
│                                                              │
│  "screening"       → Claude couldn't decide include/exclude  │
│                      Reviewer gets the PDF, makes the call   │
│                                                              │
│  "data_completion" → Paper is included but has gaps           │
│                      Reviewer fills in NEEDS_FULL_TEXT fields │
│                                                              │
│  Each row has a DOI link for PDF retrieval.                   │
│  Blank columns for: reviewer_assigned, reviewer_decision,    │
│  reviewer_notes                                              │
└──────────────────────────────────────────────────────────────┘
```

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env
# Edit .env with your actual API keys (regenerate if old ones were exposed)

# 3. Set your excluded collection key (already set to C9G9MIC9)
```

## Recommended Run Order

```bash
# 1. Calibration — verify Claude excludes known-excluded papers
python extract_pipeline.py --collection excluded

# 2. Pilot — validate against your 10 manually-extracted papers
python extract_pipeline.py --collection pilot

# 3. Full run — process the 1,122 unscreened papers
python extract_pipeline.py --collection todo

# 4. If interrupted, resume where you left off
python extract_pipeline.py --collection todo --resume
```

## Output Files

Each run produces files in `outputs/`:

| File | Description |
|------|-------------|
| `{run}.csv` | All rows combined |
| `{run}_included.csv` | Included papers — import to Google Sheets |
| `{run}_excluded.csv` | Excluded papers with screening reasons |
| `{run}_needs_fulltext.csv` | Papers Claude couldn't screen from abstract |
| `{run}_errors.csv` | Papers that failed API processing |
| `{run}_review_queue.csv` | **Give this to your team** — lists every paper needing human attention |
| `{run}_raw.json` | Raw Claude JSON (for debugging / reproducibility) |

## Collections

| Key | Zotero ID | Purpose |
|-----|-----------|---------|
| `pilot` | P2W5GAWL | 10 manually-extracted papers — validation ground truth |
| `included` | ZQS4ZZVG | 165 already-included papers |
| `excluded` | C9G9MIC9 | Known-excluded papers — calibration |
| `todo` | SALMNXDQ | 1,122 unprocessed papers |

## Note on PDFs

Zotero storage limits prevent the pipeline from accessing PDFs directly. The pipeline works from title + abstract only, which is why it uses the three-way screening decision (include / exclude / needs_full_text) instead of forcing a binary choice. Papers requiring full text are routed to the review queue with DOI links for your team to retrieve via institutional access.

## For the Methods Section

- Model: `claude-sonnet-4-6`
- The system prompt, extraction schema, and controlled vocabularies are defined in `extract_pipeline.py`
- Pin the model version for reproducibility
