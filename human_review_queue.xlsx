#!/usr/bin/env python3
"""
ABSTRACT ENRICHMENT PIPELINE
=============================
Fetches missing abstracts from free APIs to reduce NEEDS_FULL_TEXT flags.

APIs used (in priority order):
  1. CrossRef (free, no key needed, has ~90% of DOIs)
  2. Semantic Scholar (free, no key needed, good abstract coverage)
  3. OpenAlex (free, no key needed, new comprehensive source)

Usage:
  python enrich_abstracts.py                        # dry run (report only)
  python enrich_abstracts.py --apply                # fetch and update Zotero
  python enrich_abstracts.py --apply --limit 50     # test with 50 papers
  python enrich_abstracts.py --export enriched.json # save results to file

Requires: requests, pyzotero (optional, for Zotero update)
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

# ── CONFIG ──
JSON_PATH = Path("todo_20260227_112439_raw.json")  # agent results
ENRICHED_OUT = Path("enriched_abstracts.json")
PAUSE_BETWEEN = 0.5  # seconds between API calls (be polite)

# CrossRef config
CROSSREF_BASE = "https://api.crossref.org/works/"
CROSSREF_HEADERS = {
    "User-Agent": "CaptiveMicrobiomeSR/1.0 (mailto:your_email@university.edu)"
}

# Semantic Scholar config
S2_BASE = "https://api.semanticscholar.org/graph/v1/paper/DOI:"
S2_FIELDS = "title,abstract,externalIds"

# OpenAlex config
OPENALEX_BASE = "https://api.openalex.org/works/doi:"
OPENALEX_HEADERS = {
    "User-Agent": "CaptiveMicrobiomeSR/1.0 (mailto:your_email@university.edu)"
}


def fetch_crossref(doi):
    """Fetch abstract from CrossRef. Returns abstract string or None."""
    try:
        url = f"{CROSSREF_BASE}{doi}"
        r = requests.get(url, headers=CROSSREF_HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json().get("message", {})
            abstract = data.get("abstract", "")
            if abstract:
                # CrossRef abstracts sometimes have JATS XML tags
                import re
                abstract = re.sub(r'<[^>]+>', '', abstract).strip()
                if len(abstract) > 50:
                    return abstract
        return None
    except Exception:
        return None


def fetch_semantic_scholar(doi):
    """Fetch abstract from Semantic Scholar. Returns abstract string or None."""
    try:
        url = f"{S2_BASE}{doi}?fields={S2_FIELDS}"
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            abstract = data.get("abstract", "")
            if abstract and len(abstract) > 50:
                return abstract
        return None
    except Exception:
        return None


def fetch_openalex(doi):
    """Fetch abstract from OpenAlex. Returns abstract string or None."""
    try:
        url = f"{OPENALEX_BASE}{doi}"
        r = requests.get(url, headers=OPENALEX_HEADERS, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # OpenAlex stores inverted index; reconstruct
            inv_index = data.get("abstract_inverted_index")
            if inv_index:
                # Reconstruct from inverted index
                words = {}
                for word, positions in inv_index.items():
                    for pos in positions:
                        words[pos] = word
                abstract = " ".join(words[i] for i in sorted(words.keys()))
                if len(abstract) > 50:
                    return abstract
        return None
    except Exception:
        return None


def normalize_doi(doi):
    if not doi:
        return ""
    doi = str(doi).strip()
    doi = doi.replace("https://doi.org/", "").replace("http://doi.org/", "")
    return doi


def identify_papers_needing_abstracts(json_path):
    """Find papers where agent flagged needs_full_text or errored, grouped by DOI."""
    with open(json_path) as f:
        data = json.load(f)

    needs_abstract = []
    has_doi_no_abstract = 0
    no_doi = 0

    for rec in data:
        decision = rec.get("screening_decision", "")
        is_error = "error" in rec

        # Target: NFT papers and errors
        if decision == "needs_full_text" or is_error:
            doi = normalize_doi(rec.get("doi", ""))
            if doi:
                needs_abstract.append({
                    "zotero_key": rec.get("zotero_key", ""),
                    "doi": doi,
                    "decision": decision if not is_error else "error",
                    "reason": rec.get("screening_reason", rec.get("error", "")),
                })
                has_doi_no_abstract += 1
            else:
                no_doi += 1

    return needs_abstract, no_doi


def enrich(papers, limit=None):
    """Fetch abstracts from APIs. Returns list of enriched records."""
    if limit:
        papers = papers[:limit]

    results = []
    stats = {"crossref": 0, "s2": 0, "openalex": 0, "failed": 0}

    for i, paper in enumerate(papers):
        doi = paper["doi"]
        print(f"  [{i+1}/{len(papers)}] {doi[:50]}...", end=" ", flush=True)

        abstract = None
        source = None

        # Try CrossRef first
        abstract = fetch_crossref(doi)
        if abstract:
            source = "crossref"
            stats["crossref"] += 1
        else:
            time.sleep(PAUSE_BETWEEN)
            # Try Semantic Scholar
            abstract = fetch_semantic_scholar(doi)
            if abstract:
                source = "semantic_scholar"
                stats["s2"] += 1
            else:
                time.sleep(PAUSE_BETWEEN)
                # Try OpenAlex
                abstract = fetch_openalex(doi)
                if abstract:
                    source = "openalex"
                    stats["openalex"] += 1
                else:
                    stats["failed"] += 1

        if abstract:
            print(f"✓ ({source}, {len(abstract)} chars)")
        else:
            print("✗ (no abstract found)")

        results.append({
            **paper,
            "abstract": abstract,
            "abstract_source": source,
        })

        time.sleep(PAUSE_BETWEEN)

    return results, stats


def main():
    parser = argparse.ArgumentParser(description="Enrich missing abstracts via APIs")
    parser.add_argument("--apply", action="store_true", help="Actually fetch abstracts (default: dry run)")
    parser.add_argument("--limit", type=int, default=None, help="Limit to N papers")
    parser.add_argument("--export", type=str, default=None, help="Export enriched results to JSON")
    parser.add_argument("--json", type=str, default=str(JSON_PATH), help="Path to agent results JSON")
    args = parser.parse_args()

    json_path = Path(args.json)
    if not json_path.exists():
        print(f"ERROR: {json_path} not found")
        sys.exit(1)

    print("Identifying papers needing abstracts...")
    papers, no_doi_count = identify_papers_needing_abstracts(json_path)

    print(f"\nPapers needing abstracts: {len(papers)} (with DOI)")
    print(f"Papers without DOI (cannot enrich): {no_doi_count}")

    if not args.apply:
        print("\n--- DRY RUN ---")
        print(f"Would attempt to fetch abstracts for {len(papers)} papers.")
        print(f"Estimated time: ~{len(papers) * 1.5 / 60:.0f} minutes")
        print(f"Use --apply to actually fetch. Use --limit N to test with fewer.")
        return

    print(f"\nFetching abstracts (limit={args.limit or 'all'})...")
    results, stats = enrich(papers, limit=args.limit)

    # Summary
    total = sum(stats.values())
    found = stats["crossref"] + stats["s2"] + stats["openalex"]
    print(f"\n{'='*50}")
    print(f"  ENRICHMENT COMPLETE")
    print(f"{'='*50}")
    print(f"  Total attempted:  {total}")
    print(f"  Abstracts found:  {found} ({found/total*100:.0f}%)")
    print(f"    CrossRef:       {stats['crossref']}")
    print(f"    Semantic Scholar: {stats['s2']}")
    print(f"    OpenAlex:       {stats['openalex']}")
    print(f"  Not found:        {stats['failed']}")
    print(f"{'='*50}")

    # Export
    export_path = Path(args.export) if args.export else ENRICHED_OUT
    with open(export_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {export_path}")

    # Also output a summary for the rerun pipeline
    enriched_for_rerun = [r for r in results if r["abstract"]]
    still_missing = [r for r in results if not r["abstract"]]
    print(f"\nReady for agent rerun: {len(enriched_for_rerun)} papers")
    print(f"Still need human/PDF review: {len(still_missing)} papers")


if __name__ == "__main__":
    main()
