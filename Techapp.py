import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px

# Set page configuration
st.set_page_config(page_title="Technician Productivity Dashboard", layout="wide")

st.title("📊 Technician Productivity Dashboard")
st.markdown("Upload your daily timesheet export (Excel or CSV) to analyze hours and productivity.")

# File Uploader
uploaded_file = st.file_uploader("Upload Timesheet", type=["xlsx", "csv"])

if uploaded_file is not None:
    # Load Data
    try:
        if uploaded_file.name.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
        else:
            df = pd.read_excel(uploaded_file, sheet_name=0)
            
        st.success("File uploaded successfully!")
    except Exception as e:
        st.error(f"Error loading file: {e}")
        st.stop()

    # Data Processing
    with st.spinner('Processing data...'):
        # 1. Standardize column names dynamically in case of slight changes
        or_col = [col for col in df.columns if 'Numéro OR' in col and 'Main' in col]
        or_col_name = or_col[0] if or_col else None
        
        # 2. Calculate Durations
        # Combine 'Date' with Activity Start and End times
        df['Start_Time'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Activité — Début'].astype(str), errors='coerce')
        df['End_Time'] = pd.to_datetime(df['Date'].astype(str) + ' ' + df['Activité — Fin'].astype(str), errors='coerce')
        
        # Calculate duration in hours
        df['Duration_Hours'] = (df['End_Time'] - df['Start_Time']).dt.total_seconds() / 3600.0
        
        # Handle negative durations (e.g., if a task goes past midnight)
        df.loc[df['Duration_Hours'] < 0, 'Duration_Hours'] += 24
        df['Duration_Hours'] = df['Duration_Hours'].fillna(0)

        # 3. Categorize Activities
        def categorize(row):
            code = str(row.get('Code', '')).strip()
            if code == '100':
                return 'Break'
            elif code == '20':
                return 'Billable'
            else:
                return 'Non-Billable'

        df['Category'] = df.apply(categorize, axis=1)

        # 4. Handle Work Orders
        if or_col_name:
            df['Work_Order'] = df[or_col_name].fillna('No Work Order').astype(str)
            # Catch string representations of nan/empty
            df['Work_Order'] = df['Work_Order'].replace(['nan', '', 'None'], 'No Work Order')
        else:
            df['Work_Order'] = 'No Work Order'

        # 5. Extract Date components for filtering
        df['Date_Parsed'] = pd.to_datetime(df['Date'], errors='coerce')
        df['Year'] = df['Date_Parsed'].dt.year.fillna(-1).astype(int).astype(str).replace('-1', 'Unknown')
        df['Month'] = df['Date_Parsed'].dt.month.fillna(-1).astype(int).astype(str).replace('-1', 'Unknown')
        df['Week'] = df['Date_Parsed'].dt.isocalendar().week.fillna(-1).astype(int).astype(str).replace('-1', 'Unknown')

    # --- SIDEBAR FILTERS ---
    st.sidebar.header("📅 Date Filters")
    st.sidebar.markdown("Keep as **Total** to view all records.")
    
    year_options = ['Total'] + sorted([y for y in df['Year'].unique() if y != 'Unknown'])
    selected_year = st.sidebar.selectbox("Year", year_options)
    
    month_options = ['Total'] + sorted([m for m in df['Month'].unique() if m != 'Unknown'], key=lambda x: int(x))
    selected_month = st.sidebar.selectbox("Month", month_options)
    
    week_options = ['Total'] + sorted([w for w in df['Week'].unique() if w != 'Unknown'], key=lambda x: int(x))
    selected_week = st.sidebar.selectbox("Week", week_options)

    # Apply Date Filters
    filtered_df = df.copy()
    if selected_year != 'Total':
        filtered_df = filtered_df[filtered_df['Year'] == selected_year]
    if selected_month != 'Total':
        filtered_df = filtered_df[filtered_df['Month'] == selected_month]
    if selected_week != 'Total':
        filtered_df = filtered_df[filtered_df['Week'] == selected_week]

    # Filter out breaks to calculate pure working/productive hours from the filtered data
    work_df = filtered_df[filtered_df['Category'] != 'Break'].copy()

    # --- DASHBOARD UI ---
    st.markdown("---")
    
    # KPIs: Overall Team Metrics
    st.header("🏆 Overall Team Productivity")
    total_hours = work_df['Duration_Hours'].sum()
    billable_hours = work_df[work_df['Category'] == 'Billable']['Duration_Hours'].sum()
    non_billable_hours = work_df[work_df['Category'] == 'Non-Billable']['Duration_Hours'].sum()
    
    team_productivity = (billable_hours / total_hours * 100) if total_hours > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Worked Hours", f"{total_hours:.1f} h")
    col2.metric("Billable Hours", f"{billable_hours:.1f} h")
    col3.metric("Non-Billable Hours", f"{non_billable_hours:.1f} h")
    col4.metric("Team Productivity", f"{team_productivity:.1f} %")

    st.markdown("---")

    # Row 1: Technician Analysis
    st.header("🧑‍🔧 Analysis by Technician")
    
    # Aggregate data by Technician
    tech_summary = work_df.groupby('Technicien').apply(
        lambda x: pd.Series({
            'Total Hours': x['Duration_Hours'].sum(),
            'Billable Hours': x.loc[x['Category'] == 'Billable', 'Duration_Hours'].sum(),
            'Non-Billable Hours': x.loc[x['Category'] == 'Non-Billable', 'Duration_Hours'].sum()
        })
    ).reset_index()
    
    tech_summary['Productivity (%)'] = np.where(
        tech_summary['Total Hours'] > 0,
        (tech_summary['Billable Hours'] / tech_summary['Total Hours']) * 100,
        0
    )
    
    # Sort for better visualization
    tech_summary = tech_summary.sort_values('Productivity (%)', ascending=False)

    col_chart1, col_chart2 = st.columns(2)

    with col_chart1:
        st.subheader("Hours Split by Technician")
        # Melt the dataframe for plotting stacked bars
        melted_tech = tech_summary.melt(id_vars='Technicien', value_vars=['Billable Hours', 'Non-Billable Hours'], 
                                        var_name='Hour Type', value_name='Hours')
        fig_hours = px.bar(melted_tech, x='Technicien', y='Hours', color='Hour Type',
                           color_discrete_map={'Billable Hours': '#2ca02c', 'Non-Billable Hours': '#d62728'},
                           barmode='stack')
        st.plotly_chart(fig_hours, use_container_width=True)

    with col_chart2:
        st.subheader("Productivity % by Technician")
        fig_prod = px.bar(tech_summary, x='Technicien', y='Productivity (%)', 
                          text=tech_summary['Productivity (%)'].apply(lambda x: f'{x:.1f}%'),
                          color='Productivity (%)', color_continuous_scale='Blues')
        fig_prod.update_traces(textposition='outside')
        fig_prod.update_layout(yaxis=dict(range=[0, max(100, tech_summary['Productivity (%)'].max() + 10)]))
        st.plotly_chart(fig_prod, use_container_width=True)

    # Show data table
    with st.expander("View Detailed Technician Data"):
        st.dataframe(tech_summary.style.format({
            'Total Hours': '{:.2f}', 'Billable Hours': '{:.2f}', 
            'Non-Billable Hours': '{:.2f}', 'Productivity (%)': '{:.2f}%'
        }))

    st.markdown("---")

    # Row 2: Work Order Analysis
    st.header("📋 Analysis by Work Order (OR)")
    
    # Aggregate data by Work Order for Billable Hours only (or all hours based on requirement, showing all here)
    wo_summary = filtered_df.groupby(['Work_Order', 'Category'])['Duration_Hours'].sum().reset_index()
    
    # Pivot to make it easier to read
    wo_pivot = wo_summary.pivot(index='Work_Order', columns='Category', values='Duration_Hours').fillna(0).reset_index()
    
    # Ensure columns exist even if no data matches
    for col in ['Billable', 'Non-Billable', 'Break']:
        if col not in wo_pivot.columns:
            wo_pivot[col] = 0

    wo_pivot['Total Hours'] = wo_pivot['Billable'] + wo_pivot['Non-Billable'] + wo_pivot['Break']
    wo_pivot = wo_pivot.sort_values(by='Total Hours', ascending=False)

    col_wo1, col_wo2 = st.columns([2, 1])

    with col_wo1:
        st.subheader("Hours Logged per Work Order")
        # Exclude "No Work Order" if you want to focus purely on active orders, but user asked to see it.
        fig_wo = px.bar(wo_pivot.head(15), x='Work_Order', y=['Billable', 'Non-Billable', 'Break'],
                        title="Top 15 Work Orders by Total Hours",
                        color_discrete_map={'Billable': '#2ca02c', 'Non-Billable': '#d62728', 'Break': '#7f7f7f'})
        fig_wo.update_layout(xaxis_title="Work Order", yaxis_title="Hours", barmode='stack')
        st.plotly_chart(fig_wo, use_container_width=True)

    with col_wo2:
        st.subheader("Data Table")
        st.dataframe(wo_pivot[['Work_Order', 'Billable', 'Non-Billable', 'Total Hours']].head(15).style.format({
            'Billable': '{:.2f}', 'Non-Billable': '{:.2f}', 'Total Hours': '{:.2f}'
        }))

else:
    # Instructions to show when no file is uploaded
    st.info("Please upload an Excel (.xlsx) or CSV file containing the timesheet to view the dashboard.")
