"""
360 Technician Productivity Dashboard - v2
==========================================
Changes vs v1:
  * AUTO-DETECT: one uploader, drop both files in any order. The app fingerprints
    each file by its columns and assigns it to the App or ERP slot itself.
  * VALIDATION PANEL: every file gets a green/red report before it is used.
  * FOOTER STRIP: Irium exports carry trailing summary rows ("Duration",
    "Number of records", blanks). These are removed automatically.
  * NAME NORMALISATION: "BOISSEAU Nicolas" (app) and "NICOLAS BOISSEAU" (ERP
    mapping) are now recognised as the same person -> filters and comparison work.
  * BILLABLE FIX: v1 classified every ERP row as Billable because the Hour Type
    test ("MAIN D'OEUVRE") fired before the Group test, and Group was a float
    ("100.0") so it never matched the string list. Group is now the primary rule.
  * COMPARISON TAB: app-declared hours vs ERP-booked hours per technician.
"""

import re
import unicodedata

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

# ----------------------------------------------------------------------------
# CONFIGURATION - edit these when staff or ERP codes change
# ----------------------------------------------------------------------------

TECH_MAPPING = {
    2: "DILROY SEEBALACK",
    4: "NICOLAS BOISSEAU",
    5: "MICHEL FLORENTINE",
    8: "DITLANE JACOBS",
    11: "NAILI SAMIR",
    13: "HESTON ANSON",
    15: "MATTHIEU DERAIN",
    16: "JUNO CARVAJAL",
    17: "PAOLO RAMOS",
    18: "IBAN OBANDO",
    19: "HERODE ADRIEN",
    20: "Guevara Aguilar Jesus Alfonzo",
    21: "Jurman VAN GENDEREN",
    22: "BYRON LOPEZ",
}

WO_STATUS_MAPPING = {
    "AC": "QUOTE ACCEPTED",
    "AP": "TO INVOICE PARTIALLY",
    "CP": "IN ACCOUNTING",
    "DE": "QUOTE PRINTED",
    "EC": "IN PROGRESS",
    "ED": "QUOTE EDITED",
    "FC": "INVOICED",
    "RE": "QUOTE REFUSED",
    "TE": "QUOTE COMPLETED",
    "TP": "FINISHED PARTIALLY",
    "TR": "QUOTE TRANSFERRED TO ORDER",
    "TT": "TOTALLY FINISHED",
}

# ERP 'Group' -> revenue treatment. Anything not listed defaults to Non-Billable.
ERP_BILLABLE_GROUPS = {100, 101, 104, 200}   # external customer work
ERP_INTERNAL_GROUPS = {300}                  # own-branch / internal WOs
ERP_WARRANTY_GROUPS = {400, 500}             # warranty / goodwill

# App activity codes -> category
APP_BILLABLE_CODES = {"20", "30"}   # Main d'oeuvre, Temps de trajet
APP_BREAK_CODES = {"100"}           # Pause
APP_LEAVE_CODES = {"108", "102"}    # Conge paye, RCC - excluded from expected hrs

STANDARD_DAY_HOURS = 7.0
BILLING_RATE_EUR = 90.0          # used to value the recovery gap

# Attendance columns in the app timesheet - the "hours actually paid for".
ATT_ARRIVAL = "Heure arrivee"
ATT_DEPARTURE = "Heure depart"
ATT_WORKED = "Heures travaillees"     # declared worked hours, format "7h15"
ATT_OVERTIME = "Depassement horaire"
ATT_LATE = "Retard (min)"

# Column fingerprints used to recognise a file
APP_REQUIRED = ["Date", "Technicien", "Activite - Debut", "Activite - Fin", "Code"]
ERP_REQUIRED = ["Shre Salarie", "Date", "WO No.", "Hour Type", "Status", "Group"]


# ----------------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------------

def deaccent(text: str) -> str:
    """Lowercase, strip accents and punctuation - used for fuzzy column and name matching."""
    text = str(text).replace("œ", "oe").replace("Œ", "OE")
    text = text.replace("æ", "ae").replace("Æ", "AE")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def name_key(name) -> str:
    """Order-independent person key: 'BOISSEAU Nicolas' == 'NICOLAS BOISSEAU'."""
    return " ".join(sorted(deaccent(name).split()))


def find_col(df, target):
    """Return the real column name matching `target` ignoring accents/case/spacing."""
    want = deaccent(target)
    for col in df.columns:
        if deaccent(col) == want:
            return col
    for col in df.columns:                     # partial fallback
        if want in deaccent(col):
            return col
    return None


def read_any(uploaded):
    if uploaded.name.lower().endswith(".csv"):
        return pd.read_csv(uploaded)
    return pd.read_excel(uploaded, sheet_name=0)


def detect_kind(df):
    """Return ('app'|'erp'|None, missing_columns)."""
    app_missing = [c for c in APP_REQUIRED if find_col(df, c) is None]
    erp_missing = [c for c in ERP_REQUIRED if find_col(df, c) is None]
    if len(app_missing) <= len(erp_missing) and len(app_missing) <= 1:
        return "app", app_missing
    if len(erp_missing) <= 1:
        return "erp", erp_missing
    # neither is a clean match - report whichever is closest
    if len(app_missing) < len(erp_missing):
        return None, app_missing
    return None, erp_missing


def strip_footer(df, key_col):
    """Drop Irium summary rows: keep only rows whose key column is a clean integer id."""
    keys = df[key_col].astype(str).str.strip()
    return df[keys.str.fullmatch(r"\d+")].copy()


def add_period_cols(df, date_col):
    parsed = pd.to_datetime(df[date_col], errors="coerce", dayfirst=False)
    df["Date_Parsed"] = parsed
    df["Year"] = parsed.dt.year.astype("Int64").astype(str).replace("<NA>", "Unknown")
    df["Month"] = parsed.dt.month.astype("Int64").astype(str).replace("<NA>", "Unknown")
    df["Week"] = parsed.dt.isocalendar().week.astype("Int64").astype(str).replace("<NA>", "Unknown")
    return df


def expected_hours(dmin, dmax, year, month, week):
    """Working-day baseline for the selected period."""
    if pd.isna(dmin) or pd.isna(dmax):
        return 0.0
    start = dmin - pd.to_timedelta(dmin.dayofweek, unit="d")
    end = dmax + pd.to_timedelta(6 - dmax.dayofweek, unit="d")
    cal = pd.DataFrame({"Date": pd.date_range(start, end)})
    cal["Year"] = cal["Date"].dt.year.astype(str)
    cal["Month"] = cal["Date"].dt.month.astype(str)
    cal["Week"] = cal["Date"].dt.isocalendar().week.astype("Int64").astype(str)
    if year != "Total":
        cal = cal[cal["Year"] == year]
    if month != "Total":
        cal = cal[cal["Month"] == month]
    if week != "Total":
        cal = cal[cal["Week"] == week]
    return float((cal["Date"].dt.dayofweek < 5).sum() * STANDARD_DAY_HOURS)


def parse_hm(value):
    """'7h15' -> 7.25. Also accepts plain numbers."""
    text = str(value).strip().lower()
    if "h" in text:
        head, _, tail = text.partition("h")
        try:
            return int(head) + (int(tail) / 60 if tail.strip() else 0)
        except ValueError:
            return np.nan
    try:
        return float(text)
    except ValueError:
        return np.nan


def build_attendance(df):
    """One row per technician-day: what the company actually paid for.

    declared_h  - the technician's own 'Heures travaillees' (span minus breaks)
    span_h      - departure minus arrival, the full clock window
    segment_h   - activity segments net of breaks and leave
    overrun_h   - segment_h beyond declared_h; >0 means overlapping entries,
                  NOT overtime (overtime is flagged separately)
    """
    c_arr, c_dep = find_col(df, ATT_ARRIVAL), find_col(df, ATT_DEPARTURE)
    c_work, c_ot = find_col(df, ATT_WORKED), find_col(df, ATT_OVERTIME)
    c_late = find_col(df, ATT_LATE)

    keep = ["Technicien", "Date_Parsed"] + [c for c in (c_arr, c_dep, c_work, c_ot, c_late) if c]
    day = df[keep].drop_duplicates(["Technicien", "Date_Parsed"]).copy()

    day["declared_h"] = day[c_work].map(parse_hm) if c_work else np.nan

    if c_arr and c_dep:
        base = day["Date_Parsed"].dt.strftime("%Y-%m-%d")
        arr = pd.to_datetime(base + " " + day[c_arr].astype(str), errors="coerce")
        dep = pd.to_datetime(base + " " + day[c_dep].astype(str), errors="coerce")
        span = (dep - arr).dt.total_seconds() / 3600.0
        day["span_h"] = span.where(span >= 0, span + 24)
    else:
        day["span_h"] = np.nan

    day["overtime_flag"] = day[c_ot].astype(str).str.strip().str.lower().eq("oui") if c_ot else False
    day["late_min"] = pd.to_numeric(day[c_late], errors="coerce").fillna(0) if c_late else 0.0

    productive = df[~df["Category"].isin(["Break", "Leave"])]
    seg = productive.groupby(["Technicien", "Date_Parsed"])["Duration_Hours"].sum().rename("segment_h")
    day = day.merge(seg, on=["Technicien", "Date_Parsed"], how="left")
    day["segment_h"] = day["segment_h"].fillna(0)
    day["overrun_h"] = np.maximum(0, day["segment_h"] - day["declared_h"])
    day["idle_h"] = np.maximum(0, day["declared_h"] - day["segment_h"])
    return day


def classify_erp(group_value, hour_type):
    try:
        grp = int(float(group_value))
    except (TypeError, ValueError):
        grp = None
    if grp in ERP_BILLABLE_GROUPS:
        return "Billable"
    if grp in ERP_INTERNAL_GROUPS:
        return "Internal"
    if grp in ERP_WARRANTY_GROUPS:
        return "Warranty"
    if grp is None and "main d oeuvre" in deaccent(hour_type):
        return "Billable"          # last-resort fallback when Group is blank
    return "Non-Billable"


def classify_app(code):
    code = str(code).strip()
    if code.endswith(".0"):
        code = code[:-2]
    if code in APP_BREAK_CODES:
        return "Break"
    if code in APP_LEAVE_CODES:
        return "Leave"
    if code in APP_BILLABLE_CODES:
        return "Billable"
    return "Non-Billable"


# ----------------------------------------------------------------------------
# PAGE
# ----------------------------------------------------------------------------

st.set_page_config(page_title="Technician Productivity Dashboard", layout="wide")
st.title("360 Technician Productivity Dashboard")
st.caption("Self-reported app timesheet vs official ERP (Irium) labour booking.")

st.sidebar.header("Data")
uploads = st.sidebar.file_uploader(
    "Drop both files here (any order)",
    type=["xlsx", "xls", "csv"],
    accept_multiple_files=True,
    help="Expected: 'Rapport journalier des heures*.xlsx' (app) and the Irium "
         "technician-hours export (ERP). The app identifies each file by its columns.",
)

app_df = erp_df = app_att = None
reports = []

for up in uploads or []:
    try:
        raw = read_any(up)
    except Exception as exc:
        reports.append(("error", up.name, f"Could not open the file: {exc}"))
        continue

    kind, missing = detect_kind(raw)

    if kind is None:
        reports.append((
            "error", up.name,
            "Not recognised as an App timesheet or an ERP export. "
            f"Closest match is missing: {', '.join(missing)}",
        ))
        continue

    if kind == "app":
        if app_df is not None:
            reports.append(("warn", up.name, "A second App timesheet was ignored - upload one at a time."))
            continue
        df = raw.copy()
        df = df.rename(columns={find_col(df, "Technicien"): "Technicien"})
        df = df[df["Technicien"].notna()].copy()
        df = add_period_cols(df, find_col(df, "Date"))
        bad_dates = int(df["Date_Parsed"].isna().sum())
        df = df[df["Date_Parsed"].notna()].copy()
        df["Name_Key"] = df["Technicien"].map(name_key)

        c_start, c_end = find_col(df, "Activite - Debut"), find_col(df, "Activite - Fin")
        c_code, c_or = find_col(df, "Code"), find_col(df, "Numero OR - Main d oeuvre")
        base = df["Date_Parsed"].dt.strftime("%Y-%m-%d")
        start = pd.to_datetime(base + " " + df[c_start].astype(str), errors="coerce")
        end = pd.to_datetime(base + " " + df[c_end].astype(str), errors="coerce")
        dur = (end - start).dt.total_seconds() / 3600.0
        df["Duration_Hours"] = dur.where(dur >= 0, dur + 24).fillna(0)
        df["Category"] = df[c_code].map(classify_app)
        df["Code_Clean"] = df[c_code].astype(str).str.replace(r"\.0$", "", regex=True)
        df["Has_WO"] = df[c_or].notna() if c_or else False

        app_df = df
        app_att = build_attendance(df)
        note = f"App timesheet - {len(df)} activity rows, {df['Technicien'].nunique()} technicians, " \
               f"{df['Date_Parsed'].min():%d/%m/%Y} to {df['Date_Parsed'].max():%d/%m/%Y}."
        if bad_dates:
            note += f" {bad_dates} row(s) dropped for unreadable dates."
        reports.append(("ok", up.name, note))

    else:  # erp
        if erp_df is not None:
            reports.append(("warn", up.name, "A second ERP export was ignored - upload one at a time."))
            continue
        df = raw.copy()
        sal_col = find_col(df, "Shre Salarie")
        before = len(df)
        df = strip_footer(df, sal_col)
        dropped = before - len(df)
        df["Salarie_Id"] = df[sal_col].astype(float).astype(int)
        df = add_period_cols(df, find_col(df, "Date"))
        df = df[df["Date_Parsed"].notna()].copy()
        df["Tech_Name"] = df["Salarie_Id"].map(TECH_MAPPING)
        unmapped = sorted(df.loc[df["Tech_Name"].isna(), "Salarie_Id"].unique().tolist())
        df["Tech_Name"] = df["Tech_Name"].fillna("ID " + df["Salarie_Id"].astype(str) + " (unmapped)")
        df["Name_Key"] = df["Tech_Name"].map(name_key)
        erp_df = df
        note = f"ERP export - {len(df)} labour lines, {df['Tech_Name'].nunique()} technicians, " \
               f"{df['Date_Parsed'].min():%d/%m/%Y} to {df['Date_Parsed'].max():%d/%m/%Y}."
        if dropped:
            note += f" {dropped} summary/footer row(s) removed."
        reports.append(("ok", up.name, note))
        if unmapped:
            reports.append((
                "warn", up.name,
                f"Employee ID(s) {unmapped} are not in TECH_MAPPING - they show as 'unmapped'. "
                "Add them at the top of Techapp.py.",
            ))

# --- validation panel -------------------------------------------------------
if reports:
    st.sidebar.markdown("### File check")
    for level, fname, msg in reports:
        icon = {"ok": "OK", "warn": "CHECK", "error": "FAIL"}[level]
        body = f"**{icon} - {fname}**\n\n{msg}"
        (st.sidebar.success if level == "ok" else
         st.sidebar.warning if level == "warn" else st.sidebar.error)(body)

if app_df is None:
    st.sidebar.info("No App timesheet loaded yet.")
if erp_df is None:
    st.sidebar.info("No ERP export loaded yet.")

# --- global filters ---------------------------------------------------------
years, months, weeks, techs = set(), set(), set(), set()
for d, tcol in ((app_df, "Technicien"), (erp_df, "Tech_Name")):
    if d is not None:
        years |= set(d["Year"].unique())
        months |= set(d["Month"].unique())
        weeks |= set(d["Week"].unique())
        techs |= set(d[tcol].dropna().unique())

st.sidebar.markdown("---")
st.sidebar.header("Period")
sel_year = st.sidebar.selectbox("Year", ["Total"] + sorted(y for y in years if y != "Unknown"))
sel_month = st.sidebar.selectbox("Month", ["Total"] + sorted((m for m in months if m != "Unknown"), key=int))
sel_week = st.sidebar.selectbox("Week", ["Total"] + sorted((w for w in weeks if w != "Unknown"), key=int))

st.sidebar.header("Denominator")
denominator = st.sidebar.radio(
    "Hours paid for",
    ["Attendance - declared", "Attendance - clock span", f"Calendar ({STANDARD_DAY_HOURS:g} h x weekdays)"],
    help="Attendance uses the technician's own arrival/departure record, so the "
         "denominator is the time you actually paid for on the days they attended. "
         "Calendar assumes a fixed working day and charges absent days against them.",
)

st.sidebar.header("Technicians")
excluded = st.sidebar.multiselect(
    "Exclude", options=sorted(techs),
    help="Excluding a name here also excludes the matching name in the other file.",
)
excluded_keys = {name_key(t) for t in excluded}


def apply_filters(df):
    out = df.copy()
    if sel_year != "Total":
        out = out[out["Year"] == sel_year]
    if sel_month != "Total":
        out = out[out["Month"] == sel_month]
    if sel_week != "Total":
        out = out[out["Week"] == sel_week]
    if excluded_keys:
        out = out[~out["Name_Key"].isin(excluded_keys)]
    return out


COLORS = {"Billable Hours": "#2ca02c", "Non-Billable Hours": "#d62728",
          "Unreported Hours": "#7f7f7f", "Internal Hours": "#ff7f0e",
          "Warranty Hours": "#9467bd"}

if app_df is None and erp_df is None:
    st.info("Upload your files in the sidebar. Both can be dropped at once - the app sorts them out.")
    st.stop()

tab_app, tab_erp, tab_cmp, tab_fun = st.tabs(
    ["Self-reported (App)", "Official ERP (Irium)", "App vs ERP", "Recovery funnel"])

# ============================================================================
# TAB 1 - APP
# ============================================================================
app_summary = pd.DataFrame()
with tab_app:
    if app_df is None:
        st.warning("No App timesheet loaded.")
    else:
        d = app_df.copy()
        f = apply_filters(d)
        work = f[~f["Category"].isin(["Break", "Leave"])]

        att = app_att.merge(d[["Technicien", "Date_Parsed", "Year", "Month", "Week", "Name_Key"]]
                            .drop_duplicates(["Technicien", "Date_Parsed"]),
                            on=["Technicien", "Date_Parsed"], how="left")
        att_f = apply_filters(att)

        baseline = expected_hours(d["Date_Parsed"].min(), d["Date_Parsed"].max(),
                                  sel_year, sel_month, sel_week)

        if denominator.startswith("Attendance - declared"):
            paid = att_f.groupby("Technicien")["declared_h"].sum()
        elif denominator.startswith("Attendance - clock"):
            paid = att_f.groupby("Technicien")["span_h"].sum()
        else:
            paid = None

        roster = [t for t in d["Technicien"].dropna().unique() if name_key(t) not in excluded_keys]
        agg = (work.groupby("Technicien")
               .apply(lambda x: pd.Series({
                   "Total Logged Hours": x["Duration_Hours"].sum(),
                   "Billable Hours": x.loc[x["Category"] == "Billable", "Duration_Hours"].sum(),
                   "Non-Billable Hours": x.loc[x["Category"] == "Non-Billable", "Duration_Hours"].sum(),
               }), include_groups=False)
               .reset_index() if len(work) else
               pd.DataFrame(columns=["Technicien", "Total Logged Hours", "Billable Hours", "Non-Billable Hours"]))

        app_summary = pd.merge(pd.DataFrame({"Technicien": roster}), agg, on="Technicien", how="left").fillna(0)
        if paid is not None:
            app_summary["Expected Hours"] = app_summary["Technicien"].map(paid).fillna(0)
        else:
            app_summary["Expected Hours"] = baseline
        app_summary["Unreported Hours"] = np.maximum(
            0, app_summary["Expected Hours"] - app_summary["Total Logged Hours"])
        app_summary["Effective Total Hours"] = app_summary["Total Logged Hours"] + app_summary["Unreported Hours"]
        app_summary["Productivity (%)"] = np.where(
            app_summary["Effective Total Hours"] > 0,
            app_summary["Billable Hours"] / app_summary["Effective Total Hours"] * 100, 0)
        app_summary["Name_Key"] = app_summary["Technicien"].map(name_key)
        app_summary = app_summary.sort_values("Productivity (%)", ascending=False)

        st.caption(f"Denominator: **{denominator}**. Productivity = billable hours divided by the "
                   "hours paid for, so time neither logged nor billed counts against the score.")
        eff = app_summary["Effective Total Hours"].sum()
        cols = st.columns(5)
        cols[0].metric("Hours paid", f"{app_summary['Expected Hours'].sum():.1f} h")
        cols[1].metric("Logged", f"{app_summary['Total Logged Hours'].sum():.1f} h")
        cols[2].metric("Billable", f"{app_summary['Billable Hours'].sum():.1f} h")
        cols[3].metric("Unaccounted", f"{app_summary['Unreported Hours'].sum():.1f} h")
        cols[4].metric("Team productivity",
                       f"{(app_summary['Billable Hours'].sum() / eff * 100) if eff else 0:.1f} %")

        left, right = st.columns(2)
        with left:
            melted = app_summary.melt(id_vars="Technicien",
                                      value_vars=["Billable Hours", "Non-Billable Hours", "Unreported Hours"],
                                      var_name="Type", value_name="Hours")
            fig = px.bar(melted, x="Technicien", y="Hours", color="Type",
                         color_discrete_map=COLORS, barmode="stack", title="Hours split by technician")
            st.plotly_chart(fig, use_container_width=True)
        with right:
            fig2 = px.bar(app_summary, x="Technicien", y="Productivity (%)",
                          text=app_summary["Productivity (%)"].map("{:.1f}%".format),
                          color="Productivity (%)", color_continuous_scale="Blues",
                          title="Productivity %")
            fig2.update_traces(textposition="outside")
            st.plotly_chart(fig2, use_container_width=True)

        c_lib = find_col(f, "Libelle activite")
        with st.expander("Activity code breakdown"):
            keys = ["Code_Clean"] + ([c_lib] if c_lib else [])
            st.dataframe(f.groupby(keys)["Duration_Hours"].sum().round(2)
                         .reset_index().sort_values("Duration_Hours", ascending=False),
                         use_container_width=True)

# ============================================================================
# TAB 2 - ERP
# ============================================================================
erp_summary = pd.DataFrame()
with tab_erp:
    if erp_df is None:
        st.warning("No ERP export loaded.")
    else:
        d = erp_df.copy()
        c_hours = find_col(d, "Time carried out") or find_col(d, "Duration")
        c_status, c_group = find_col(d, "Status"), find_col(d, "Group")
        c_hourtype, c_wo = find_col(d, "Hour Type"), find_col(d, "WO No.")

        d[c_hours] = pd.to_numeric(d[c_hours], errors="coerce").fillna(0)
        d["Category"] = [classify_erp(g, h) for g, h in zip(d[c_group], d[c_hourtype])]
        d["Status_Label"] = d[c_status].map(WO_STATUS_MAPPING).fillna(d[c_status].astype(str))

        f = apply_filters(d)
        baseline = expected_hours(d["Date_Parsed"].min(), d["Date_Parsed"].max(),
                                  sel_year, sel_month, sel_week)

        roster = [t for t in d["Tech_Name"].dropna().unique() if name_key(t) not in excluded_keys]
        pivot = (f.pivot_table(index="Tech_Name", columns="Category", values=c_hours,
                               aggfunc="sum").fillna(0).reset_index()
                 if len(f) else pd.DataFrame({"Tech_Name": []}))
        for cat in ["Billable", "Non-Billable", "Internal", "Warranty"]:
            if cat not in pivot.columns:
                pivot[cat] = 0.0
        pivot = pivot.rename(columns={"Billable": "Billable Hours", "Non-Billable": "Non-Billable Hours",
                                      "Internal": "Internal Hours", "Warranty": "Warranty Hours"})

        erp_summary = pd.merge(pd.DataFrame({"Tech_Name": roster}), pivot, on="Tech_Name", how="left").fillna(0)
        erp_summary["Total Hours Worked"] = erp_summary[
            ["Billable Hours", "Non-Billable Hours", "Internal Hours", "Warranty Hours"]].sum(axis=1)
        erp_summary["Expected Hours"] = baseline
        erp_summary["Unreported Hours"] = np.maximum(0, baseline - erp_summary["Total Hours Worked"])
        erp_summary["Effective Total Hours"] = erp_summary["Total Hours Worked"] + erp_summary["Unreported Hours"]
        erp_summary["Productivity (%)"] = np.where(
            erp_summary["Effective Total Hours"] > 0,
            erp_summary["Billable Hours"] / erp_summary["Effective Total Hours"] * 100, 0)
        erp_summary["Name_Key"] = erp_summary["Tech_Name"].map(name_key)
        erp_summary = erp_summary.sort_values("Productivity (%)", ascending=False)

        st.caption("Productivity = Billable / (Hours booked + Unreported). Internal (Group 300) and "
                   "warranty (400/500) hours are worked but not customer-billable.")
        eff = erp_summary["Effective Total Hours"].sum()
        cols = st.columns(6)
        cols[0].metric("Expected", f"{erp_summary['Expected Hours'].sum():.1f} h")
        cols[1].metric("Booked", f"{erp_summary['Total Hours Worked'].sum():.1f} h")
        cols[2].metric("Billable", f"{erp_summary['Billable Hours'].sum():.1f} h")
        cols[3].metric("Internal", f"{erp_summary['Internal Hours'].sum():.1f} h")
        cols[4].metric("Warranty", f"{erp_summary['Warranty Hours'].sum():.1f} h")
        cols[5].metric("Team productivity", f"{(erp_summary['Billable Hours'].sum() / eff * 100) if eff else 0:.1f} %")

        left, right = st.columns(2)
        with left:
            melted = erp_summary.melt(
                id_vars="Tech_Name",
                value_vars=["Billable Hours", "Internal Hours", "Warranty Hours",
                            "Non-Billable Hours", "Unreported Hours"],
                var_name="Type", value_name="Hours")
            fig = px.bar(melted, x="Tech_Name", y="Hours", color="Type",
                         color_discrete_map=COLORS, barmode="stack", title="Booked ERP hours split")
            st.plotly_chart(fig, use_container_width=True)
        with right:
            fig2 = px.bar(erp_summary, x="Tech_Name", y="Productivity (%)",
                          text=erp_summary["Productivity (%)"].map("{:.1f}%".format),
                          color="Productivity (%)", color_continuous_scale="Greens",
                          title="Official ERP productivity %")
            fig2.update_traces(textposition="outside")
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("---")
        st.subheader("Work order detail")
        drill = st.multiselect("Drill down into technician(s)",
                               options=sorted(f["Tech_Name"].dropna().unique()))
        sub = f[f["Tech_Name"].isin(drill)] if drill else f
        wo = (sub.pivot_table(index=[c_wo, "Status_Label"], columns="Category",
                              values=c_hours, aggfunc="sum").fillna(0).reset_index()
              if len(sub) else pd.DataFrame(columns=[c_wo, "Status_Label"]))
        for cat in ["Billable", "Non-Billable", "Internal", "Warranty"]:
            if cat not in wo.columns:
                wo[cat] = 0.0
        wo["Total Hours"] = wo[["Billable", "Non-Billable", "Internal", "Warranty"]].sum(axis=1)
        st.dataframe(wo.sort_values("Total Hours", ascending=False).round(2), use_container_width=True)

# ============================================================================
# TAB 3 - COMPARISON
# ============================================================================
with tab_cmp:
    if app_df is None or erp_df is None:
        st.warning("Upload both files to compare declared hours against booked hours.")
    else:
        a = app_summary[["Name_Key", "Technicien", "Total Logged Hours", "Billable Hours"]].rename(
            columns={"Total Logged Hours": "App Logged", "Billable Hours": "App Billable"})
        e = erp_summary[["Name_Key", "Tech_Name", "Total Hours Worked", "Billable Hours"]].rename(
            columns={"Total Hours Worked": "ERP Booked", "Billable Hours": "ERP Billable"})
        m = pd.merge(a, e, on="Name_Key", how="outer").fillna(0)
        m["Technician"] = np.where(m["Technicien"] != 0, m["Technicien"], m["Tech_Name"])
        m["Gap (App - ERP)"] = m["App Billable"] - m["ERP Billable"]
        m = m[["Technician", "App Logged", "App Billable", "ERP Booked", "ERP Billable", "Gap (App - ERP)"]]
        m = m.sort_values("Gap (App - ERP)", key=abs, ascending=False)

        st.subheader("Declared vs booked")
        st.caption("A large positive gap means the technician logged billable time in the app that never "
                   "reached a work order in Irium - revenue leakage. A negative gap means the app timesheet "
                   "is incomplete.")
        st.dataframe(m.round(2), use_container_width=True)

        melted = m.melt(id_vars="Technician", value_vars=["App Billable", "ERP Billable"],
                        var_name="Source", value_name="Hours")
        st.plotly_chart(px.bar(melted, x="Technician", y="Hours", color="Source",
                               barmode="group", title="Billable hours: app vs ERP"),
                        use_container_width=True)

# ============================================================================
# TAB 4 - RECOVERY FUNNEL
# ============================================================================
with tab_fun:
    if app_df is None:
        st.warning("Upload the App timesheet to build the funnel.")
    else:
        d = apply_filters(app_df)
        att = app_att.merge(app_df[["Technicien", "Date_Parsed", "Year", "Month", "Week", "Name_Key"]]
                            .drop_duplicates(["Technicien", "Date_Parsed"]),
                            on=["Technicien", "Date_Parsed"], how="left")
        att = apply_filters(att)

        paid_h = att["declared_h"].sum()
        span_h = att["span_h"].sum()
        productive = d[~d["Category"].isin(["Break", "Leave"])]
        logged_h = productive["Duration_Hours"].sum()
        billable_h = d.loc[d["Category"] == "Billable", "Duration_Hours"].sum()
        direct_h = d.loc[d["Code_Clean"] == "20", "Duration_Hours"].sum()
        wo_h = d.loc[(d["Code_Clean"] == "20") & (d["Has_WO"]), "Duration_Hours"].sum()

        booked_h = np.nan
        if erp_df is not None:
            e = apply_filters(erp_df)
            c_hours = find_col(e, "Time carried out") or find_col(e, "Duration")
            booked_h = pd.to_numeric(e[c_hours], errors="coerce").fillna(0).sum()

        st.subheader("Where the paid hour goes")
        st.caption("Each step is a place hours can be lost. The last two steps are where the "
                   "money is: direct labour that never got a work order number, and work-order "
                   "labour that never reached Irium.")

        steps = [
            ("Hours paid (declared attendance)", paid_h),
            ("Logged in activity segments", logged_h),
            ("Billable-coded (20 + 30)", billable_h),
            ("Direct labour only (20)", direct_h),
            ("Direct labour carrying a WO number", wo_h),
        ]
        if not np.isnan(booked_h):
            steps.append(("Booked in Irium", booked_h))

        fun = pd.DataFrame(steps, columns=["Stage", "Hours"])
        fun["% of paid"] = np.where(paid_h > 0, fun["Hours"] / paid_h * 100, 0)
        fun["Lost vs previous"] = fun["Hours"].shift(1) - fun["Hours"]

        cols = st.columns(4)
        cols[0].metric("Hours paid", f"{paid_h:.1f} h")
        cols[1].metric("Clock span", f"{span_h:.1f} h")
        if not np.isnan(booked_h):
            cols[2].metric("Booked in Irium", f"{booked_h:.1f} h")
            cols[3].metric("Recovery (booked / paid)",
                           f"{booked_h / paid_h * 100 if paid_h else 0:.1f} %")
        else:
            cols[2].metric("Billable-coded", f"{billable_h:.1f} h")
            cols[3].metric("Billable / paid", f"{billable_h / paid_h * 100 if paid_h else 0:.1f} %")

        st.plotly_chart(
            px.bar(fun, x="Hours", y="Stage", orientation="h",
                   text=fun["Hours"].map("{:.0f} h".format),
                   title="Recovery funnel").update_yaxes(autorange="reversed"),
            use_container_width=True)
        st.dataframe(fun.round(1), use_container_width=True)

        if not np.isnan(booked_h) and wo_h > booked_h:
            st.error(f"**{wo_h - booked_h:.1f} h** of work-order labour was logged in the app but "
                     f"never booked in Irium - worth **EUR {(wo_h - booked_h) * BILLING_RATE_EUR:,.0f}** "
                     f"at EUR {BILLING_RATE_EUR:g}/h. Confirm the Irium export is not filtered to a "
                     "single branch or department before acting on this.")

        st.markdown("---")
        st.subheader("Timesheet integrity")
        st.caption("Activity segments should never exceed declared worked hours. Where they do, "
                   "segments overlap or were entered twice - it is not overtime, which is flagged "
                   "separately in the timesheet.")

        bad = att[att["overrun_h"] > 0.25].copy()
        ic = st.columns(4)
        ic[0].metric("Technician-days", f"{len(att)}")
        ic[1].metric("Days with overrun", f"{len(bad)}")
        ic[2].metric("Overrun hours", f"{att['overrun_h'].sum():.1f} h")
        ic[3].metric("Overtime-flagged days", f"{int(att['overtime_flag'].sum())}")

        if len(bad):
            show = bad[["Technicien", "Date_Parsed", "span_h", "declared_h",
                        "segment_h", "overrun_h", "overtime_flag"]].copy()
            show["Date_Parsed"] = show["Date_Parsed"].dt.strftime("%d/%m/%Y")
            show = show.rename(columns={"Date_Parsed": "Date", "span_h": "Clock span",
                                        "declared_h": "Declared", "segment_h": "Segments",
                                        "overrun_h": "Overrun", "overtime_flag": "Overtime flagged"})
            st.dataframe(show.sort_values("Overrun", ascending=False).round(2),
                         use_container_width=True)
        else:
            st.success("No segment overruns - the timesheet reconciles to attendance.")

        st.markdown("---")
        st.subheader("Idle time per technician")
        st.caption("Paid attendance not covered by any activity segment.")
        idle = att.groupby("Technicien").agg(
            **{"Hours paid": ("declared_h", "sum"),
               "Segments": ("segment_h", "sum"),
               "Idle": ("idle_h", "sum"),
               "Overrun": ("overrun_h", "sum"),
               "Days": ("declared_h", "size")}).reset_index()
        idle["Idle %"] = np.where(idle["Hours paid"] > 0, idle["Idle"] / idle["Hours paid"] * 100, 0)
        st.dataframe(idle.sort_values("Idle", ascending=False).round(1), use_container_width=True)
