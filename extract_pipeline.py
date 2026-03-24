# Captive Animal Microbiome — Pipeline Action Plan

**Generated:** 2026-03-06
**Status:** Phase 1 complete (agent results integrated into Excel)

---

## Current State After Integration

| Category | Count | Notes |
|----------|-------|-------|
| **Total corpus** | 1,355 papers | Web of Science, Sept 2025 |
| **Human included** | 245 papers (525 rows) | Ground truth in Excel |
| **Human excluded** | 137 papers | Ground truth in Excel |
| **AI excluded (new)** | 358 papers | High confidence, now in Excel (green rows) |
| **AI included (new)** | 19 rows across 16 papers | Partial extraction, in Excel (green + yellow) |
| **Review queue** | 625 papers | Errors + needs_full_text |
| **Estimated unprocessed** | ~230 papers | Not in agent JSON or Excel |

---

## Phase 1: Integration ✅ COMPLETE

**Script:** `integrate_agent_results.py`

**What it did:**
- Added 358 AI-excluded papers to ExcludedPapers sheet (green highlight, initials = "AI-high")
- Added 19 AI-extracted rows to IncludedPapers sheet (green highlight, NEEDS_FULL_TEXT fields in yellow)
- Created AgentReviewQueue sheet with 625 prioritized papers
- Created PipelineSummary sheet with project statistics

**Output files:**
- `SysReviewPapersCaptiveMicrobiome_INTEGRATED.xlsx` — updated master workbook
- `human_review_queue.xlsx` — standalone queue for the team

**Required human action:**
- Spot-check ~20 random AI exclusions (green rows) to validate agent accuracy (~10 min)
- If any false exclusions found, move to IncludedPapers and flag for extraction

---

## Phase 2: Abstract Enrichment ⏳ NEXT

**Script:** `enrich_abstracts.py`

**Why this matters:** 559 of 565 needs_full_text decisions happened because the agent only saw a title (no abstract). If we can fetch abstracts from free APIs, most of these will resolve automatically on rerun.

**What it does:**
- Queries CrossRef, Semantic Scholar, and OpenAlex for each DOI
- Expected hit rate: ~70-85% of DOIs will return abstracts
- Estimated runtime: ~14 minutes for all 552 papers with DOIs
- 163 papers have no DOI and cannot be enriched this way

**Commands:**
```bash
# Dry run (just count)
python enrich_abstracts.py --json /path/to/todo_20260227_112439_raw.json

# Fetch abstracts (test with 20 first)
python enrich_abstracts.py --json /path/to/todo_raw.json --apply --limit 20

# Full run
python enrich_abstracts.py --json /path/to/todo_raw.json --apply

# Results saved to enriched_abstracts.json
```

**Cost:** $0 (all APIs are free, no API key needed)

---

## Phase 3: Rerun Pipeline ⏳ AFTER ENRICHMENT

**Script:** `rerun_pipeline.py`

**What it does:**
- Reruns 150 errored papers (API credits ran out mid-run)
- Reruns NFT papers that now have enriched abstracts
- Uses same system prompt and Sonnet model as original run
- Supports Batch API mode (50% cost savings)

**Commands:**
```bash
# Dry run (see what would be rerun)
python rerun_pipeline.py --dry-run

# Errors only (150 papers, ~$0.50)
python rerun_pipeline.py --errors-only

# Full rerun with enriched abstracts (recommended: use batch)
python rerun_pipeline.py --batch

# Submit batch file via Python:
# import anthropic
# client = anthropic.Anthropic()
# batch = client.messages.batches.create(requests=[...])
```

**Estimated cost:** $1-3 (Sonnet, Batch API)

**After rerun:** Run `integrate_agent_results.py` again with the new JSON to merge results.

---

## Phase 4: Stage 2 Opus Extraction ⏳ AFTER RERUNS

**Script:** `stage2_opus_extraction.py`

**What it does:**
- Takes papers confirmed as INCLUDE but with missing fields
- Sends them to Claude Opus with enriched abstracts + few-shot examples from human extractions
- Few-shot examples auto-selected for taxonomic diversity (bat, mandrill, penguin, iguana, fish)
- Fills in captive_n, geographic_location, captivity_setting, etc.

**Commands:**
```bash
# See what needs extraction
python stage2_opus_extraction.py --dry-run

# Generate batch file (recommended)
python stage2_opus_extraction.py --batch

# After batch completes, integrate results into Excel
```

**Estimated cost:** $3-7 (Opus, Batch API)

---

## Phase 5: Human Review Queue ⏳ FINAL

After all automated steps, the irreducible human review queue will consist of:

1. **Papers with no DOI and no abstract** (~163): Must be looked up manually in Zotero or publisher sites
2. **Papers where agent was unsure even WITH abstract** (~6): Genuinely ambiguous cases
3. **NEEDS_FULL_TEXT fields that Opus couldn't resolve** (~varies): Require PDF access
4. **~230 unprocessed papers** not in the agent JSON: Need initial screening

**Recommended team workflow:**
- Sort review queue by Priority column
- Priority 1 (errors) will be resolved by Phase 3 rerun
- Priority 2 (medium confidence NFT) should be screened first — higher include probability
- Priority 3 (low confidence NFT, usually title-only) — batch assign to team

---

## File Inventory

| File | Purpose |
|------|---------|
| `integrate_agent_results.py` | Merges AI results into Excel (Phase 1) |
| `enrich_abstracts.py` | Fetches missing abstracts from APIs (Phase 2) |
| `rerun_pipeline.py` | Reruns errors + enriched papers (Phase 3) |
| `stage2_opus_extraction.py` | Opus full-text extraction (Phase 4) |
| `SysReviewPapersCaptiveMicrobiome_INTEGRATED.xlsx` | Updated master workbook |
| `human_review_queue.xlsx` | Standalone queue for the team |

---

## Cost Summary

| Phase | Model | Papers | Estimated Cost |
|-------|-------|--------|---------------|
| 2. Enrichment | Free APIs | 552 | $0 |
| 3. Rerun (Sonnet, batch) | Sonnet 4.6 | ~700 | $1-3 |
| 4. Stage 2 (Opus, batch) | Opus 4.6 | ~100-200 | $3-7 |
| **Total** | | | **$4-10** |

---

## Important Notes

- The Excel workbook is the source of truth for the manuscript
- Agent rows are highlighted in green; NEEDS_FULL_TEXT fields in yellow
- Agent initials are "AI-high", "AI-partial", etc. to distinguish from human work
- Zero conflicts found between agent exclusions and human inclusions (validated)
- The ~230 unprocessed papers may include non-journal-article items filtered out by the pipeline
- Your `.env` file needs valid ANTHROPIC_API_KEY with sufficient credits before running Phases 3-4
