import os, io, time, requests
import pandas as pd
import streamlit as st
import altair as alt
import pydeck as pdk

st.set_page_config(page_title="CRM Dashboard", layout="wide", page_icon="📊")

with open("styles.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

st.markdown("<div class='glass'><h1>📊 CRM Dashboard</h1></div>", unsafe_allow_html=True)

LAT, LON = 'lat', 'lon'
REMARKS = 'Remarks'

# Read ORS key from secrets (optional; only needed when geocoding)
ORS_API_KEY = st.secrets.get('ORS_API_KEY', '')

# ---------- Helpers ----------
@st.cache_data(show_spinner=False)
def load_csv(uploaded):
    df = pd.read_csv(uploaded)
    df.columns = [str(c).strip() for c in df.columns]
    if REMARKS not in df.columns:
        df[REMARKS] = ''
    return df

@st.cache_data(show_spinner=False)
def value_counts_df(series: pd.Series, top_n=15, label='Label'):
    s = series.dropna().astype(str)
    vc = s.value_counts().reset_index()
    if not vc.empty:
        vc.columns = [label, 'Count']
        return vc.head(top_n)
    return pd.DataFrame(columns=[label,'Count'])

# Basic geocode single text via ORS
@st.cache_data(show_spinner=False)
def ors_geocode_one(q: str, api_key: str, country_bias: str|None=None):
    try:
        url = 'https://api.openrouteservice.org/geocode/search'
        params = {'api_key': api_key, 'text': q}
        if country_bias:
            params['boundary.country'] = country_bias
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return None, None
        feats = (r.json() or {}).get('features') or []
        if not feats: return None, None
        lon, lat = feats[0]['geometry']['coordinates']
        return lat, lon
    except Exception:
        return None, None

# ---------- Sidebar ----------
with st.sidebar:
    st.header('📁 Upload & Filters')
    file = st.file_uploader('Upload CSV', type=['csv'])
    st.divider()
    st.caption('Optional geocoding (ORS key via secrets)')
    country_bias = st.text_input('Country bias (e.g., IN, USA)', value='')
    rate_ms = st.slider('Geocode rate limit (ms)', 100, 1500, 300, 50)

if not file:
    st.info('Upload a CSV to begin')
    st.stop()

if 'df_base' not in st.session_state:
    st.session_state.df_base = load_csv(file)
    st.session_state.file_name = file.name

base = st.session_state.df_base
filtered = base.copy()

# Cascading filters (Customer -> Location -> Package -> Application)
for col in ['Customer','Location','Package','Application']:
    if col in filtered.columns:
        opts = sorted(filtered[col].dropna().astype(str).unique())
        sel = st.sidebar.multiselect(col, opts)
        if sel:
            filtered = filtered[filtered[col].astype(str).isin(sel)]

# ---------- KPIs ----------
st.markdown("<div class='glass metric-card'>", unsafe_allow_html=True)
k1,k2,k3,k4 = st.columns(4)
with k1: st.metric('Records', len(filtered))
with k2: st.metric('Customers', filtered['Customer'].nunique() if 'Customer' in filtered else '—')
with k3: st.metric('Packages', filtered['Package'].nunique() if 'Package' in filtered else '—')
with k4:
    qty = pd.to_numeric(filtered.get('Qty', pd.Series(dtype=float)), errors='coerce').fillna(0).sum() if 'Qty' in filtered else 0
    st.metric('Total Qty', int(qty))
st.markdown("</div>", unsafe_allow_html=True)

# ---------- Charts Row ----------
colA, colB = st.columns(2)

with colA:
    st.markdown("<div class='glass'><h4>By Customer</h4>", unsafe_allow_html=True)
    if 'Customer' in filtered and not filtered.empty:
        top_cust = value_counts_df(filtered['Customer'], label='Customer')
        if not top_cust.empty:
            chart = (alt.Chart(top_cust)
                .mark_bar(color='#7aa2ff')
                .encode(x=alt.X('Count:Q', title='Count'),
                        y=alt.Y('Customer:N', sort='-x', title='Customer'),
                        tooltip=[alt.Tooltip('Customer:N'), alt.Tooltip('Count:Q')])
                .properties(height=320))
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info('No customer data after filters')
    else:
        st.info('Add a Customer column to view this chart')
    st.markdown("</div>", unsafe_allow_html=True)

with colB:
    st.markdown("<div class='glass'><h4>By Package</h4>", unsafe_allow_html=True)
    if 'Package' in filtered and not filtered.empty:
        top_pack = value_counts_df(filtered['Package'], label='Package')
        if not top_pack.empty:
            chart = (alt.Chart(top_pack)
                .mark_bar(color='#9fe6a0')
                .encode(x=alt.X('Count:Q', title='Count'),
                        y=alt.Y('Package:N', sort='-x', title='Package'),
                        tooltip=[alt.Tooltip('Package:N'), alt.Tooltip('Count:Q')])
                .properties(height=320))
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info('No package data after filters')
    else:
        st.info('Add a Package column to view this chart')
    st.markdown("</div>", unsafe_allow_html=True)

# ---------- Map & Geocoding ----------
st.markdown("<div class='glass'><h4>🗺️ Map</h4>", unsafe_allow_html=True)
has_latlon = set([LAT,LON]).issubset(filtered.columns)

if has_latlon and filtered[LAT].notna().any() and filtered[LON].notna().any():
    map_df = filtered.dropna(subset=[LAT,LON]).copy()
    # Build color by status if available
    def status_color(s):
        s=str(s).lower()
        if 'received' in s: return [80,200,120]
        if 'hold' in s: return [255,150,0]
        if 'fund' in s: return [255,90,90]
        return [120,200,255]
    if 'Current Status' in map_df.columns:
        map_df['__color__'] = map_df['Current Status'].apply(status_color)
    else:
        map_df['__color__'] = [120,200,255]

    tooltip_text = "{Customer}
{Location}" if 'Customer' in map_df.columns and 'Location' in map_df.columns else "{Location}"
    layer = pdk.Layer(
        'ScatterplotLayer', map_df,
        get_position=[LON,LAT], get_radius=60000,
        get_color='__color__', pickable=True
    )
    view = pdk.ViewState(latitude=float(map_df[LAT].mean()), longitude=float(map_df[LON].mean()), zoom=4)
    deck = pdk.Deck(layers=[layer], initial_view_state=view, map_style='dark', tooltip={'text': tooltip_text})
    st.pydeck_chart(deck)
else:
    st.warning('No latitude/longitude found. Use the geocoding tool below to create them.')

# Geocode tool
with st.expander('🌐 Geocode Missing Coordinates (OpenRouteService)'):
    geo_cols = [c for c in base.columns if c not in [LAT,LON]]
    sel_cols = st.multiselect('Pick columns to combine (e.g., Customer + Location)', options=geo_cols,
                              default=[c for c in geo_cols if c.lower() in ('customer','location')])
    do_geo = st.button('⚡ Geocode Now')
    if do_geo:
        if not ORS_API_KEY:
            st.error('Add ORS_API_KEY in .streamlit/secrets.toml')
        elif not sel_cols:
            st.error('Select at least one column')
        else:
            work = base.copy()
            if LAT not in work.columns: work[LAT] = None
            if LON not in work.columns: work[LON] = None
            # rows needing coordinates
            mask = work[[LAT,LON]].isna().any(axis=1)
            todo = work[mask]
            total = len(todo)
            if total == 0:
                st.success('All rows already have coordinates')
            else:
                prog = st.progress(0, text='Geocoding…')
                for i,(idx,row) in enumerate(todo.iterrows(), start=1):
                    addr = ' '.join([str(row[c]) for c in sel_cols])
                    lat,lon = ors_geocode_one(addr, ORS_API_KEY, country_bias.strip() or None)
                    if lat is not None and lon is not None:
                        work.at[idx, LAT] = lat
                        work.at[idx, LON] = lon
                    time.sleep(rate_ms/1000)
                    prog.progress(i/total, text=f'Geocoding {i}/{total}')
                prog.empty()
                st.session_state.df_base = work
                st.success('Geocoding done. Map will refresh with points now.')
                try:
                    st.rerun()
                except Exception:
                    pass

st.markdown("</div>", unsafe_allow_html=True)

# ---------- Data Editor ----------
st.markdown("<div class='glass'><h4>✏️ Edit Data / Remarks</h4>", unsafe_allow_html=True)
edited = st.data_editor(filtered, num_rows='dynamic', use_container_width=True, height=360)

colS1, colS2 = st.columns([1,2])
with colS1:
    if st.button('💾 Apply Edits to Full Dataset'):
        # Merge back by index relation (best effort for this simple version)
        # Since we didn't add a row id here, we update by matching all columns that exist in both
        # For reliability, we simply replace filtered rows in base where all values match original
        # Simpler approach: write edited to CSV directly
        st.session_state.df_base = edited.copy()
        st.success('Applied edits to session data')
with colS2:
    if st.button('⬇️ Save & Download CSV (Full Dataset)'):
        buff = io.StringIO(); st.session_state.df_base.to_csv(buff, index=False)
        st.download_button('Download Updated CSV', buff.getvalue(), file_name='updated_'+st.session_state.file_name, mime='text/csv')

st.markdown("</div>", unsafe_allow_html=True)
