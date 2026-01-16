import os, io, time, requests
import pandas as pd
import streamlit as st
import altair as alt
import pydeck as pdk

st.set_page_config(page_title="CRM Dashboard — ORS Geocode (Location→lat/lon)", layout="wide", page_icon="🗺️")

with open("styles.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

st.markdown("<div class='glass'><h1>🗺️ CRM — Geocode Location to Lat/Lon (ORS)</h1></div>", unsafe_allow_html=True)

LAT, LON = 'lat', 'lon'
REMARKS = 'Remarks'
ORS_API_KEY = st.secrets.get('ORS_API_KEY', '')  # put in .streamlit/secrets.toml

@st.cache_data(show_spinner=False)
def load_csv(uploaded):
    df = pd.read_csv(uploaded)
    df.columns = [str(c).strip() for c in df.columns]
    if REMARKS not in df.columns:
        df[REMARKS] = ''
    return df

# Geocode one location string -> (lat, lon)
def ors_geocode_location(q: str, api_key: str, country_bias: str|None=None):
    try:
        url = 'https://api.openrouteservice.org/geocode/search'
        params = {'api_key': api_key, 'text': q}
        if country_bias:
            params['boundary.country'] = country_bias
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return None, None
        feats = (r.json() or {}).get('features') or []
        if not feats:
            return None, None
        lon, lat = feats[0]['geometry']['coordinates']
        return lat, lon
    except Exception:
        return None, None

# ---- Sidebar ----
with st.sidebar:
    st.header('📁 Upload & Options')
    file = st.file_uploader('Upload CSV', type=['csv'])
    st.caption('CSV should include a **Location** column. This app will fetch **lat/lon** using ORS for each Location.')
    country_bias = st.text_input('Country bias (optional, e.g., IN, USA, DE)', value='')
    rate_ms = st.slider('Rate limit per geocode (ms)', 100, 1500, 300, 50)
    auto_run = st.checkbox('Auto-geocode on upload if lat/lon missing', value=True)

if not file:
    st.info('Upload a CSV to begin')
    st.stop()

if 'df_base' not in st.session_state or st.session_state.get('file_name') != file.name:
    st.session_state.df_base = load_csv(file)
    st.session_state.file_name = file.name

base = st.session_state.df_base.copy()

if 'Location' not in base.columns:
    st.error("CSV must contain a 'Location' column to geocode.")
    st.stop()

# Ensure lat/lon columns exist
if LAT not in base.columns: base[LAT] = None
if LON not in base.columns: base[LON] = None

# Determine rows needing geocode (missing or non-numeric)
lat_num = pd.to_numeric(base[LAT], errors='coerce')
lon_num = pd.to_numeric(base[LON], errors='coerce')
need = lat_num.isna() | lon_num.isna()

# Geocode button (or auto)
run_geo = False
if auto_run and need.any() and ORS_API_KEY:
    run_geo = True

if st.button('⚡ Geocode Location → lat/lon (ORS)'):
    run_geo = True

if run_geo:
    if not ORS_API_KEY:
        st.error('Missing ORS_API_KEY. Add it to .streamlit/secrets.toml')
    else:
        to_do = base[need].copy()
        total = len(to_do)
        if total == 0:
            st.success('All rows already have coordinates.')
        else:
            prog = st.progress(0, text='Geocoding…')
            for i,(idx,row) in enumerate(to_do.iterrows(), start=1):
                q = str(row['Location'])
                lat, lon = ors_geocode_location(q, ORS_API_KEY, country_bias.strip() or None)
                if lat is not None and lon is not None:
                    base.at[idx, LAT] = lat
                    base.at[idx, LON] = lon
                time.sleep(rate_ms/1000)
                prog.progress(i/total, text=f'Geocoding {i}/{total}')
            prog.empty()
            st.session_state.df_base = base
            st.success('Geocoding complete. Map & CSV updated!')
            try:
                st.rerun()
            except Exception:
                pass

# KPIs
st.markdown("<div class='glass metric-card'>", unsafe_allow_html=True)
k1,k2,k3,k4 = st.columns(4)
with k1: st.metric('Records', len(base))
with k2: st.metric('Unique Locations', base['Location'].nunique())
with k3: st.metric('lat filled', base[LAT].notna().sum())
with k4: st.metric('lon filled', base[LON].notna().sum())
st.markdown("</div>", unsafe_allow_html=True)

# Map (with Customer + Location tooltip if available)
st.markdown("<div class='glass'><h4>🗺️ Map</h4>", unsafe_allow_html=True)
map_df = base.dropna(subset=[LAT,LON]).copy()
if not map_df.empty:
    # Status-based color if provided
    def status_color(s):
        s=str(s).lower()
        if 'received' in s: return [80,200,120]
        if 'hold' in s: return [255,150,0]
        if 'fund' in s: return [255,90,90]
        return [120,200,255]
    map_df['__color__'] = map_df['Current Status'].apply(status_color) if 'Current Status' in map_df.columns else [120,200,255]

    if 'Customer' in map_df.columns and 'Location' in map_df.columns:
        tooltip = {"text": "{Customer}\n{Location}"}
    elif 'Location' in map_df.columns:
        tooltip = {"text": "{Location}"}
    else:
        tooltip = {"text": "Point"}

    layer = pdk.Layer('ScatterplotLayer', map_df,
                      get_position=[LON,LAT], get_radius=60000,
                      get_color='__color__', pickable=True)
    view = pdk.ViewState(latitude=float(pd.to_numeric(map_df[LAT]).mean()),
                         longitude=float(pd.to_numeric(map_df[LON]).mean()), zoom=4)
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, map_style='dark', tooltip=tooltip))
else:
    st.info('No points yet. Click the geocode button above to populate lat/lon from Location.')

st.markdown("</div>", unsafe_allow_html=True)

# Simple charts (optional): top locations
st.markdown("<div class='glass'><h4>Top Locations</h4>", unsafe_allow_html=True)
vc = base['Location'].astype(str).value_counts().reset_index()
if not vc.empty:
    vc.columns = ['Location','Count']
    chart = alt.Chart(vc.head(15)).mark_bar(color='#7aa2ff').encode(x=alt.X('Count:Q'), y=alt.Y('Location:N', sort='-x'))
    st.altair_chart(chart, use_container_width=True)
else:
    st.info('No Location values to chart.')

st.markdown("</div>", unsafe_allow_html=True)

# Data editor & download
st.markdown("<div class='glass'><h4>✏️ Edit Data / Remarks</h4>", unsafe_allow_html=True)
edited = st.data_editor(base, num_rows='dynamic', use_container_width=True, height=380)

buff = io.StringIO(); edited.to_csv(buff, index=False)
st.download_button('⬇️ Download Updated CSV', buff.getvalue(), file_name='updated_'+st.session_state.file_name, mime='text/csv')

st.markdown("</div>", unsafe_allow_html=True)
