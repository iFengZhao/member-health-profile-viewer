# Design decisions and open questions

Status: health-status-first read-only viewer for the optional Streamlit
extension (post-GATE-002 wiring under `DEC-007`, `DEC-008`, and `DEC-009`).
Written in English; all statements here are planning/design notes, not
empirical results.

## Design decisions

1. **Health-status view is the primary surface, concise first.** The main
   area opens on an anchored representative member chosen deterministically
   from the sample: both claim and prescription evidence, at least two
   documented conditions, and the most recognizable condition names
   (common diseases preferred; vague care-context categories such as
   "Factors influencing health care" are avoided). The inference review
   signal is a tiebreaker, not a requirement, so the default view reads as a
   concrete health status rather than a burden-signal demo. The app is never
   empty on load. Directly under the member id, a one-line **Concise health
   summary (observed)** renders the recorded conditions as short lines
   (`Recently recorded: …`, `Historically recorded: …`); source coverage
   follows as a small gray caption so it stays subtle, then the four compact
   status cards.
   All other health information follows as layer two (expanders); the verbose
   "Outpatient claims record N recorded items" block was removed from the main
   area and its definition text plus recency definitions moved to the Notes
   section at the bottom of the member view.
2. **`member_profiles.csv` is the single source of truth for profile content.**
   The full member table (291,611 rows, one per member, `member_id` unique,
   verified by read) carries the observed health summary, claim-usage and
   recency fields, medication picture, the eight member-level aggregates, the
   coverage label, and the evidence-quality note — the field set described in
   the brief's Section 1. The prototype's 3-row `profile_examples.csv` is no
   longer used.
3. **Inference is left-joined, not re-created.** The 49,610-member application
   output provides `inferred_condition_count`, `top_inferred_labels`, and
   `review_signal`; `member_profiles.csv` only persists the `Not assessed`
   placeholder. The join is one-to-one on `member_id` (unique on both sides,
   verified). Members without inference render `Not assessed` (not evaluated),
   never a false negative.
4. **Sidebar is a control panel, not a text wall.** Long explanation text was
   moved into one "Language and evidence rules" expander. The sidebar now
   holds `Search members`, `Select a member to inspect` (over the sample), and
   the preset buttons, whose labels are left-aligned via a small static CSS
   block (Streamlit centers button labels by default); the main area is
   reserved for member content.
5. **The app UI carries no "optional"/"outside core" labeling.** Per user
   direction, the app presents itself as a viewer without extension-status
   disclaimers in the UI. The study contract (study.md) still documents the
   interface as an optional extension; that governance text lives in the
   artifacts, not in the app.
6. **Default picker uses a seeded 1,000-member sample; presets search the full
   table.** The full table is 177 MB, so day-to-day member selection runs over
   a fixed, seeded sample (500 with inference, 500 without). Preset quick
   filters run over the full 291,611-member table so rare unusual-care
   patterns (for example stale prescriptions, 943 members) stay reachable.
   Preset matches are capped at the top 200 by the preset's key field for the
   picker and table; the sidebar shows the active preset and a `Clear preset`
   button to return to the default view.
7. **Presets are grounded in the study contract.** High inferred burden
   (DEC-008 trigger), high claim volume (study.md 10+ flag example),
   polypharmacy (study.md class-count indicator), stale prescriptions
   (DEC-009 p99 tail, 842 days), many-NDC-narrow-categories (DEC-009
   single-therapy context note, not an anomaly), and unmapped diagnosis codes
   (documentation-mismatch signal). Thresholds are demonstration defaults that
   stay adjustable without changing the underlying evidence.
8. **Vocabulary longest-match label parsing.** `top_inferred_labels` joins
   full label names with "; ", and some CCS Level 2 names contain "; "
   themselves. The app parses against the persisted label vocabulary, longest
   match first; verified over the full cohort (every member parses to exactly
   five labels).
9. **Conservative language is taken verbatim from the artifacts.** Recency
   labels, evidence provenance, and the prescription-inferred boundary are
   rendered as persisted. The app never uses active / resolved / persistent
   disease wording and never converts an absent field into a negative clinical
   claim.
10. **LLM summarization was considered and deliberately not adopted.** Faithful
   deterministic rendering of saved outputs; no hallucination or wording-drift
   risk, no API/network/per-page cost. If an AI reading aid is ever wanted, it
   should be default-off and clearly labeled as not part of the evidence
   record.
11. **Deployment data is packaged, not recomputed.** The single heavy input
   (`member_profiles.csv`, 169 MB) exceeds GitHub's 100 MB limit, so
   `build_deploy_data.py` writes lossless zstd-parquet copies of every input
   the app loads into `review_interface/data/` (17 MB total, measured
   2026-08-03; `member_profiles.parquet` 16.3 MB). Only integer dtypes are
   downcast; floats stay float64 so validation scores keep full precision.
   The app reads the copies when present and falls back to the `outputs/`
   CSVs, so the deployed bundle is a pure packaging artifact of the persisted
   outputs, not a new analysis.

## What is implemented in this version

- Anchored representative member on load; concise health status (four cards)
  as layer one with a one-line observed health summary directly under the
  member id; detailed health information (full date-ordered condition list,
  claims usage, medication detail with the eight aggregates, inference
  validation context, evidence quality) as layer two; claim-evidence and
  recency definitions in the Notes section at the bottom.
- Sidebar control panel: member search + picker over the 1,000-member sample;
  six preset quick filters over the full table; clear-preset action; one
  "Language and evidence rules" expander.
- Review worklist tab: filters (review signal, inferred-count tiers, top-label
  text, member ID, source coverage) and sorting over the sample.
- Reference tables tab: label decisions, validation thresholds, label
  comparison, retained labels, medication hierarchy.
- Deployment bundle: `build_deploy_data.py` + `review_interface/data/*.parquet`
  (lossless, 17 MB total), with app loaders preferring the copies and falling
  back to the `outputs/` CSVs.

## What remains pending (needs persisted data, not app work)

- Raw unmapped diagnosis text per member (only `unmapped_items` counts are
  persisted), so unmapped evidence cannot be shown as a list today.
- Per-label scores or longer inferred-label lists (the application output
  stores the top five labels only).
- Full-cohort default selection (currently a 1,000-member seeded sample;
  preset filters already search the full table).

## Open questions

1. **Full-cohort default selection.** Whether the default picker should
   eventually cover all 291,611 members (feasible; the sample is a demo-scale
   choice) and whether sample size/seed should be user-adjustable.
2. **Unmapped evidence list.** Whether the profile output should persist the
   raw unmapped diagnosis codes as text so the app can show them (they are
   currently count-only).
3. **Per-label detail.** Whether the application output should persist
   per-label scores or more than the top five labels; today the count is over
   the full 80-label vocabulary while only five labels are stored per member.
4. **Recalibration controls.** The burden trigger (3+), tier boundaries, and
   preset thresholds are fixed defaults; making them adjustable in the UI for
   review capacity is a small, clearly-labeled control change to add later.
