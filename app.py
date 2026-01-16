import os, io
import pandas as pd
import streamlit as st
import altair as alt
import pydeck as pdk

st.set_page_config(page_title='CRM Dashboard', layout='wide', page_icon='📊')

with open('styles.css') as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

st.markdown("<div class='glass'><h1>📊 CRM Dashboard</h1></div>", unsafe_allow_html=True)

LAT, LON = 'lat', 'lon'
REMARKS = 'Remarks'

@st.cache_data(show_spinner=False)
def load_csv(uploaded):
    df = pd.read_csv(uploaded)
    df.columns = [str(c).strip() for c in df.columns]
    if REMARKS not in df.columns:
        df[REMARKS] = ''
    return df

# Sidebar upload
file = st.sidebar.file_uploader('Upload CSV', type=['csv'])
if not file:
    st.info('Upload a CSV to start')
    st.stop()

df = load_csv(file)
filtered = df.copy()

# Cascading filters
for col in ['Customer','Location','Package','Application']:
    if col in filtered.columns:
        options = sorted(filtered[col].dropna().astype(str).unique())
        sel = st.sidebar.multiselect(col, options)
        if sel:
            filtered = filtered[filtered[col].astype(str).isin(sel)]

# KPIs
k1,k2,k3,k4 = st.columns(4)
k1.metric('Records', len(filtered))
k2.metric('Customers', filtered['Customer'].nunique() if 'Customer' in filtered else '—')
k3.metric('Packages', filtered['Package'].nunique() if 'Package' in filtered else '—')
k4.metric('Total Qty', int(pd.to_numeric(filtered.get('Qty', pd.Series(dtype=float)), errors='coerce').fillna(0).sum()) if 'Qty' in filtered else '—')

# Charts (Altair v6-safe: pass DataFrame, set types explicitly)
if 'Customer' in filtered:
    top_cust = (filtered['Customer'].astype(str)
                .value_counts()
                .reset_index()
                .rename(columns={'index':'Customer','Customer':'Count'}))
    chart_cust = (alt.Chart(top_cust)
        .mark_bar(color='#7aa2ff')
        .encode(
            x=alt.X('Count:Q', title='Count'),
            y=alt.Y('Customer:N', sort='-x', title='Customer'),
            tooltip=[alt.Tooltip('Customer:N'), alt.Tooltip('Count:Q')]
        )
        .properties(height=300))
    st.altair_chart(chart_cust, use_container_width=True)

if 'Package' in filtered:
    top_pack = (filtered['Package'].astype(str)
                .value_counts()
                .reset_index()
                .rename(columns={'index':'Package','Package':'Count'}))
    chart_pack = (alt.Chart(top_pack)
        .mark_bar(color='#9fe6a0')
        .encode(
            x=alt.X('Count:Q', title='Count'),
            y=alt.Y('Package:N', sort='-x', title='Package'),
            tooltip=[alt.Tooltip('Package:N'), alt.Tooltip('Count:Q')]
        )
        .properties(height=300))
    st.altair_chart(chart_pack, use_container_width=True)

# Map
if set([LAT,LON]).issubset(filtered.columns):
    mdf = filtered.dropna(subset=[LAT,LON])
    if not mdf.empty:
        layer = pdk.Layer('ScatterplotLayer', mdf,
                          get_position=[LON,LAT],
                          get_radius=60000,
                          get_color=[120,200,255],
                          pickable=True)
        view = pdk.ViewState(latitude=float(mdf[LAT].mean()),
                             longitude=float(mdf[LON].mean()),
                             zoom=4)
        deck = pdk.Deck(layers=[layer], initial_view_state=view, map_style='dark')
        st.pydeck_chart(deck)

# Editor
st.markdown('### ✏️ Edit Data / Remarks')
edited = st.data_editor(filtered, num_rows='dynamic', use_container_width=True)

# Download
buf = io.StringIO()
edited.to_csv(buf, index=False)
st.download_button('⬇️ Download Updated CSV', buf.getvalue(), file_name='updated_'+file.name, mime='text/csv')
