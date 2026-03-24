# Captive Animal Microbiome — Systematic Review Pipeline

An AI-assisted pipeline for large-scale systematic literature screening and data extraction, built for a systematic review of gut microbiome research in captive animals.

Sensitive information was removed and will be added upon publishing

## Background

Systematic reviews require screening hundreds to thousands of papers for inclusion criteria and extracting structured data from each — an enormous manual burden. This pipeline uses Claude to automate the bulk of that work, reducing a months-long process to days at a cost of under $10.

The corpus: **1,355 papers** from Web of Science (September 2025) on captive animal gut microbiomes.

## Pipeline Overview

```
1,355 papers
     │
     ▼
Phase 1: AI Screening (Sonnet)
     ├── 358 excluded (high confidence) ──► ExcludedPapers sheet
     ├── 16 included with partial extraction ──► IncludedPapers sheet
     └── 625 flagged for review ──► AgentReviewQueue sheet
     │
     ▼
Phase 2: Abstract Enrichment (free APIs)
     └── Fetch missing abstracts via CrossRef, Semantic Scholar, OpenAlex
     │
     ▼
Phase 3: Rerun Pipeline (Sonnet, Batch API)
     └── Re-screen papers that previously lacked abstracts
     │
     ▼
Phase 4: Full-Text Extraction (Opus)
     └── Fill remaining fields in confirmed-include papers
     │
     ▼
Phase 5: Human Review Queue
     └── Irreducible cases requiring manual lookup or PDF access
```

## Scripts

| Script | Phase | Description |
|--------|-------|-------------|
| `extract_pipeline.py` | 1 | Initial AI screening of full corpus |
| `integrate_agent_results.py` | 1 | Merges AI results into master Excel workbook |
| `enrich_abstracts.py` | 2 | Fetches missing abstracts from free APIs |
| `rerun_pipeline.py` | 3 | Re-screens papers with enriched abstracts |
| `stage2_opus_extraction.py` | 4 | Full-text field extraction using Claude Opus |

## Usage

```bash
pip install anthropic openpyxl requests python-dotenv

# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Phase 1: Screen the corpus
python extract_pipeline.py

# Phase 1: Integrate results into Excel
python integrate_agent_results.py

# Phase 2: Fetch missing abstracts (free, no API key needed)
python enrich_abstracts.py --apply

# Phase 3: Rerun with enriched abstracts (use batch for 50% cost savings)
python rerun_pipeline.py --batch

# Phase 4: Opus extraction for confirmed includes
python stage2_opus_extraction.py --batch
```

## Multi-Model Design

The pipeline uses different Claude models for different tasks based on cost/capability tradeoffs:

- **Sonnet** — Initial screening (include/exclude) and abstract-level extraction. Fast and cheap.
- **Opus** — Stage 2 full-text extraction for confirmed includes. More expensive but higher accuracy for nuanced fields.
- **Batch API** — Used throughout for 50% cost reduction on large runs.

## Data Extraction Schema

Each included paper is extracted into structured fields:

- `animal_common_name`, `animal_taxon_scientific`, `subspecies`
- `captive_n`, `wild_n`, `mixed_captive_wild`
- `captivity_setting` — Zoo, Wildlife Park, Research Center, Sanctuary, etc.
- `geographic_location` — where animals are housed, not researcher affiliation
- `sample_type` — Fecal, Intestinal Content, Mucosal, Other
- `microbiome_method` — 16S, Shotgun Metagenomics, ITS, etc.
- `interventions` — None, Dietary, Medication, Fecal Transplant, Other
- `longitudinal`, `healthy_vs_diseased`

Controlled vocabularies are enforced in prompts to ensure consistency across AI and human extractors.

## Few-Shot Learning

Stage 2 Opus extraction uses few-shot examples drawn from human-extracted ground truth in the master workbook. Examples are selected for taxonomic diversity (mammals, birds, reptiles, fish) to maximize coverage of edge cases.

## Cost

| Phase | Model | Papers | Cost |
|-------|-------|--------|------|
| 1. Screening | Sonnet (Batch) | ~1,355 | ~$2–4 |
| 2. Enrichment | Free APIs | ~552 | $0 |
| 3. Rerun | Sonnet (Batch) | ~700 | $1–3 |
| 4. Extraction | Opus (Batch) | ~100–200 | $3–7 |
| **Total** | | | **~$6–14** |

## Output Files

- `SysReviewPapersCaptiveMicrobiome_INTEGRATED.xlsx` — Master workbook (source of truth for the manuscript)
  - `IncludedPapers` — Human + AI extracted rows (AI rows highlighted green, uncertain fields yellow)
  - `ExcludedPapers` — All excluded papers with reasons
  - `AgentReviewQueue` — Papers requiring human review, sorted by priority
  - `PipelineSummary` — Project statistics
- `human_review_queue.xlsx` — Standalone queue for the review team
- `enriched_abstracts.json` — Cached abstracts from API enrichment

## Notes

- The Excel workbook is the source of truth — never edit AI JSON files directly
- Agent initials: `AI-high` (confident exclusion), `AI-partial` (partial extraction)
- Zero conflicts found between AI exclusions and human inclusions in validation
- ~230 papers not in agent JSON may be non-article items (editorials, corrections) filtered by Zotero
