import os, io, time, requests
import pandas as pd
import streamlit as st
import altair as alt
import pydeck as pdk

st.set_page_config(page_title="CRM Dashboard", layout="wide")

with open("styles.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

st.markdown("<div class='glass'><h1>CRM Dashboard</h1></div>", unsafe_allow_html=True)

ORS_API_KEY = st.secrets.get("ORS_API_KEY", "")
LAT, LON = 'lat','lon'
REMARKS = 'Remarks'

@st.cache_data(show_spinner=False)
def load_csv(f):
    df = pd.read_csv(f)
    if REMARKS not in df.columns: df[REMARKS] = ''
    return df

file = st.sidebar.file_uploader("Upload CSV", type=["csv"])
if not file:
    st.stop()

df = load_csv(file)
filtered = df.copy()

for col in ['Customer','Location','Package','Application']:
    if col in filtered.columns:
        sel = st.sidebar.multiselect(col, sorted(filtered[col].dropna().unique()))
        if sel:
            filtered = filtered[filtered[col].isin(sel)]

k1,k2,k3,k4 = st.columns(4)
k1.metric("Records", len(filtered))
k2.metric("Customers", filtered['Customer'].nunique() if 'Customer' in filtered else '-')
k3.metric("Packages", filtered['Package'].nunique() if 'Package' in filtered else '-')
k4.metric("Total Qty", int(filtered['Qty'].sum()) if 'Qty' in filtered else '-')

if 'Customer' in filtered:
    chart = alt.Chart(filtered['Customer'].value_counts().reset_index().rename(columns={'index':'Customer','Customer':'Count'})).mark_bar().encode(x='Count', y=alt.Y('Customer', sort='-x'))
    st.altair_chart(chart, use_container_width=True)

if {LAT,LON}.issubset(filtered.columns):
    mdf = filtered.dropna(subset=[LAT,LON])
    if not mdf.empty:
        st.pydeck_chart(pdk.Deck(
            layers=[pdk.Layer('ScatterplotLayer', mdf, get_position=[LON,LAT], get_radius=60000)],
            initial_view_state=pdk.ViewState(latitude=mdf[LAT].mean(), longitude=mdf[LON].mean(), zoom=4)
        ))

st.markdown("### Edit Data")
edited = st.data_editor(filtered, num_rows='dynamic', use_container_width=True)

buf = io.StringIO(); edited.to_csv(buf, index=False)
st.download_button("Download CSV", buf.getvalue(), file_name="updated.csv", mime="text/csv")
