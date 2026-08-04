"""Read-only Streamlit viewer for member health profiles.

Built from the review-interface workstream recorded in
openspec/changes/oscar-member-health-study/study.md (DEC-007, DEC-008, and
DEC-009). The app consumes saved outputs under outputs/ exactly as they are
persisted; it does not train models, recompute the analysis, or write any files.

Primary purpose: a concise health-status view per member. The main area opens
on an anchored representative member whose concise health status is shown
first; other health information follows as a second layer. The default member
search and picker run over a fixed, seeded 1,000-member sample of the full
member profile table (outputs/profile/member_profiles.csv, 291,611 members).
Preset quick filters (for example high inferred burden, high claim volume,
stale prescriptions) search the full table and show qualifying members.
Prescription-only inference
(outputs/application/application_xgboost_inferred.csv, 49,610 members) is
left-joined by member_id; members without inference show "Not assessed" (not
evaluated), never a false negative.
For deployment, build_deploy_data.py writes compact parquet copies of these
outputs into review_interface/data/; when a copy exists the app reads it
instead, so the deployed bundle does not need the 169 MB CSV.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
APPLICATION_DIR = REPO_ROOT / "outputs" / "application"
PROFILE_DIR = REPO_ROOT / "outputs" / "profile"
LABELS_DIR = REPO_ROOT / "outputs" / "labels"
DATASET_DIR = REPO_ROOT / "outputs" / "dataset"
EVALUATION_DIR = REPO_ROOT / "outputs" / "evaluation"

PROFILE_CUTOFF = "2018-04-30"
RECENCY_WINDOW_DAYS = 365

MEMBER_PROFILES = PROFILE_DIR / "member_profiles.csv"
APPLICATION_INFERENCE = APPLICATION_DIR / "application_xgboost_inferred.csv"
MEDICATION_SUMMARY = PROFILE_DIR / "medication_hierarchy_summary.csv"
LABEL_DECISIONS = LABELS_DIR / "ccs_level2_label_decisions.csv"
LABEL_COMPARISON = EVALUATION_DIR / "label_comparison.csv"
VALIDATION_THRESHOLDS = EVALUATION_DIR / "xgboost_validation_thresholds.csv"
RETAINED_LABELS = DATASET_DIR / "retained_label_names.csv"
DEPLOY_DATA_DIR = Path(__file__).resolve().parent / "data"

# Default member search and picker use a fixed, seeded sample of the full
# member table (the full table is 177 MB). Preset quick filters search the
# full table instead, so rare unusual-care patterns stay reachable.
SAMPLE_SIZE = 1000
SAMPLE_SEED = 42
INFERENCE_SAMPLE_HALF = SAMPLE_SIZE // 2
PRESET_TOP_N = 200

# Review-signal semantics (DEC-008): `none` means evaluated and not triggered;
# `Not assessed` means not yet evaluated (here: member not in the inference
# cohort). The burden trigger is a fixed default (3+ inferred labels above
# threshold) and may be recalibrated for review capacity without changing the
# underlying evidence.
BURDEN_SIGNAL = "high inferred condition burden"
SIGNAL_OPTIONS = [BURDEN_SIGNAL, "none", "Not assessed"]
BURDEN_TRIGGER_MIN_COUNT = 3

# Inferred-count tiers requested by study.md for the worklist.
INFERRED_COUNT_TIERS = [
    ("0", 0, 0),
    ("1", 1, 1),
    ("2", 2, 2),
    ("3-4", 3, 4),
    ("5-9", 5, 9),
    ("10+", 10, None),
]

SORT_OPTIONS = {
    "Inferred condition count (high first)": ("inferred_condition_count", False),
    "Inferred condition count (low first)": ("inferred_condition_count", True),
    "Member ID (A-Z)": ("member_id", True),
}

# Preset quick filters over the full member table. Each preset is grounded in
# the study contract (DEC-008 trigger, study.md claim-volume flag, DEC-009
# patterns) and is a demonstration default: thresholds stay adjustable without
# changing the underlying evidence.
PRESETS = [
    {
        "name": "High inferred burden",
        "definition": f"`{BURDEN_SIGNAL}` ({BURDEN_TRIGGER_MIN_COUNT}+ inferred labels above threshold)",
        "matches": lambda df: df["review_signal"].eq(BURDEN_SIGNAL),
        "sort": "inferred_condition_count",
        "columns": ["member_id", "source_coverage", "inferred_condition_count", "review_signal"],
        "note": "DEC-008 fixed default for the review signal.",
        "hint": "3+ inferred conditions above validation threshold",
    },
    {
        "name": "High claim volume",
        "definition": "more than 10 distinct claim records",
        "matches": lambda df: df["unique_claim_records"] > 10,
        "sort": "unique_claim_records",
        "columns": ["member_id", "source_coverage", "unique_claim_records", "unique_claim_dates"],
        "note": "study.md flag example: 10 or more distinct claim records.",
        "hint": "10+ distinct outpatient claim records",
    },
    {
        "name": "Polypharmacy",
        "definition": "5 or more distinct drug classes",
        "matches": lambda df: df["distinct_classes"] >= 5,
        "sort": "distinct_classes",
        "columns": ["member_id", "source_coverage", "distinct_classes", "distinct_ndc", "prescription_fills"],
        "note": "Polypharmacy indicator from study.md (distinct NDC, category, group, class counts).",
        "hint": "5+ distinct drug classes",
    },
    {
        "name": "Stale prescriptions",
        "definition": "recency 842 or more days (last fill near the window start)",
        "matches": lambda df: df["recency_days"] >= 842,
        "sort": "recency_days",
        "columns": ["member_id", "source_coverage", "recency_days", "observed_span_days", "prescription_fills"],
        "note": "DEC-009 `stale_prescription_recency`: recency p99 about 842 days; an inactive-medication review pattern.",
        "hint": "Last fill 842+ days before cutoff",
    },
    {
        "name": "Many NDC, narrow categories",
        "definition": "8 or more distinct NDC with at most 2 drug categories",
        "matches": lambda df: (df["distinct_ndc"] >= 8) & (df["distinct_categories"] <= 2),
        "sort": "distinct_ndc",
        "columns": ["member_id", "source_coverage", "distinct_ndc", "distinct_categories", "distinct_groups"],
        "note": "DEC-009 `many_ndc_narrow_categories`: usually an explainable single-therapy context note, not an anomaly.",
        "hint": "Many distinct drugs, few categories — often explainable",
    },
    {
        "name": "Unmapped diagnosis codes",
        "definition": "at least one unmapped diagnosis code",
        "matches": lambda df: df["unmapped_items"].fillna(0) > 0,
        "sort": "unmapped_items",
        "columns": ["member_id", "source_coverage", "unmapped_items", "condition-like mapped_items"],
        "note": "Documentation-mismatch signal; unmapped codes are never presented as a known disease.",
        "hint": "Diagnosis codes that did not map to the medical dictionary",
    },
]
PRESET_BY_NAME = {preset["name"]: preset for preset in PRESETS}

# One-line definition used in the Notes section at the bottom of the member
# view. Template red lines: verbs are limited to "recorded in outpatient
# claims"; the words diagnosed / has / suffers from / active / resolved /
# persistent are never used.
CLAIM_EVIDENCE_NOTE = (
    "Items below are **recorded in outpatient claims** — evidence of documented "
    f"care, not a verified diagnosis. Recency is measured to the profile cutoff "
    f"**{PROFILE_CUTOFF}**. Absence of a recorded code is not absence of disease."
)

# Medication hierarchy rows are persisted without their level labels; the order
# matches notebook 01 execution (drug_category, drug_group, drug_class).
MEDICATION_LEVEL_ORDER = ["drug_category", "drug_group", "drug_class"]

RECENCY_GUIDE = {
    "ever recorded": "Any otherwise usable claim evidence exists, whether or not its date is reliable.",
    "recently recorded": "At least one time-valid record falls within the 365 days before the profile cutoff (2018-04-30).",
    "historically recorded": "Time-valid evidence exists on or before the cutoff, but the latest record predates the recency window.",
    "date unavailable/unreliable": "Supports only 'ever recorded'; no recency classification.",
    "outside profile cutoff": "Recorded after 2018-04-30; kept in the descriptive record but does not determine recent or historical status.",
}

PROVENANCE_GUIDE = {
    "claim-mapped observed": "Recorded in outpatient claims and mapped to a CCS category. Evidence of documented care, not independently verified clinical truth.",
    "claim-unmapped observed": "Recorded in outpatient claims but not mapped to a CCS category. Kept as raw evidence; excluded from CCS-based labels.",
    "prescription-inferred": "Estimated from prescription patterns by a model evaluated on members with mapped claims. Not confirmed by claims.",
    "time-valid": "The date passes the predeclared parsing and eligibility rules; may support recency, sequence, and time-windowed analysis.",
    "time-unreliable / time-unknown": "Otherwise usable evidence is retained but excluded from recency, sequence, and time-windowed modeling.",
}

# The eight member-level medication aggregates (study.md / DEC-009), as
# persisted in member_profiles.csv, with display labels.
MEDICATION_AGGREGATES = [
    ("distinct_prescription_dates", "Distinct prescription dates"),
    ("active_months", "Active months (months with at least one fill)"),
    ("distinct_ndc", "Distinct NDC"),
    ("distinct_categories", "Distinct drug categories"),
    ("distinct_groups", "Distinct drug groups"),
    ("distinct_classes", "Distinct drug classes"),
    ("observed_span_days", "Observed span (days)"),
    ("recency_days", "Recency (days since last fill)"),
]


def _deploy_copy(path: Path) -> Path | None:
    """Compact parquet copy of a persisted output, if build_deploy_data.py ran."""
    candidate = DEPLOY_DATA_DIR / f"{path.stem}.parquet"
    return candidate if candidate.exists() else None


def load_csv(path: Path, label: str) -> pd.DataFrame | None:
    """Read a persisted output, preferring the compact parquet copy.

    build_deploy_data.py writes review_interface/data/<stem>.parquet for each
    output the app loads; when the copy exists (for example in a deployed
    bundle) it is read instead of the outputs/ CSV. The outputs/ files remain
    the source of truth and are read when no copy exists. Returns None if the
    file is missing.
    """
    source = _deploy_copy(path) or path
    if not source.exists():
        st.warning(
            f"Missing input: {path.relative_to(REPO_ROOT)} ({label}). "
            "The app renders everything else that is available."
        )
        return None
    try:
        if source.suffix == ".parquet":
            frame = pd.read_parquet(source)
        else:
            frame = pd.read_csv(source)
        if "member_id" in frame.columns:
            frame["member_id"] = frame["member_id"].astype(str)
        return frame
    except Exception as exc:  # defensive read-only guard
        st.error(f"Could not read {source.relative_to(REPO_ROOT)}: {exc}")
        return None


@st.cache_data(show_spinner=False)
def load_member_profiles() -> pd.DataFrame | None:
    return load_csv(MEMBER_PROFILES, "member profiles (291,611 members)")


@st.cache_data(show_spinner=False)
def load_application_inference() -> pd.DataFrame | None:
    return load_csv(APPLICATION_INFERENCE, "application inference cohort")


@st.cache_data(show_spinner=False)
def load_full() -> pd.DataFrame | None:
    """Full member table with inference columns left-joined.

    One row per member (member_id unique in both sources, verified by read).
    Members without inference keep null inference columns and render as
    "Not assessed" (not evaluated), never as a false negative.
    """
    profiles = load_member_profiles()
    if profiles is None:
        return None
    inference = load_application_inference()
    if inference is None:
        profiles["inferred_condition_count"] = None
        profiles["top_inferred_labels"] = None
        profiles["review_signal"] = None
        return profiles
    return profiles.merge(
        inference[["member_id", "inferred_condition_count", "top_inferred_labels", "review_signal"]],
        on="member_id",
        how="left",
        validate="one_to_one",
    )


@st.cache_data(show_spinner=False)
def load_sample() -> pd.DataFrame | None:
    """Seeded 1,000-member sample of the full table (500 with inference, 500 without)."""
    full = load_full()
    if full is None:
        return None
    inferred_members = set(full.loc[full["inferred_condition_count"].notna(), "member_id"])
    with_inference = full[full["member_id"].isin(inferred_members)]
    without_inference = full[~full["member_id"].isin(inferred_members)]
    return pd.concat(
        [
            with_inference.sample(n=INFERENCE_SAMPLE_HALF, random_state=SAMPLE_SEED),
            without_inference.sample(
                n=min(SAMPLE_SIZE - INFERENCE_SAMPLE_HALF, len(without_inference)),
                random_state=SAMPLE_SEED + 1,
            ),
        ],
        ignore_index=True,
    )


@st.cache_data(show_spinner=False)
def load_medication_summary() -> pd.DataFrame | None:
    frame = load_csv(MEDICATION_SUMMARY, "medication hierarchy summary")
    if frame is None:
        return None
    labeled = frame.copy()
    labeled.insert(0, "hierarchy_level", MEDICATION_LEVEL_ORDER[: len(labeled)])
    return labeled


@st.cache_data(show_spinner=False)
def load_label_decisions() -> pd.DataFrame | None:
    return load_csv(LABEL_DECISIONS, "CCS Level 2 label decisions")


@st.cache_data(show_spinner=False)
def load_label_comparison() -> pd.DataFrame | None:
    return load_csv(LABEL_COMPARISON, "label comparison")


@st.cache_data(show_spinner=False)
def load_validation_thresholds() -> pd.DataFrame | None:
    return load_csv(VALIDATION_THRESHOLDS, "validation thresholds")


@st.cache_data(show_spinner=False)
def load_retained_labels() -> pd.DataFrame | None:
    return load_csv(RETAINED_LABELS, "retained label names")


@st.cache_data(show_spinner=False)
def load_label_vocabulary() -> list[str]:
    """Known label names from persisted reference tables, longest first.

    Used to parse top_inferred_labels: some CCS Level 2 names contain "; "
    themselves (for example "Pleurisy; pneumothorax; pulmonary collapse [130.]"),
    so a vocabulary longest-match parse is required instead of splitting on "; ".
    """
    names: set[str] = set()
    for loader in (load_retained_labels, load_validation_thresholds, load_label_decisions):
        frame = loader()
        if frame is None:
            continue
        column = "label" if "label" in frame.columns else frame.columns[0]
        names.update(frame[column].astype(str))
    return sorted(names, key=len, reverse=True)


def display_value(value: object) -> str:
    """Render a cell without turning an empty value into a claim."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    text = str(value).strip()
    return text if text else "—"


def as_int(value: object) -> int:
    """Return an int cell value, or 0 for missing/empty values."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def member_picker_label(row: pd.Series) -> str:
    """Dropdown label: member id, source coverage, and inference status.

    `Not assessed` means the member is not in the inference cohort, never a
    negative finding; an evaluated member shows its inferred-label count.
    """
    inferred = row.get("inferred_condition_count")
    if inferred is None or (isinstance(inferred, float) and pd.isna(inferred)):
        status = "Not assessed"
    else:
        count = int(inferred)
        status = f"{count} inferred label" + ("" if count == 1 else "s")
    return f"{row['member_id']} — {row['source_coverage']} · {status}"


def split_items(text: object) -> list[tuple[str, str]] | None:
    """Parse a persisted "recency: item | recency: item" string into pairs."""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return None
    raw = str(text).strip()
    if not raw:
        return None
    items: list[tuple[str, str]] = []
    for part in raw.split(" | "):
        if ": " in part:
            recency, item = part.split(": ", 1)
            items.append((recency.strip(), item.strip()))
        else:
            return None
    return items or None


def split_groups(text: object) -> list[str]:
    """Split a persisted " | "-joined drug-group string into groups."""
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return []
    return [group.strip() for group in str(text).split(" | ") if group.strip()]


def inferred_count_tier(count: float | int | None) -> str:
    """Map an inferred condition count to the study-tier label."""
    if count is None or (isinstance(count, float) and pd.isna(count)):
        return "Not assessed"
    for tier_label, low, high in INFERRED_COUNT_TIERS:
        if high is None and count >= low:
            return tier_label
        if low <= count <= high:
            return tier_label
    return "10+"


def split_labels(text: object, vocabulary: list[str] | None = None) -> list[str]:
    """Parse the persisted top-inferred-labels string into individual labels.

    Uses longest-match against the known label vocabulary because some CCS
    Level 2 label names contain "; " themselves. Falls back to plain "; "
    splitting when the vocabulary is unavailable (missing reference files).
    """
    if text is None or (isinstance(text, float) and pd.isna(text)):
        return []
    raw = str(text).strip()
    if not raw:
        return []
    if not vocabulary:
        return [part.strip() for part in raw.split(";") if part.strip()]
    labels: list[str] = []
    i = 0
    while i < len(raw):
        matched = None
        for name in vocabulary:
            if raw.startswith(name, i):
                end = i + len(name)
                if end == len(raw) or raw[end : end + 2] == "; ":
                    matched = name
                    break
        if matched is None:
            nxt = raw.find("; ", i)
            end = len(raw) if nxt == -1 else nxt
            labels.append(raw[i:end].strip())
            i = len(raw) if nxt == -1 else nxt + 2
        else:
            labels.append(matched)
            i += len(matched)
            if raw[i : i + 2] == "; ":
                i += 2
    return [label for label in labels if label]


def short_label_list(text: object, vocabulary: list[str] | None = None, limit: int = 3) -> str:
    """Compact label list for tables; full text stays in the detail."""
    labels = split_labels(text, vocabulary)
    if not labels:
        return ""
    if len(labels) <= limit:
        return "; ".join(labels)
    return "; ".join(labels[:limit]) + f"; … ({len(labels)} total)"


# Used only to choose the anchored example member (a demo choice, not an
# analytical claim): vague care-context categories are avoided, and items that
# name a common condition are preferred when several members are equally
# concrete.
VAGUE_CONDITION_MARKERS = (
    "factors influencing health care",
    "immunizations and screening",
    "screening",
    "symptoms; signs; and ill-defined conditions",
    "contraceptive and procreative management",
    "other and unspecified",
    "residual codes",
    "unclassified",
    "personal history",
    "family history",
    "administrative",
    "encounter for",
    "observation for",
    "aftercare",
    "follow-up",
    "examination",
)
COMMON_CONDITION_KEYWORDS = (
    "diabetes",
    "hypertension",
    "asthma",
    "migraine",
    "headache",
    "mood disorders",
    "depression",
    "anxiety",
    "arthritis",
    "thyroid",
    "lipid disorders",
    "cancer",
    "epilepsy",
    "anemia",
    "heart",
    "intestinal infection",
    "pneumonia",
    "influenza",
    "bronchitis",
    "eczema",
    "psoriasis",
    "gout",
    "obesity",
    "copd",
)


def condition_item_is_concrete(item: str) -> bool:
    """True when an observed item names a condition rather than care context."""
    lowered = item.lower()
    return not any(marker in lowered for marker in VAGUE_CONDITION_MARKERS)


def anchor_quality(member: pd.Series) -> tuple:
    """Anchor-choice score: concrete, recently concrete, documented, common,
    burden signal, inferred count, then most-recent medication fill (highest
    wins)."""
    items = split_items(member.get("observed_health_summary")) or []
    concrete = concrete_recent = common = 0
    for recency, item in items:
        if not condition_item_is_concrete(item):
            continue
        concrete += 1
        if recency == "recently recorded":
            concrete_recent += 1
        if any(keyword in item.lower() for keyword in COMMON_CONDITION_KEYWORDS):
            common += 1
    inferred = member.get("inferred_condition_count")
    inferred_count = (
        int(inferred) if inferred is not None and not pd.isna(inferred) else -1
    )
    recency = member.get("recency_days")
    if recency is None or pd.isna(recency):
        recency_score = -(10**9)
    else:
        recency_score = -int(recency)
    return (
        concrete,
        concrete_recent,
        documented_condition_count(member),
        common,
        bool(member.get("review_signal") == BURDEN_SIGNAL),
        inferred_count,
        recency_score,
    )


def anchored_member_id(sample: pd.DataFrame) -> str:
    """Deterministic representative member.

    Prefers a member with both claim and prescription evidence and at least
    two documented conditions, choosing the one whose recorded conditions are
    the most recognizable (common diseases preferred), so the default view
    reads as a concrete health status rather than vague care-context
    categories. The inference review signal is a tiebreaker, not a
    requirement.
    """
    coverage = sample["source_coverage"]
    documented = sample.apply(documented_condition_count, axis=1)
    for mask in [
        coverage.eq("claims and prescriptions") & documented.ge(2),
        sample["review_signal"].eq(BURDEN_SIGNAL),
        coverage.eq("claims and prescriptions"),
    ]:
        hits = sample[mask]
        if hits.empty:
            continue
        best_index = hits.apply(anchor_quality, axis=1).idxmax()
        return hits.loc[best_index, "member_id"]
    return sample.iloc[0]["member_id"]


def documented_condition_count(member: pd.Series) -> int:
    """Number of recorded claim conditions for a member."""
    items = split_items(member.get("observed_health_summary"))
    if items is not None:
        return len(items)
    return (
        as_int(member.get("recently_recorded_items"))
        + as_int(member.get("historically_recorded_items"))
        + as_int(member.get("date_unavailable_or_unreliable_items"))
    )


def one_line_summary_lines(member: pd.Series) -> list[str]:
    """Compact observed summary: one line per recency group, as persisted."""
    items = split_items(member.get("observed_health_summary"))
    if items is None:
        return []
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for recency, item in items:
        if recency not in grouped:
            grouped[recency] = []
            order.append(recency)
        grouped[recency].append(item)
    lines = []
    for key in order:
        label = key[0].upper() + key[1:]
        lines.append(f"{label}: {'; '.join(grouped[key])}")
    return lines


def render_concise_observed_summary(member: pd.Series) -> None:
    """One-line observed summary shown directly under the member identity."""
    st.markdown("**Concise health summary (observed)**")
    lines = one_line_summary_lines(member)
    if lines:
        for line in lines:
            st.markdown(f"- {line}")
        return
    raw = member.get("observed_health_summary")
    if isinstance(raw, str) and raw.strip():
        st.markdown(f"- {raw.strip()}")
    else:
        st.markdown(
            "- No condition evidence in the provided data; absence of a "
            "recorded code is not absence of disease."
        )


def render_concise_status(member: pd.Series) -> None:
    """Layer 1: the concise health status, four compact cards."""
    st.markdown("**Concise health status**")
    recently = as_int(member.get("recently_recorded_items"))
    historically = as_int(member.get("historically_recorded_items"))
    date_unavailable = as_int(member.get("date_unavailable_or_unreliable_items"))
    outside = as_int(member.get("outside_profile_cutoff_only_items"))
    total = recently + historically + date_unavailable
    c1, c2, c3, c4 = st.columns(4)
    if total == 0:
        c1.metric("Documented conditions", "None recorded")
        c1.caption("No condition evidence in the provided data; absence of a code is not absence of disease.")
    else:
        c1.metric("Documented conditions", f"{total:,}")
        breakdown = f"{recently} recently · {historically} historically · {date_unavailable} date unavailable"
        if outside:
            breakdown += f" · {outside} after cutoff"
        c1.caption(breakdown)

    claim_records = as_int(member.get("unique_claim_records"))
    claim_dates = as_int(member.get("unique_claim_dates"))
    c2.metric("Outpatient claims", f"{claim_records:,} records")
    c2.caption(f"{claim_dates:,} distinct claim dates")

    groups = split_groups(member.get("medication_summary"))
    fills = as_int(member.get("prescription_fills"))
    if groups:
        c3.metric("Medications", f"{len(groups):,} groups")
        c3.caption(f"{fills:,} prescription fills")
    else:
        c3.metric("Medications", "No evidence")
        c3.caption("No prescription evidence in the provided data; not a health judgment")

    inferred = member.get("inferred_condition_count")
    assessed = inferred is not None and not (isinstance(inferred, float) and pd.isna(inferred))
    if assessed:
        c4.metric("Inferred (prescription-only)", f"{int(inferred):,} labels")
        c4.caption(f"Review signal: {display_value(member.get('review_signal'))}")
    else:
        c4.metric("Inferred (prescription-only)", "Not assessed")
        c4.caption("Not in the inference cohort; not a negative finding")


def render_identity(member: pd.Series, anchored: bool = False) -> None:
    """Member identity bar: id, one-line observed summary, subtle source coverage."""
    with st.container(border=True):
        st.markdown(f"### Member {member['member_id']}")
        render_concise_observed_summary(member)
        suffix = " · anchored example member" if anchored else ""
        st.caption(
            f"Source coverage: {display_value(member.get('source_coverage'))}{suffix}"
        )


def render_observed_detail(member: pd.Series) -> None:
    """Second layer: full observed condition list on demand."""
    with st.expander(
        "Full condition list (date-ordered, most recent first)", expanded=True
    ):
        items = split_items(member.get("date_ordered_condition_items"))
        if items:
            for recency, item in items:
                st.markdown(f"- *{recency}*: {item}")
        else:
            st.markdown(display_value(member.get("date_ordered_condition_items")))
        st.caption(
            "Items are listed in claim-date order as persisted; recency labels "
            "follow the conservative language rules in the Notes below."
        )


def render_claims_usage_detail(member: pd.Series) -> None:
    """Second layer: claims-usage detail behind an expander."""
    with st.expander("Claims usage detail", expanded=True):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Distinct claim records", f"{as_int(member.get('unique_claim_records')):,}")
        c2.metric("Distinct claim dates", f"{as_int(member.get('unique_claim_dates')):,}")
        c3.metric("Same-day clusters", f"{as_int(member.get('multi_code_same_day_clusters')):,}")
        c4.metric("Latest cluster date", display_value(member.get("latest_multi_code_cluster_date")))
        st.markdown(
            f"- **Recorded on multiple dates items:** {as_int(member.get('recorded_on_multiple_dates_items')):,} "
            "(evidence on at least two distinct time-valid service dates)."
        )
        st.markdown(
            f"- **Time-valid same-day clusters:** {as_int(member.get('time_valid_same_day_clusters')):,} "
            "(same-day claim clusters, not confirmed visits)."
        )
        st.markdown(
            "- **Recency buckets:** "
            f"{as_int(member.get('recently_recorded_items')):,} recently · "
            f"{as_int(member.get('historically_recorded_items')):,} historically · "
            f"{as_int(member.get('date_unavailable_or_unreliable_items')):,} date unavailable · "
            f"{as_int(member.get('outside_profile_cutoff_only_items')):,} after cutoff."
        )


def render_medication_detail(member: pd.Series) -> None:
    """Second layer: medication detail behind an expander."""
    with st.expander("Medication detail", expanded=True):
        groups = split_groups(member.get("medication_groups_full")) or split_groups(member.get("medication_summary"))
        if groups:
            st.markdown("**Recorded medication groups:**")
            for group in groups:
                st.markdown(f"- {group}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Prescription fills", f"{as_int(member.get('prescription_fills')):,}")
        c2.metric("Drug categories", f"{as_int(member.get('drug_categories')):,}")
        c3.metric("Drug groups", f"{as_int(member.get('drug_groups')):,}")
        c4.metric("Drug classes", f"{as_int(member.get('drug_classes')):,}")
        st.markdown("**Member-level aggregates** (time-valid fills inside the core window, as persisted):")
        for column, label in MEDICATION_AGGREGATES:
            value = member.get(column)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                rendered = "date unavailable or unreliable"
            else:
                rendered = f"{int(value):,}" if float(value).is_integer() else f"{value:,.1f}"
            st.markdown(f"- **{label}:** {rendered}")


def render_inferred_detail(member: pd.Series) -> None:
    """Second layer: inference reading and validation context."""
    inferred = member.get("inferred_condition_count")
    if inferred is None or (isinstance(inferred, float) and pd.isna(inferred)):
        return
    labels = split_labels(member.get("top_inferred_labels"), load_label_vocabulary())
    with st.expander("Inference validation context", expanded=True):
        if labels:
            st.markdown(
                f"**Inferred labels ({len(labels)} persisted, highest predicted "
                "probability first):**"
            )
            for label in labels:
                st.markdown(f"- {label}")
        st.markdown(
            "- `inferred_condition_count` is the number of labels whose "
            "predicted probability passed the per-label F1-max validation "
            "threshold across the 80-label model vocabulary (fixed study "
            "default per DEC-008); it is not limited to the labels shown here."
        )
        st.markdown(
            "- The application output persists the top five labels only, in "
            "model-predicted order; labels below the top five and per-label "
            "scores are not stored."
        )
        thresholds = load_validation_thresholds()
        comparison = load_label_comparison()
        if thresholds is not None and labels:
            context = thresholds.copy()
            if comparison is not None:
                context = context.merge(
                    comparison[["label", "xgboost_ap", "xgboost_f1"]],
                    on="label",
                    how="inner",
                )
            present = context[context["label"].isin(labels)]
            if not present.empty:
                st.markdown(
                    "Validation thresholds and test performance for this "
                    "member's inferred labels (reference context, read-only):"
                )
                st.dataframe(present, width="stretch", hide_index=True)


def render_evidence_quality(member: pd.Series) -> None:
    """Evidence-quality and provenance notes behind a collapsed expander."""
    with st.expander("Evidence provenance and limitations"):
        st.markdown(
            "- Claim evidence shows **documented care**, not independently "
            "verified clinical health; absence of a code is not absence of "
            "disease."
        )
        st.markdown(
            "- Same-day clusters preserve co-recorded condition and contextual "
            "codes; they are not confirmed visits and do not establish "
            "causality or severity."
        )
        st.markdown(
            "- Cross-source mismatches may motivate human review but cannot "
            "establish that required care was missed."
        )
        st.markdown(
            "- Recency language stays conservative (ever / recently / "
            "historically recorded; date unavailable or unreliable; outside "
            "profile cutoff); it never becomes active, resolved, or persistent "
            "disease."
        )
        st.markdown(
            "- Inferred labels are presented only with validation-threshold "
            "and evaluation context and are never presented as claim-confirmed."
        )
        st.markdown("**Evidence quality**")
        st.markdown(display_value(member.get("evidence_quality")))
        st.markdown(
            f"**Claim time-limited records:** {as_int(member.get('claim_time_limited_records')):,} "
            "(cannot support recency or time-based conclusions)."
        )
        st.markdown(
            f"**Prescription time-limited records:** {as_int(member.get('prescription_time_limited_records')):,} "
            "(cannot support recency or time-based conclusions)."
        )
        unmapped = as_int(member.get("unmapped_items"))
        if unmapped > 0:
            st.markdown(
                f"**Unmapped diagnosis codes:** {unmapped:,} — kept as raw "
                "evidence, never presented as a mapped or known disease."
            )


def render_member_status(member: pd.Series, anchored: bool = False) -> None:
    """Full member view: identity, concise status first, details second."""
    render_identity(member, anchored=anchored)
    render_concise_status(member)
    st.divider()
    st.markdown("#### Detailed health information")
    render_observed_detail(member)
    render_claims_usage_detail(member)
    render_medication_detail(member)
    render_inferred_detail(member)
    render_evidence_quality(member)
    st.divider()
    st.markdown("#### Notes")
    st.caption(
        "Read-only: consumes saved outputs under `outputs/`; no models are "
        "trained and no analysis is recomputed on page load."
    )
    st.caption(CLAIM_EVIDENCE_NOTE)
    st.caption(
        "Source coverage describes how much evidence exists (claims only, "
        "prescriptions only, or both); absence of a source is not a health "
        "judgment."
    )
    st.markdown("**Recency definitions**")
    for label, meaning in RECENCY_GUIDE.items():
        st.caption(f"- **`{label}`:** {meaning}")
    if anchored:
        st.caption(
            "Anchored example member: a sample member with claim and "
            "prescription evidence whose recorded conditions are recognizable "
            "conditions (common diseases preferred), shown so the status view "
            "is not empty on load."
        )


def render_sidebar(sample: pd.DataFrame | None) -> None:
    with st.sidebar:
        st.header("Member selection")
        if sample is None:
            st.stop()
        assessed = int(sample["inferred_condition_count"].notna().sum())
        st.caption(
            f"Read-only; consumes saved outputs under `outputs/`. Default "
            f"search uses a seeded {len(sample):,}-member sample ({assessed} "
            "with inference); presets below search the full 291,611-member table."
        )
        search = st.text_input(
            "Search members",
            placeholder="member_id or text in the health or medication summary",
        ).strip().lower()
        matches = sample
        if search:
            text_hits = (
                sample["observed_health_summary"].fillna("")
                + " "
                + sample["medication_summary"].fillna("")
            ).str.lower().str.contains(search, regex=False)
            id_hits = sample["member_id"].str.lower().str.contains(search, regex=False)
            matches = sample[id_hits | text_hits]

        anchored = anchored_member_id(sample)
        anchored_label = member_picker_label(
            sample.loc[sample["member_id"] == anchored].iloc[0]
        )
        st.session_state.setdefault("sample_member", anchored_label)
        options = {
            member_picker_label(row): row.member_id for _, row in matches.iterrows()
        }
        if len(matches) == 0:
            st.info("No members match the search in the sample. Clear the search.")
        else:
            st.selectbox("Select a member to inspect", list(options), key="sample_member")

        st.markdown("**Presets (full population)**")
        st.caption(
            "These filters flag recorded-care patterns that may indicate "
            "unusual health care usage worth human review."
        )
        for preset in PRESETS:
            if st.button(preset["name"], key=f"preset_{preset['name']}"):
                st.session_state["active_preset"] = preset["name"]
            st.caption(preset["hint"])
        active = st.session_state.get("active_preset")
        if active:
            if st.button("Clear preset"):
                st.session_state.pop("active_preset", None)
                st.rerun()
            st.caption(
                f"Active preset: **{active}** — shown in the main area; "
                "**Clear preset** above resets the filter."
            )

        with st.expander("Language and evidence rules"):
            for label, meaning in PROVENANCE_GUIDE.items():
                st.markdown(f"- **`{label}`:** {meaning}")
            st.markdown("**Recency:**")
            for label, meaning in RECENCY_GUIDE.items():
                st.markdown(f"- `{label}`: {meaning}")
            st.markdown(
                "No visit identifier is provided; `member_id` plus a service "
                "date defines only a same-day claim cluster, not a confirmed "
                "visit or encounter."
            )
            st.markdown(
                f"Profile cutoff {PROFILE_CUTOFF}; recency window the preceding "
                f"{RECENCY_WINDOW_DAYS} days."
            )


def render_preset_view(full: pd.DataFrame, preset: dict) -> None:
    """Preset quick-filter view: qualifying members from the full table."""
    st.subheader(f"Preset: {preset['name']}")
    st.caption(f"{preset['definition']}. {preset['note']}")
    matches = full[preset["matches"](full)].sort_values(preset["sort"], ascending=False)
    st.caption(
        f"**{len(matches):,} members** qualify in the full 291,611-member "
        f"table; showing the top {min(PRESET_TOP_N, len(matches))} by "
        f"`{preset['sort']}` (highest first) below."
    )
    if len(matches) == 0:
        st.info("No members qualify for this preset. Choose another preset or clear it.")
        return
    top = matches.head(PRESET_TOP_N)
    st.dataframe(top[preset["columns"]], width="stretch", hide_index=True)
    options = {member_picker_label(row): row.member_id for _, row in top.iterrows()}
    choice = st.selectbox("Select a member from the preset matches", list(options), key="preset_member")
    member = full.loc[full["member_id"] == options[choice]].iloc[0]
    render_member_status(member)


def render_status_tab(sample: pd.DataFrame, full: pd.DataFrame) -> None:
    """Primary tab: anchored member by default; presets replace the picker."""
    active_preset = st.session_state.get("active_preset")
    if active_preset:
        render_preset_view(full, PRESET_BY_NAME[active_preset])
        return
    selected_label = st.session_state.get("sample_member")
    if selected_label is None:
        selected_label = ""
    selected_id = selected_label.split(" — ")[0]
    hit = sample.loc[sample["member_id"] == selected_id]
    if hit.empty:
        hit = sample.loc[sample["member_id"] == anchored_member_id(sample)]
    member = hit.iloc[0]
    render_member_status(member, anchored=member["member_id"] == anchored_member_id(sample))


def render_worklist_tab(sample: pd.DataFrame) -> None:
    """Secondary surface: review worklist over the sampled members."""
    st.subheader("Review worklist")
    st.caption(
        "Secondary surface: review of inferred health status over the "
        "1,000-member sample. Members without inference show `Not assessed`."
    )
    c1, c2 = st.columns(2)
    member_query = c1.text_input("Member ID", placeholder="e.g. M0000001")
    label_query = c2.text_input("Top inferred labels contain", placeholder="e.g. Diabetes")
    c3, c4 = st.columns(2)
    signals = c3.multiselect(
        "Review signal",
        SIGNAL_OPTIONS,
        default=list(SIGNAL_OPTIONS),
        help=(
            "`none` = evaluated and not triggered. "
            f"`{BURDEN_SIGNAL}` = {BURDEN_TRIGGER_MIN_COUNT} or more inferred labels "
            "above threshold. `Not assessed` = not in the inference cohort."
        ),
    )
    tiers = c4.multiselect(
        "Inferred count tier",
        [tier[0] for tier in INFERRED_COUNT_TIERS] + ["Not assessed"],
        default=[tier[0] for tier in INFERRED_COUNT_TIERS] + ["Not assessed"],
    )
    sources = st.multiselect(
        "Source coverage",
        sorted(sample["source_coverage"].dropna().unique()),
        default=sorted(sample["source_coverage"].dropna().unique()),
    )
    sort_key = st.selectbox("Sort worklist by", list(SORT_OPTIONS), index=0)

    out = sample.copy()
    member_query = member_query.strip().lower()
    if member_query:
        out = out[out["member_id"].str.lower().str.contains(member_query, regex=False)]
    label_query = label_query.strip().lower()
    if label_query:
        out = out[
            out["top_inferred_labels"]
            .fillna("")
            .str.lower()
            .str.contains(label_query, regex=False)
        ]
    if signals:
        out = out[out["review_signal"].fillna("Not assessed").isin(signals)]
    if tiers:
        out = out[out["inferred_condition_count"].map(inferred_count_tier).isin(tiers)]
    if sources:
        out = out[out["source_coverage"].isin(sources)]

    shown = len(out)
    burden = int(out["review_signal"].eq(BURDEN_SIGNAL).sum())
    assessed = int(out["inferred_condition_count"].notna().sum())
    medians = out["inferred_condition_count"].dropna()
    median = medians.median() if len(medians) else None
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Members shown", f"{shown:,}", f"of {len(sample):,} in the sample")
    m2.metric("Burden signal (3+ labels)", f"{burden:,}")
    m3.metric("With inferred labels", f"{assessed:,}")
    m4.metric("Median inferred labels", f"{median:g}" if median is not None else "—")

    vocabulary = load_label_vocabulary()
    table = out[
        ["member_id", "source_coverage", "inferred_condition_count", "review_signal", "top_inferred_labels"]
    ].copy()
    table["inferred_condition_count"] = table["inferred_condition_count"].map(
        lambda v: "Not assessed" if pd.isna(v) else f"{int(v):,}"
    )
    table["review_signal"] = table["review_signal"].fillna("Not assessed")
    table["top_inferred_labels"] = table["top_inferred_labels"].map(
        lambda value: short_label_list(value, vocabulary)
    )
    column, ascending = SORT_OPTIONS[sort_key]
    if column == "inferred_condition_count":
        table["_sort"] = out["inferred_condition_count"]
        table = table.sort_values("_sort", ascending=ascending, na_position="last").drop(columns="_sort")
    else:
        table = table.sort_values(column, ascending=ascending)
    st.dataframe(table, width="stretch", hide_index=True)
    st.caption(
        "`inferred_condition_count` is the number of labels above threshold; "
        "`top_inferred_labels` is the persisted top-five label list. Inferred "
        "labels are prescription-inferred, not claim-confirmed."
    )


def render_reference_tab() -> None:
    """Reference tables: label decisions, thresholds, comparison, hierarchy."""
    st.subheader("Reference tables")
    st.markdown(
        "Reference tables are shown as persisted under `outputs/`. The status "
        "view reads `outputs/profile/member_profiles.csv`; inference comes from "
        "`outputs/application/application_xgboost_inferred.csv`."
    )
    med = load_medication_summary()
    if med is not None:
        st.markdown(
            "**Medication hierarchy summary** (levels labeled by notebook "
            "execution order; the persisted CSV omits the level column):"
        )
        st.dataframe(med, width="stretch", hide_index=True)

    decisions = load_label_decisions()
    if decisions is not None:
        retained = int(decisions["retained_for_modeling"].sum())
        st.markdown(
            f"**CCS Level 2 label decisions** — {len(decisions)} candidate "
            f"labels, {retained} retained for prescription-only modeling:"
        )
        st.dataframe(decisions, width="stretch", hide_index=True)

    thresholds = load_validation_thresholds()
    if thresholds is not None:
        st.markdown(
            f"**XGBoost validation thresholds** ({len(thresholds)} labels, "
            "F1-max operating points per DEC-008):"
        )
        st.dataframe(thresholds, width="stretch", hide_index=True)

    comparison = load_label_comparison()
    if comparison is not None:
        st.markdown(
            f"**XGBoost vs logistic, per label** ({len(comparison)} labels, "
            "protected-test context):"
        )
        st.dataframe(comparison, width="stretch", hide_index=True)

    retained_names = load_retained_labels()
    if retained_names is not None:
        st.markdown(f"**Retained label names** ({len(retained_names)} labels):")
        st.dataframe(retained_names, width="stretch", hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Member Health Profile Viewer", layout="wide")
    st.title("Member Health Profile Viewer")
    # Left-align sidebar button labels (preset quick filters); Streamlit
    # centers them by default. Static CSS only; no user input is interpolated.
    st.markdown(
        "<style>"
        "[data-testid='stSidebar'] [data-testid='stButton'] button {"
        "justify-content: flex-start;"
        "}"
        "[data-testid='stSidebar'] [data-testid='stButton'] button * {"
        "text-align: left;"
        "}"
        "</style>",
        unsafe_allow_html=True,
    )

    sample = load_sample()
    full = load_full()
    render_sidebar(sample)
    if sample is None or full is None:
        st.stop()

    tab_status, tab_worklist, tab_reference = st.tabs(
        ["Member health status", "Review worklist", "Reference tables"]
    )
    with tab_status:
        render_status_tab(sample, full)
    with tab_worklist:
        render_worklist_tab(sample)
    with tab_reference:
        render_reference_tab()

    st.divider()
    st.caption(
        "Read-only: no files are written by this app. Default member selection "
        "uses a fixed, seeded 1,000-member sample; presets search the full "
        "persisted table. The full persisted outputs are unchanged."
    )


if __name__ == "__main__":
    main()
