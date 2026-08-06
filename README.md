# Technician Productivity Dashboard

A Streamlit dashboard that compares what technicians **say** they did (self-reported
app timesheet) against what was **booked to a work order** in the Irium ERP, and
turns the difference into a productivity figure per technician.

Built for the SURMAC Cayenne service branch.

---

## Table of contents

1. [What it does](#what-it-does)
2. [Installation](#installation)
3. [Running the app](#running-the-app)
4. [The two input files](#the-two-input-files)
   - [File A — App timesheet](#file-a--app-timesheet-rapport-journalier-des-heures)
   - [File B — ERP export](#file-b--erp-export-irium-technician-hours)
5. [Upload procedure](#upload-procedure)
6. [How the numbers are calculated](#how-the-numbers-are-calculated)
7. [Configuration](#configuration)
8. [Troubleshooting](#troubleshooting)
9. [Changelog](#changelog)

---

## What it does

Three tabs:

| Tab | Source | Question it answers |
|---|---|---|
| **Self-reported (App)** | technician timesheet | How does the technician account for their day? |
| **Official ERP (Irium)** | labour lines on work orders | What did we actually book, and how much of it is billable? |
| **App vs ERP** | both | Where is billable time being logged but never invoiced? |
| **Recovery funnel** | both + attendance | Of every hour paid for, how much survives to a booked work order? |

Global filters (year / month / week / excluded technicians) apply to all three tabs
at once, so every figure on screen always refers to the same period.

---

## Installation

Requires Python 3.9 or later.

```bash
git clone https://github.com/RuizSimons/Technician-Productivity.git
cd Technician-Productivity
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## Running the app

```bash
streamlit run Techapp.py
```

The dashboard opens at `http://localhost:8501`. Nothing is uploaded anywhere — files
are read in memory and discarded when you close the tab.

---

## The two input files

The dashboard needs **two files**. They are different in origin, different in shape,
and neither can be substituted for the other.

| | File A — App timesheet | File B — ERP export |
|---|---|---|
| **Who makes it** | The technicians, in the field app / form | You, from Irium |
| **Typical filename** | `Rapport journalier des heures (N).xlsx` | `TechnicianHours_<dates>.xlsx`, `Labor_Hours_Irium_<dates>.xlsx` |
| **What it measures** | What the technician *says* they did, minute by minute | What was *booked to a work order* and can be invoiced |
| **Header language** | French | English |
| **First column** | `Date` | `Shre Salarie` |
| **Grain** | One row per activity block | One row per labour line on a WO |

> **Rule of thumb:** if the first column header is `Shre Salarie`, it is the ERP file.
> If it is `Date` and the second is `Technicien`, it is the app file.

You do not need to remember which uploader slot is which — there is only one
uploader and the app identifies each file by its column signature.

---

### File A — App timesheet (`Rapport journalier des heures`)

Export the responses sheet as `.xlsx`. **Sheet 1** (`Feuille 1`) is used; the
`Récapitulatif mensuel` sheet is a pivot and is ignored.

#### Required columns — exact headers, accents included

| # | Header | Used for | Format |
|---|---|---|---|
| 1 | `Date` | period filters | a real date, not text |
| 2 | `Technicien` | grouping | `SURNAME Firstname` |
| 3 | `Heure arrivée` | attendance denominator | `HH:MM:SS` |
| 4 | `Heure départ` | attendance denominator | `HH:MM:SS` |
| 5 | `Retard (min)` | lateness | minutes |
| 6 | `Heures travaillées` | **hours paid for** | `7h15` format |
| 7 | `Dépassement horaire` | overtime flag | `Oui` / `Non` |
| 9 | `Activité — Début` | duration | `HH:MM:SS` |
| 10 | `Activité — Fin` | duration | `HH:MM:SS` |
| 11 | `Code` | billable classification | number, or `AUT` |
| 14 | `Numéro OR — Main d'œuvre (20)` | work-order linkage | 8-digit WO number |

All other columns (`Commune`, `Commentaires`, `Horodatage`, …) are carried through
untouched, and extra columns are harmless. **Do not rename or reorder those above** —
that is the only thing that breaks it.

`Heures travaillées` is the technician's own declared worked time: clock span minus
breaks. It is the closest thing in the data to *hours the company paid for*, which is
why it is the default denominator.

Header matching ignores accents, case and spacing, so `Activite - Debut` also works.

#### Activity codes

| Code | Label | Counted as |
|---|---|---|
| `20` | Main d'œuvre | **Billable** |
| `30` | Temps de trajet | **Billable** |
| `100` | Pause | Break — removed from the day entirely |
| `102` | RCC | Leave — removed |
| `108` | Congé payé | Leave — removed |
| `80` | Contamination contrôle | Non-billable |
| `85` | Lavage équipement | Non-billable |
| `101` | Nettoyage | Non-billable |
| `105` | Temps d'inactivité | Non-billable |
| `107` | Entretien | Non-billable |
| `110` | Supervision | Non-billable |
| `112` | Formation | Non-billable |
| `113` | Réunion | Non-billable |
| `114` | Préparation travail | Non-billable |
| `116` | Retard | Non-billable |
| `AUT` | Autre (préciser) | Non-billable |

#### What gets rejected

- **Date stored as text.** If the export writes `07/04/2026` as a string, the row is
  dropped. Format column A as a Date before exporting.
- **Blank `Technicien`.** Dropped.
- **Times written as `10h00` or `10.00` instead of `10:00:00`.** Duration becomes 0.

---

### File B — ERP export (Irium technician hours)

This is the **labour-lines** report. It is *not* the invoice export
(`data (NN).xlsx`, columns `cust_num` / `invoice_no` / `net_amount`) and *not*
`Control printing of the WO…`. Both of those have entirely different columns and
will be rejected with a message telling you what is missing.

#### Required columns

| Header | Used for | Notes |
|---|---|---|
| `Shre Salarie` | technician identity | numeric employee ID, mapped to a name in `TECH_MAPPING` |
| `Date` | period filters | a real date |
| `WO No.` | work-order drill-down | 8 digits |
| `Hour Type` | fallback classification | e.g. `MAIN D'OEUVRE` |
| `Status` | WO status label | 2-letter code (`EC`, `TE`, `FC`, …) |
| `Group` | **billable classification** | 100 / 200 / 300 / 400 / 500 |
| `Time carried out` | the hours themselves | decimal hours; `Duration` used if absent |

Also kept and available: `Branch`, `Customer name`, `Labor type`, `Sort`, `Type`,
`Start`, `End`, `Hourly rate`.

#### Group codes

| Group | Meaning | Counted as |
|---|---|---|
| `100`, `101`, `104` | External customer labour | **Billable** |
| `200` | Customer sale / VTE | **Billable** |
| `300` | Internal — own-branch work order | Internal (worked, not billable) |
| `400`, `500` | Warranty / goodwill | Warranty (worked, not billable) |

#### Work-order status codes

`AC` quote accepted · `AP` to invoice partially · `CP` in accounting ·
`DE` quote printed · `EC` in progress · `ED` quote edited · `FC` invoiced ·
`RE` quote refused · `TE` quote completed · `TP` finished partially ·
`TR` quote transferred to order · `TT` totally finished

#### What gets rejected

- **Footer rows.** Irium appends summary lines (`Duration`, a total, `Number of
  records`) at the bottom of the sheet. These are stripped automatically — any row
  whose `Shre Salarie` is not a plain integer is discarded.
- **Unmapped employee IDs.** Any ID absent from `TECH_MAPPING` shows as
  `ID 7 (unmapped)` and raises a `CHECK` warning. Add the name to the table at the
  top of `Techapp.py`.

---

## Upload procedure

1. Start the app and open it in your browser.
2. Drag **both** files into the single uploader in the sidebar. Order does not matter.
3. Read the **File check** panel. Each file gets one of:

   | Status | Meaning |
   |---|---|
   | `OK` | Recognised. Shows row count, technician count and date range — verify the date range is the period you expected. |
   | `CHECK` | Loaded, but something needs attention (unmapped IDs, a duplicate upload). |
   | `FAIL` | Not recognised. The message lists exactly which columns are missing. |

4. Set Year / Month / Week. Exclude any borrowed technicians.
5. Read the tabs. In **App vs ERP**, a large positive gap means billable time was
   logged in the app that never reached a work order in Irium.

---

## How the numbers are calculated

```
Hours paid        = per the selected denominator (see below)
Unaccounted hours = max(0, Hours paid − Logged)
Effective hours   = Logged + Unaccounted        ( = max(Logged, Hours paid) )
Productivity %    = Billable ÷ Effective hours
```

### Choosing a denominator

Set this in the sidebar. It is the single biggest lever on the reported number.

| Option | Denominator | Use when |
|---|---|---|
| **Attendance — declared** (default) | `Heures travaillées` summed over the days attended | You want productivity against hours actually paid for. Absent days are excluded, so it does not punish approved leave. |
| **Attendance — clock span** | `Heure départ − Heure arrivée` | You want to include paid break time in the denominator — a stricter, site-occupancy view. |
| **Calendar (7 h × weekdays)** | Fixed working day × working days in the period | Legacy behaviour. Charges every absent day against the technician, so it conflates absence with idleness. |

Unaccounted time is deliberately treated as non-billable: not filling in the
timesheet lowers the score rather than hiding it.

Note that when logged segments exceed attendance (see *Timesheet integrity*), the
denominator falls back to the logged total. That is conservative but distorted —
fix the overlapping entries rather than reading the score.

### Recovery funnel

The fourth tab traces one paid hour through every stage where it can be lost:

```
Hours paid → Logged in segments → Billable-coded (20+30)
           → Direct labour (20) → Carrying a WO number → Booked in Irium
```

The last drop is usually the largest and the most expensive: labour the technician
logged against a work order that never reached the ERP. It is valued at
`BILLING_RATE_EUR` (default €90/h).

**Before acting on that figure, confirm the Irium labour export is not filtered to a
single branch or department** — a filtered export produces the same symptom.

### Timesheet integrity

Activity segments should never exceed declared worked hours. Where they do, segments
overlap or were entered twice. This is *not* overtime — overtime is flagged separately
in `Dépassement horaire`, and the two do not correlate in practice. The integrity
panel lists every offending technician-day so the form data can be corrected.

Breaks (code `100`) and leave (`102`, `108`) are removed from the app calculation
entirely, so a technician is neither credited nor penalised for them.

On the ERP side, internal (Group 300) and warranty (Groups 400/500) hours are shown
as their own stacked segments. They are real work but not customer-billable, so they
sit between billable and unreported in the chart.

---

## Configuration

All settings live in a single block at the top of `Techapp.py`.

| Constant | Purpose |
|---|---|
| `TECH_MAPPING` | ERP employee ID → technician name. **Update when staff change.** |
| `WO_STATUS_MAPPING` | 2-letter WO status → readable label |
| `ERP_BILLABLE_GROUPS` | Group codes that count as customer-billable |
| `ERP_INTERNAL_GROUPS` | Group codes for own-branch work |
| `ERP_WARRANTY_GROUPS` | Group codes for warranty / goodwill |
| `APP_BILLABLE_CODES` | App activity codes that count as billable |
| `APP_BREAK_CODES` | App codes removed as breaks |
| `APP_LEAVE_CODES` | App codes removed as leave |
| `STANDARD_DAY_HOURS` | Fallback hours per working day for the calendar denominator (default `7.0`) |
| `BILLING_RATE_EUR` | Rate used to value the recovery gap (default `90.0`) |

### Technician name consistency

The app file uses free-typed names; the ERP file uses IDs mapped to names in code.
Matching ignores word order and accents, so `BOISSEAU Nicolas` and
`NICOLAS BOISSEAU` are recognised as the same person. It cannot match a **partial**
name — `Iban` and `Obando Iban` remain two different people.

**Recommended fix at source:** replace the free-text technician field in the field
app / form with a fixed dropdown of the exact roster. This removes most
reconciliation work permanently.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `FAIL — not recognised` | Wrong export, or renamed headers | Check the missing-columns list in the message against the tables above |
| A technician shows `ID n (unmapped)` | Employee ID missing from `TECH_MAPPING` | Add `n: "NAME"` and restart |
| Duplicate technicians in the exclude list | Different spellings in the app file | Fix the form; use a dropdown |
| Everything shows 0 hours | Times not in `HH:MM:SS`, or dates stored as text | Reformat the source columns |
| Productivity looks impossibly low | Period filter includes weeks with no data — expected hours still accrue | Narrow the Year/Month/Week filter |
| Billable seems too high | You are on v1 — it classified every ERP row as billable | Upgrade to v2 |

---

## Changelog

### v3

- **Attendance denominator.** The timesheet's arrival/departure/worked-hours columns
  (3–7) were present and 100% populated but ignored by every prior version, which
  assumed a flat 7 h day. Productivity is now measured against hours actually paid
  for, selectable in the sidebar.
- **Recovery funnel tab** tracing paid → logged → billable → direct → work-order →
  booked, with the gap valued in euros.
- **Timesheet integrity panel** listing technician-days where activity segments
  exceed declared worked hours. These are overlapping or duplicated entries, not
  overtime — overtime is separately flagged and does not explain them.
- **Idle-time table** per technician: paid attendance covered by no activity segment.
- Duration and category are computed once at load instead of per tab.

### v2

- **Single uploader with auto-detection.** Files are identified by column signature,
  so they can be dropped in any order and cannot land in the wrong slot.
- **Validation panel.** Every file reports OK / CHECK / FAIL with row counts, date
  range, and the exact missing columns when rejected.
- **Fixed ERP classification.** v1 tested `Hour Type` before `Group`, and `Group`
  arrived as a float (`"100.0"`), so the string comparison never matched and *every*
  ERP row was classified as billable. `Group` is now the primary rule, with Internal
  and Warranty as separate categories.
- **Irium footer rows stripped.** v1 turned the trailing summary lines into phantom
  technicians on the chart.
- **Accent- and order-insensitive name matching**, so app names and ERP names line
  up and a single exclusion applies to both files.
- **Breaks and leave separated.** v1 counted paid leave against productivity.
- **New App vs ERP tab** quantifying billable time logged but never booked.
- **Header matching is now tolerant** of accents, case and spacing.
- Removed a duplicate `"EC"` key in `WO_STATUS_MAPPING` that silently overwrote
  `QUOTE ACCEPTED`.

### v1

Initial dashboard: two uploaders, App and ERP tabs, interactive technician
selection on the ERP chart.
