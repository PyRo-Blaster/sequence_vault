# P6 Intelligent Extraction Implementation Plan

> **For agentic workers:** Use anthropic-skills:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Extract names and sequences from DOCX, CSV, XLSX and text PDF with evidence, use an approved model only where rules leave the mapping open, and measure accuracy on a frozen set.

**Architecture:** New parsers emit DocumentIR in the sandbox; rule extraction handles paragraph joins and tables; `application/model_assist.py` asks the model to link numbered candidates (ADR 0007) through `adapters/ai/gateway.py`; `tools/evaluation/evaluate.py` scores a gold manifest with the production code path.

## Tasks

- [x] **Task 1:** DOCX reader over OOXML with hardened XML parsing: paragraphs, tables, tracked-changes views, text boxes, hidden text, headers, footers, comments, images, embedded objects and merged cells reported as coverage warnings.
- [x] **Task 2:** CSV and XLSX readers: cell locations, formulas never evaluated and flagged, hidden sheets, rows and columns reported. Text PDF reader with page coordinates, scanned-page and multi-column warnings, 100-page limit.
- [x] **Task 3:** Rule extraction for joined paragraphs (with `cross_block_join` → QC08), heading labels, table headers, chain columns (T04), pending names in tables; filename conflicts only for identifier-like stems.
- [x] **Task 4:** Migration 0002 stores the chosen tracked-changes view; reprocess accepts it (T07); the review page offers the other view.
- [x] **Task 5:** Model assistance with candidate ids, one repair, refusal handling, summaries for long blocks (T14, T19); Anthropic adapter with structured outputs, effort and refusal fallback; AI stays disabled until approved.
- [x] **Task 6:** Evaluation tool, synthetic gold set across all formats, and tests that the tool fails on wrong names, missed records and unblocked cases.

## Not yet verified

Live model calls (no approved endpoint here) and the 200-file departmental frozen set, which the data owner supplies.
