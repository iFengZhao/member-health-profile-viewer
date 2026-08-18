# Member Health Profile Viewer (read-only)

**Status: optional, outside the recommended four-hour core.**

This app is an optional extension per the "Optional Streamlit review
interface" section of `openspec/changes/oscar-member-health-study/study.md` and
decisions `DEC-007`, `DEC-008`, and `DEC-009`. It is **not required** for
reviewer assessment of the core study, and no core conclusion depends on it.

## Purpose

The app's primary purpose is a **concise health-status view per member**. The
main area opens on an anchored representative member: the first section is
their concise health status (four compact cards: documented conditions,
outpatient claims, medications, inferred status), and the remaining health
information follows as a second layer behind expanders. Review of **inferred
health status** (the worklist) is an additional surface.

## What it does

- **Member health status (primary tab)** — opens on an anchored representative
  member (a sample member with claim and prescription evidence whose recorded
  conditions are recognizable conditions, common diseases preferred; the
  inference review signal is a tiebreaker, not a requirement). Directly under
  the member id, a one-line **Concise health summary (observed)** shows the
  recorded conditions as short lines
  (`Recently recorded: …`, `Historically recorded: …`, plus outside-cutoff or
  date-unavailable lines when present); source coverage follows as a small
  gray caption under the summary; the four compact status cards come next.
  Detailed health information (full date-ordered condition list, claims
  usage, medication groups and aggregates, prescription-based inference context,
  evidence quality) is layer two behind expanders. Explanatory notes
  (claim-evidence definition, recency definitions, source-coverage meaning,
  read-only behavior, anchored-member rationale) sit at the bottom of the
  member view so the top stays concise.
- **Control panel (sidebar)** — compact: `Search members` and
  `Select a member to inspect` run over a fixed, seeded 1,000-member sample;
  preset quick filters search the **full 291,611-member table** and are reset
  with the `Clear preset` button shown in the sidebar while a preset is active.
- **Preset quick filters (full population)** — one click applies a filter and
  shows the qualifying members (top 200 by the preset's key field), from which
  a member can be selected for the status view:
  - High inferred burden (`high inferred condition burden`, 3+ condition-level
    signals above their condition-specific cutoffs; DEC-008 default)
  - High claim volume (`unique_claim_records > 10`; study.md flag example)
  - Polypharmacy (`distinct_classes >= 5`)
  - Stale prescriptions (`recency_days >= 842`; DEC-009 p99 tail)
  - Many NDC, narrow categories (`distinct_ndc >= 8`, `distinct_categories <= 2`;
    DEC-009 single-therapy context note, not an anomaly)
  - Unmapped diagnosis codes (`unmapped_items > 0`)
- **Review worklist (secondary tab)** — filters over the sample (review
  signal, inferred-count tiers, top-label text, member ID, source coverage)
  with summary cards and a compact table.
- **Reference tables** — CCS Level 2 label decisions (135 candidates, 80
  retained), XGBoost validation thresholds (80), XGBoost-vs-logistic
  comparison (80), retained label names (80), and the medication hierarchy
  summary.
- **Read-only** — consumes saved outputs under `outputs/` exactly as
  persisted; no models are trained and no analysis is recomputed on page load;
  nothing is written by the app.
- Conservative language only (ever / recently / historically recorded; date
  unavailable or unreliable; outside profile cutoff). The app distinguishes
  the number of condition probabilities above their cutoffs from the separate
  top-five probability ranking. Neither is presented as observed or diagnosed;
  `Not assessed` (not in the inference cohort) is never a negative finding.

## Data inputs (read-only)

| Input | Role |
|---|---|
| `outputs/profile/member_profiles.csv` | Primary source: full member profile table (291,611 members, one row per member) |
| `outputs/application/application_xgboost_inferred.csv` | Prescription-based inference results for the 49,610-member inference cohort, left-joined by `member_id` |
| `outputs/evaluation/xgboost_validation_thresholds.csv` | Per-label probability cutoffs selected to maximize F1 on validation data (reference context) |
| `outputs/evaluation/label_comparison.csv` | XGBoost-vs-logistic per-label comparison (reference context) |
| `outputs/labels/ccs_level2_label_decisions.csv` | CCS Level 2 label decisions (135 candidates, 80 retained) |
| `outputs/dataset/retained_label_names.csv` | Retained label names (80; label vocabulary for parsing) |
| `outputs/profile/medication_hierarchy_summary.csv` | Medication hierarchy coverage |

For deployment, `review_interface/build_deploy_data.py` writes lossless parquet copies of all seven inputs under `review_interface/data/` (17 MB total; `member_profiles.parquet` is 16.3 MB); the app reads the copies when present and falls back to the `outputs/` CSVs.

The default member picker uses a fixed, seeded 1,000-member sample of the
member table (500 from the 49,610-member inference cohort, 500 from the rest)
so every profile surface is visible without loading the 177 MB full table into
the browser. Preset filters search the full table instead, so rare
unusual-care patterns stay reachable. The full persisted outputs are
unchanged; `SAMPLE_SIZE`/`SAMPLE_SEED` and the preset definitions live in
`review_interface/app.py`.

## Run

Streamlit is not in the project `pyproject.toml` (deliberately, to keep the core
environment untouched). Run with an ephemeral dependency:

```bash
# from the repository root
uv run --with streamlit streamlit run review_interface/app.py
```

Or in a dedicated virtual environment (does not touch the project environment):

```bash
python3 -m venv .venv-review
.venv-review/bin/pip install -r review_interface/requirements.txt
.venv-review/bin/streamlit run review_interface/app.py
```

Both options read only `outputs/` and `review_interface/`. When `review_interface/data/*.parquet` exists (built as described below), the app reads those compact copies instead of the `outputs/` CSVs.

## Deployment (free tiers)

The heavy input (`outputs/profile/member_profiles.csv`, 169 MB) exceeds
GitHub's 100 MB single-file limit, so the app prefers a compact parquet copy
when one exists. Build it once — read-only over `outputs/`, writes only under
`review_interface/`:

```bash
# from the repository root
uv run --with pyarrow --offline --no-sync python review_interface/build_deploy_data.py
```

This writes `review_interface/data/*.parquet`: every row and column preserved,
measured 2026-08-03 at 17 MB total (of which `member_profiles.parquet` is
16.3 MB, down from 169 MB). The app loads the parquet copies when present and
falls back to the `outputs/` CSVs otherwise, so local development is
unchanged.

**Streamlit Community Cloud (free, recommended).** Push `review_interface/`
to a public GitHub repository, then sign in at share.streamlit.io and create
an app pointing at `app.py` on that repository. Free tier: 1 GB RAM, public
app, sleeps after inactivity and wakes on the next visit; the ~17 MB data
bundle fits comfortably (no Git LFS needed). Streamlit Cloud installs the
pinned dependencies in `review_interface/requirements.txt` (`streamlit`,
`pandas`, `pyarrow`). Note the app is publicly accessible on this tier,
including its derived member-level data.

**Hugging Face Spaces (paid only).** HF deprecated the Streamlit hosted SDK
and now requires a PRO subscription to host Gradio/Docker Spaces, so the free
tier cannot run this app. The included `Dockerfile` (sdk: docker, port 7860)
is ready if a paid HF Space is ever wanted.

Both deployment paths keep the app read-only; neither writes to `outputs/` or
`data/raw/`.

## Current caveats

- The default member picker samples 1,000 members; members outside the sample
  are reachable only through preset filters (which search the full table).
- Unmapped diagnosis evidence is persisted as a count only (`unmapped_items`);
  the raw unmapped code text is not in the saved profile output, so the app
  shows the count with a "never presented as a known disease" note.
- `recency_days` is null for members without a time-valid prescription fill
  (about a quarter of the table); the app renders it as "date unavailable or
  unreliable".
- The application output persists the five highest-probability condition
  candidates per member. Member-specific probabilities and the identities of
  the conditions above cutoff are not stored, so the viewer cannot identify
  which conditions produced `inferred_condition_count`.
- Preset thresholds are demonstration defaults grounded in DEC-008/DEC-009 and
  study.md; they stay adjustable without changing the underlying evidence.

See `DESIGN_NOTES.md` for design decisions and open questions.
