import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# --- MAPPINGS FROM SCREENSHOTS ---
# You can easily add or edit these mappings based on your exact ERP data.

TECH_MAPPING = {
    2: "DILROY SEEBALACK",
    4: "NICOLAS BOISSEAU",
    5: "MICHEL FLORENTINE",
    8: "DITLANE JACOBS",
    11: "NAILI SAMIR",
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
    "EC": "TO INVOICE",
    "AP": "TO INVOICE PARTIALLY",
    "CP": "IN ACCOUNTING",
    "DE": "QUOTE PRINTED",
    "EC": "IN PROGRESS",
    "ED": "DEVIS EDITE",
    "FC": "INVOICED",
    "RE": "QUOTE REFUSED",
    "TE": "DEVIS TERMINE",
    "TP": "FINISHED PARTIALLY",
    "TR": "QUOTE TRANSFERRED TO ORD",
    "TT": "TOTALLY FINISHED",

    # Add other statuses as needed
}

def classify_erp_hours(row):
    """
    Classifies ERP hours into Billable vs Non-Billable based on Hour Type or Group.
    Learned from hour classification screenshot and standard logic.
    """
    hour_type = str(row.get('Hour Type', '')).upper()
    group = str(row.get('Group', ''))
    
    # Group 100, 101, 104 or text containing Main d'oeuvre / Travel are billable
    if 'MAIN D\'OEUVRE' in hour_type or 'TRAVEL' in hour_type or group in ['100', '101', '104']:
        return 'Billable'
    else:
        return 'Non-Billable'

# --- PAGE CONFIG ---
st.set_page_config(page_title="Technician Productivity Dashboard", layout="wide")

st.title("📊 360° Technician Productivity Dashboard")
st.markdown("Compare Self-Reported App Data against Official ERP (IRIUM) Data.")

# --- SIDEBAR: FILE UPLOADS ---
st.sidebar.header("📁 Data Sources")
app_file = st.sidebar.file_uploader("1. Upload App Timesheet", type=["xlsx", "csv"], key="app")
erp_file = st.sidebar.file_uploader("2. Upload ERP Report", type=["xlsx", "csv"], key="erp")

# Initialize DataFrames
app_df = None
erp_df = None
available_years, available_months, available_weeks = set(), set(), set()
available_techs = set()

# --- LOAD DATA & EXTRACT DATES FOR UNIFIED FILTERS ---
with st.spinner("Loading data..."):
    # 1. Load App Data
    if app_file is not None:
        try:
            app_df = pd.read_csv(app_file) if app_file.name.endswith('.csv') else pd.read_excel(app_file, sheet_name=0)
            app_df['Date_Parsed'] = pd.to_datetime(app_df['Date'], errors='coerce')
            app_df['Year'] = app_df['Date_Parsed'].dt.year.fillna(-1).astype(int).astype(str).replace('-1', 'Unknown')
            app_df['Month'] = app_df['Date_Parsed'].dt.month.fillna(-1).astype(int).astype(str).replace('-1', 'Unknown')
            # Fix uint32 out of bounds error by safely casting to Int64 first
            app_df['Week'] = app_df['Date_Parsed'].dt.isocalendar().week.astype('Int64').fillna(-1).astype(str).replace('-1', 'Unknown')
            
            available_years.update(app_df['Year'].unique())
            available_months.update(app_df['Month'].unique())
            available_weeks.update(app_df['Week'].unique())
            available_techs.update(app_df['Technicien'].dropna().unique())
        except Exception as e:
            st.sidebar.error(f"Error loading App data: {e}")

    # 2. Load ERP Data
    if erp_file is not None:
        try:
            erp_df = pd.read_csv(erp_file) if erp_file.name.endswith('.csv') else pd.read_excel(erp_file, sheet_name=0)
            erp_df['Date_Parsed'] = pd.to_datetime(erp_df['Date'], errors='coerce')
            erp_df['Year'] = erp_df['Date_Parsed'].dt.year.fillna(-1).astype(int).astype(str).replace('-1', 'Unknown')
            erp_df['Month'] = erp_df['Date_Parsed'].dt.month.fillna(-1).astype(int).astype(str).replace('-1', 'Unknown')
            # Fix uint32 out of bounds error by safely casting to Int64 first
            erp_df['Week'] = erp_df['Date_Parsed'].dt.isocalendar().week.astype('Int64').fillna(-1).astype(str).replace('-1', 'Unknown')
            
            # Map ERP tech names immediately so we can use them in the global filter
            erp_df['Tech_Name'] = erp_df['Shre Salarie'].map(TECH_MAPPING).fillna(erp_df['Shre Salarie'].astype(str) + " (Unknown Name)")

            available_years.update(erp_df['Year'].unique())
            available_months.update(erp_df['Month'].unique())
            available_weeks.update(erp_df['Week'].unique())
            available_techs.update(erp_df['Tech_Name'].dropna().unique())
        except Exception as e:
            st.sidebar.error(f"Error loading ERP data: {e}")

# --- SIDEBAR: UNIFIED DATE FILTERS ---
st.sidebar.markdown("---")
st.sidebar.header("📅 Global Date Filters")
st.sidebar.markdown("These filters apply to BOTH dashboards.")

year_options = ['Total'] + sorted([y for y in available_years if y != 'Unknown'])
selected_year = st.sidebar.selectbox("Year", year_options)

month_options = ['Total'] + sorted([m for m in available_months if m != 'Unknown'], key=lambda x: int(x))
selected_month = st.sidebar.selectbox("Month", month_options)

week_options = ['Total'] + sorted([w for w in available_weeks if w != 'Unknown'], key=lambda x: int(x))
selected_week = st.sidebar.selectbox("Week", week_options)

st.sidebar.markdown("---")
st.sidebar.header("🧑‍🔧 Technician Filters")
excluded_techs = st.sidebar.multiselect(
    "Exclude Technicians", 
    options=sorted(list(available_techs)),
    help="Select technicians to exclude from calculations (e.g., borrowed from other branches)."
)

# --- MAIN DASHBOARD AREA ---
if app_df is None and erp_df is None:
    st.info("👈 Please upload at least one file from the sidebar to view the dashboard.")
else:
    # Create Tabs
    tab1, tab2 = st.tabs(["📱 Self-Reported Timesheet (App)", "🏢 Official ERP Data (IRIUM)"])

    # ==========================================
    # TAB 1: SELF-REPORTED APP DATA
    # ==========================================
    with tab1:
        if app_df is None:
            st.warning("No App Timesheet uploaded.")
        else:
            # Process App Data
            or_col = [col for col in app_df.columns if 'Numéro OR' in col and 'Main' in col]
            or_col_name = or_col[0] if or_col else None
            
            app_df['Start_Time'] = pd.to_datetime(app_df['Date'].astype(str) + ' ' + app_df['Activité — Début'].astype(str), errors='coerce')
            app_df['End_Time'] = pd.to_datetime(app_df['Date'].astype(str) + ' ' + app_df['Activité — Fin'].astype(str), errors='coerce')
            app_df['Duration_Hours'] = (app_df['End_Time'] - app_df['Start_Time']).dt.total_seconds() / 3600.0
            app_df.loc[app_df['Duration_Hours'] < 0, 'Duration_Hours'] += 24
            app_df['Duration_Hours'] = app_df['Duration_Hours'].fillna(0)

            def categorize_app(row):
                code = str(row.get('Code', '')).strip()
                if code == '100': return 'Break'
                elif code in ['20', '30']: return 'Billable'
                else: return 'Non-Billable'

            app_df['Category'] = app_df.apply(categorize_app, axis=1)

            if or_col_name:
                app_df['Work_Order'] = app_df[or_col_name].fillna('No Work Order').astype(str)
                app_df['Work_Order'] = app_df['Work_Order'].replace(['nan', '', 'None'], 'No Work Order')
            else:
                app_df['Work_Order'] = 'No Work Order'

            # Apply Filters
            filtered_app = app_df.copy()
            if selected_year != 'Total': filtered_app = filtered_app[filtered_app['Year'] == selected_year]
            if selected_month != 'Total': filtered_app = filtered_app[filtered_app['Month'] == selected_month]
            if selected_week != 'Total': filtered_app = filtered_app[filtered_app['Week'] == selected_week]
            if excluded_techs: filtered_app = filtered_app[~filtered_app['Technicien'].isin(excluded_techs)]

            work_app_df = filtered_app[filtered_app['Category'] != 'Break'].copy()

            # Calendar Expected Hours Baseline
            if not app_df['Date_Parsed'].dropna().empty:
                global_min = app_df['Date_Parsed'].min()
                global_max = app_df['Date_Parsed'].max()
                start_date = global_min - pd.to_timedelta(global_min.dayofweek, unit='d')
                end_date = global_max + pd.to_timedelta(6 - global_max.dayofweek, unit='d')
                
                cal_df = pd.DataFrame({'Date': pd.date_range(start=start_date, end=end_date)})
                cal_df['Year'] = cal_df['Date'].dt.year.astype(str)
                cal_df['Month'] = cal_df['Date'].dt.month.astype(str)
                cal_df['Week'] = cal_df['Date'].dt.isocalendar().week.astype('Int64').astype(str)
                cal_df['Is_Weekday'] = cal_df['Date'].dt.dayofweek < 5
                
                if selected_year != 'Total': cal_df = cal_df[cal_df['Year'] == selected_year]
                if selected_month != 'Total': cal_df = cal_df[cal_df['Month'] == selected_month]
                if selected_week != 'Total': cal_df = cal_df[cal_df['Week'] == selected_week]
                
                expected_hours_baseline = float(cal_df['Is_Weekday'].sum() * 7.0)
            else:
                expected_hours_baseline = 0.0

            # Exclude them from the master technician list so they do not show up as 0 hours
            all_techs = [t for t in app_df['Technicien'].dropna().unique() if t not in excluded_techs]
            app_summary = work_app_df.groupby('Technicien').apply(
                lambda x: pd.Series({
                    'Total Logged Hours': x['Duration_Hours'].sum(),
                    'Billable Hours': x.loc[x['Category'] == 'Billable', 'Duration_Hours'].sum(),
                    'Non-Billable Hours': x.loc[x['Category'] == 'Non-Billable', 'Duration_Hours'].sum()
                })
            ).reset_index()
            
            # --- FIX: Ensure columns exist even if the filtered data is completely empty ---
            for col in ['Total Logged Hours', 'Billable Hours', 'Non-Billable Hours']:
                if col not in app_summary.columns:
                    app_summary[col] = 0.0

            app_summary = pd.merge(pd.DataFrame({'Technicien': all_techs}), app_summary, on='Technicien', how='left').fillna(0)
            
            if not app_summary.empty:
                app_summary['Expected Hours'] = expected_hours_baseline
                app_summary['Unreported Hours'] = np.maximum(0, app_summary['Expected Hours'] - app_summary['Total Logged Hours'])
                app_summary['Effective Total Hours'] = app_summary['Total Logged Hours'] + app_summary['Unreported Hours']
                app_summary['Productivity (%)'] = np.where(app_summary['Effective Total Hours'] > 0, (app_summary['Billable Hours'] / app_summary['Effective Total Hours']) * 100, 0)
                app_summary = app_summary.sort_values('Productivity (%)', ascending=False)
            
            # App UI
            st.subheader("🏆 App Data - Overall Team Productivity (Expected vs Logged)")
            total_exp = app_summary['Expected Hours'].sum()
            total_log = app_summary['Total Logged Hours'].sum()
            total_effective = app_summary['Effective Total Hours'].sum() if not app_summary.empty else 0
            bill_hrs = app_summary['Billable Hours'].sum()
            unrep_hrs = app_summary['Unreported Hours'].sum()
            app_prod = (bill_hrs / total_effective * 100) if total_effective > 0 else 0

            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Expected Hours", f"{total_exp:.1f} h")
            c2.metric("Logged Hours", f"{total_log:.1f} h")
            c3.metric("Billable Hours", f"{bill_hrs:.1f} h")
            c4.metric("Unreported Hours", f"{unrep_hrs:.1f} h")
            c5.metric("Team Productivity", f"{app_prod:.1f} %")

            c_chart1, c_chart2 = st.columns(2)
            with c_chart1:
                melted = app_summary.melt(id_vars='Technicien', value_vars=['Billable Hours', 'Non-Billable Hours', 'Unreported Hours'], var_name='Type', value_name='Hours')
                fig_hrs = px.bar(melted, x='Technicien', y='Hours', color='Type', color_discrete_map={'Billable Hours': '#2ca02c', 'Non-Billable Hours': '#d62728', 'Unreported Hours': '#7f7f7f'}, barmode='stack')
                
                # --- FIX: Safe max calculation for empty dataframes ---
                max_logged = app_summary['Total Logged Hours'].max() if not app_summary.empty else 0
                max_logged = 0 if pd.isna(max_logged) else max_logged
                max_y = max(expected_hours_baseline * 1.1, max_logged * 1.1) if expected_hours_baseline > 0 else 40
                
                fig_hrs.update_layout(yaxis=dict(range=[0, max_y]), title="Hours Split by Technician")
                st.plotly_chart(fig_hrs, use_container_width=True)

            with c_chart2:
                fig_prod = px.bar(app_summary, x='Technicien', y='Productivity (%)', text=app_summary['Productivity (%)'].apply(lambda x: f'{x:.1f}%'), color='Productivity (%)', color_continuous_scale='Blues')
                fig_prod.update_traces(textposition='outside')
                fig_prod.update_layout(yaxis=dict(range=[0, max(100, app_summary['Productivity (%)'].max() + 10)]), title="Productivity %")
                st.plotly_chart(fig_prod, use_container_width=True)


    # ==========================================
    # TAB 2: OFFICIAL ERP DATA (IRIUM)
    # ==========================================
    with tab2:
        if erp_df is None:
            st.warning("No ERP Report uploaded.")
        else:
            # Process ERP Data
            filtered_erp = erp_df.copy()
            if selected_year != 'Total': filtered_erp = filtered_erp[filtered_erp['Year'] == selected_year]
            if selected_month != 'Total': filtered_erp = filtered_erp[filtered_erp['Month'] == selected_month]
            if selected_week != 'Total': filtered_erp = filtered_erp[filtered_erp['Week'] == selected_week]
            if excluded_techs: filtered_erp = filtered_erp[~filtered_erp['Tech_Name'].isin(excluded_techs)]

            # Apply Mappings
            filtered_erp['Status_Label'] = filtered_erp['Status'].map(WO_STATUS_MAPPING).fillna(filtered_erp['Status'].astype(str))
            filtered_erp['Category'] = filtered_erp.apply(classify_erp_hours, axis=1)
            
            # Using 'Time carried out' as actual worked hours
            worked_col = 'Time carried out' if 'Time carried out' in filtered_erp.columns else 'Duration'
            filtered_erp[worked_col] = pd.to_numeric(filtered_erp[worked_col], errors='coerce').fillna(0)

            # Calendar Expected Hours Baseline for ERP
            if not erp_df['Date_Parsed'].dropna().empty:
                erp_min = erp_df['Date_Parsed'].min()
                erp_max = erp_df['Date_Parsed'].max()
                erp_start = erp_min - pd.to_timedelta(erp_min.dayofweek, unit='d')
                erp_end = erp_max + pd.to_timedelta(6 - erp_max.dayofweek, unit='d')
                
                cal_erp_df = pd.DataFrame({'Date': pd.date_range(start=erp_start, end=erp_end)})
                cal_erp_df['Year'] = cal_erp_df['Date'].dt.year.astype(str)
                cal_erp_df['Month'] = cal_erp_df['Date'].dt.month.astype(str)
                cal_erp_df['Week'] = cal_erp_df['Date'].dt.isocalendar().week.astype('Int64').astype(str)
                cal_erp_df['Is_Weekday'] = cal_erp_df['Date'].dt.dayofweek < 5
                
                if selected_year != 'Total': cal_erp_df = cal_erp_df[cal_erp_df['Year'] == selected_year]
                if selected_month != 'Total': cal_erp_df = cal_erp_df[cal_erp_df['Month'] == selected_month]
                if selected_week != 'Total': cal_erp_df = cal_erp_df[cal_erp_df['Week'] == selected_week]
                
                erp_expected_hours_baseline = float(cal_erp_df['Is_Weekday'].sum() * 7.0)
            else:
                erp_expected_hours_baseline = 0.0

            # Master list of techs (Mapped techs + any unexpected techs found in the file), minus exclusions
            known_techs = list(TECH_MAPPING.values())
            found_techs = filtered_erp['Tech_Name'].dropna().unique().tolist()
            combined_techs = [t for t in list(set(known_techs + found_techs)) if t not in excluded_techs]
            all_erp_techs = pd.DataFrame({'Tech_Name': combined_techs})

            erp_summary_raw = filtered_erp.groupby('Tech_Name').apply(
                lambda x: pd.Series({
                    'Total Hours Worked': x[worked_col].sum(),
                    'Billable Hours': x.loc[x['Category'] == 'Billable', worked_col].sum(),
                    'Non-Billable Hours': x.loc[x['Category'] == 'Non-Billable', worked_col].sum()
                })
            ).reset_index()

            # --- FIX: Ensure columns exist even if the filtered data is completely empty ---
            for col in ['Total Hours Worked', 'Billable Hours', 'Non-Billable Hours']:
                if col not in erp_summary_raw.columns:
                    erp_summary_raw[col] = 0.0

            # Merge to ensure techs who logged 0 hours appear
            erp_summary = pd.merge(all_erp_techs, erp_summary_raw, on='Tech_Name', how='left').fillna(0)

            # Assign Expected and Unreported Hours
            erp_summary['Expected Hours'] = erp_expected_hours_baseline
            erp_summary['Unreported Hours'] = np.maximum(0, erp_summary['Expected Hours'] - erp_summary['Total Hours Worked'])
            erp_summary['Effective Total Hours'] = erp_summary['Total Hours Worked'] + erp_summary['Unreported Hours']

            # --- CUSTOM PRODUCTIVITY CALCULATION (Adapted from PDF) ---
            # Formula adapted: Billable Hours / (Total Hours Worked + Unreported Hours)
            erp_summary['Productivity (%)'] = np.where(
                erp_summary['Effective Total Hours'] > 0,
                (erp_summary['Billable Hours'] / erp_summary['Effective Total Hours']) * 100,
                0
            )
            erp_summary = erp_summary.sort_values('Productivity (%)', ascending=False)

            st.subheader("🏆 ERP Data - Adjusted Productivity (Includes Unreported)")
            st.caption("ℹ️ *Note: To address under-reporting, the official PDF formula has been adapted. Unreported hours are effectively treated as non-billable time. Productivity = Billable Hours / (Logged Hours + Unreported Hours). Overtime increases the total hours for the day.*")
            
            erp_total_worked = erp_summary['Total Hours Worked'].sum()
            erp_total_expected = erp_summary['Expected Hours'].sum()
            erp_total_effective = erp_summary['Effective Total Hours'].sum()
            erp_billable = erp_summary['Billable Hours'].sum()
            erp_non_billable = erp_summary['Non-Billable Hours'].sum()
            erp_unreported = erp_summary['Unreported Hours'].sum()
            erp_team_prod = (erp_billable / erp_total_effective * 100) if erp_total_effective > 0 else 0

            ec1, ec2, ec3, ec4, ec5, ec6 = st.columns(6)
            ec1.metric("Expected Hours", f"{erp_total_expected:.1f} h")
            ec2.metric("Hours Worked (ERP)", f"{erp_total_worked:.1f} h")
            ec3.metric("Billable (ERP)", f"{erp_billable:.1f} h")
            ec4.metric("Non-Billable (ERP)", f"{erp_non_billable:.1f} h")
            ec5.metric("Unreported", f"{erp_unreported:.1f} h")
            ec6.metric("ERP Team Prod", f"{erp_team_prod:.1f} %")

            ec_chart1, ec_chart2 = st.columns(2)
            with ec_chart1:
                erp_melted = erp_summary.melt(id_vars='Tech_Name', value_vars=['Billable Hours', 'Non-Billable Hours', 'Unreported Hours'], var_name='Type', value_name='Hours')
                fig_erp_hrs = px.bar(erp_melted, x='Tech_Name', y='Hours', color='Type', color_discrete_map={'Billable Hours': '#2ca02c', 'Non-Billable Hours': '#d62728', 'Unreported Hours': '#7f7f7f'}, barmode='stack')
                
                # --- FIX: Safe max calculation for empty dataframes ---
                max_worked = erp_summary['Total Hours Worked'].max() if not erp_summary.empty else 0
                max_worked = 0 if pd.isna(max_worked) else max_worked
                max_y_erp = max(erp_expected_hours_baseline * 1.1, max_worked * 1.1) if erp_expected_hours_baseline > 0 else 40
                
                fig_erp_hrs.update_layout(yaxis=dict(range=[0, max_y_erp]), title="Logged ERP Hours Split")
                st.plotly_chart(fig_erp_hrs, use_container_width=True)

            with ec_chart2:
                fig_erp_prod = px.bar(erp_summary, x='Tech_Name', y='Productivity (%)', text=erp_summary['Productivity (%)'].apply(lambda x: f'{x:.1f}%'), color='Productivity (%)', color_continuous_scale='Greens')
                fig_erp_prod.update_traces(textposition='outside')
                fig_erp_prod.update_layout(yaxis=dict(range=[0, max(100, erp_summary['Productivity (%)'].max() + 10)]), title="Official ERP Productivity %")
                st.plotly_chart(fig_erp_prod, use_container_width=True)

            # Detailed ERP Data Table
            st.markdown("---")
            st.subheader("📋 ERP Work Order Details")
            wo_erp_summary = filtered_erp.groupby(['WO No.', 'Status_Label', 'Category'])[worked_col].sum().reset_index()
            
            # --- FIX: Use pivot_table instead of pivot to prevent duplicate/unhashable list errors ---
            if not wo_erp_summary.empty:
                wo_erp_pivot = wo_erp_summary.pivot_table(index=['WO No.', 'Status_Label'], columns='Category', values=worked_col, aggfunc='sum').fillna(0).reset_index()
            else:
                wo_erp_pivot = pd.DataFrame(columns=['WO No.', 'Status_Label', 'Billable', 'Non-Billable'])
            
            for col in ['Billable', 'Non-Billable']:
                if col not in wo_erp_pivot.columns: wo_erp_pivot[col] = 0
                
            wo_erp_pivot['Total Hours'] = wo_erp_pivot['Billable'] + wo_erp_pivot['Non-Billable']
            wo_erp_pivot = wo_erp_pivot.sort_values(by='Total Hours', ascending=False)
            
            st.dataframe(wo_erp_pivot.style.format({'Billable': '{:.2f}', 'Non-Billable': '{:.2f}', 'Total Hours': '{:.2f}'}), use_container_width=True)
