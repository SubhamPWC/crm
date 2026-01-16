
import os
import io
import time
import requests
import pandas as pd
import streamlit as st
import altair as alt
import pydeck as pdk

st.set_page_config(page_title="CRM Dashboard — Filters + Map + ORS", layout="wide", page_icon="📊")

with open("styles.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

st.markdown("<div class='glass'><h1>📊 CRM Dashboard — Filters, Charts & Map (ORS Geocoding)</h1></div>", unsafe_allow_html=True)

LAT = "lat"
LON = "lon"
REMARKS = "Remarks"
ROW_ID = "__row_id__"

# Secrets
ORS_API_KEY = st.secrets.get("ORS_API_KEY", "")

# Helpers
@st.cache_data(show_spinner=False)
def load_csv(uploaded):
    df = pd.read_csv(uploaded)
    df.columns = [str(c).strip() for c in df.columns]
    if REMARKS not in df.columns:
        df[REMARKS] = ""
    if ROW_ID not in df.columns:
        df.insert(0, ROW_ID, range(1, len(df) + 1))
    return df

def ors_geocode(query_text: str, api_key: str, country_bias: str | None = None):
    try:
        url = "https://api.openrouteservice.org/geocode/search"
        params = {"api_key": api_key, "text": query_text}
        if country_bias:
            params["boundary.country"] = country_bias
        r = requests.get(url, params=params, timeout=15)
        if r.status_code != 200:
            return None, None
        js = r.json() or {}
        feats = js.get("features") or []
        if not feats:
            return None, None
        lon, lat = feats[0]["geometry"]["coordinates"]
        return float(lat), float(lon)
    except Exception:
        return None, None

# Sidebar
with st.sidebar:
    st.header("📁 Upload & Controls")
    file = st.file_uploader("Upload CSV", type=["csv"])
    st.caption("CSV needs a 'Location' column. The app can create lat/lon using ORS.")
    st.divider()
    country_bias = st.text_input("Country bias (optional, e.g., IN, USA, DE)", value="")
    rate_ms = st.slider("Geocode rate limit (ms)", 100, 1500, 300, 50)
    auto_geocode = st.checkbox("Auto-geocode on upload if lat/lon missing", value=True)

if not file:
    st.info("Upload a CSV to begin")
    st.stop()

if "df_base" not in st.session_state or st.session_state.get("file_name") != file.name:
    st.session_state.df_base = load_csv(file)
    st.session_state.file_name = file.name

base = st.session_state.df_base.copy()

# Ensure required columns
if "Location" not in base.columns:
    st.error("CSV must contain a 'Location' column.")
    st.stop()
if LAT not in base.columns:
    base[LAT] = None
if LON not in base.columns:
    base[LON] = None

# Determine which rows need geocoding
lat_num = pd.to_numeric(base[LAT], errors="coerce")
lon_num = pd.to_numeric(base[LON], errors="coerce")
need_mask = lat_num.isna() | lon_num.isna()

# Decide if geocoding should run
trigger_geo = False
if auto_geocode and need_mask.any() and ORS_API_KEY:
    trigger_geo = True
if st.button("⚡ Geocode Location → lat/lon (via ORS)"):
    trigger_geo = True

# Run geocoding if triggered
if trigger_geo:
    if not ORS_API_KEY:
        st.error("Missing ORS_API_KEY. Add it to .streamlit/secrets.toml")
    else:
        todo = base[need_mask].copy()
        total = len(todo)
        if total == 0:
            st.success("All rows already have coordinates.")
        else:
            prog = st.progress(0, text="Geocoding…")
            for i, (idx, row) in enumerate(todo.iterrows(), start=1):
                parts = [str(row.get("Location", ""))]
                if "Customer" in base.columns:
                    parts.append(str(row.get("Customer", "")))
                q = " ".join([p for p in parts if p and p.lower() != "nan"]).strip()
                lat, lon = ors_geocode(q, ORS_API_KEY, country_bias.strip() or None)
                if lat is not None and lon is not None:
                    base.at[idx, LAT] = lat
                    base.at[idx, LON] = lon
                time.sleep(rate_ms / 1000)
                prog.progress(i / total, text=f"Geocoding {i}/{total}")
            prog.empty()
            st.session_state.df_base = base
            st.success("Geocoding complete. Coordinates saved.")
            try:
                st.rerun()
            except Exception:
                pass

# Cascading filters
filtered = base.copy()
for col in ["Customer", "Location", "Package", "Application"]:
    if col in filtered.columns:
        opts = sorted(filtered[col].dropna().astype(str).unique())
        selected = st.sidebar.multiselect(col, opts)
        if selected:
            filtered = filtered[filtered[col].astype(str).isin(selected)]

# KPI cards
st.markdown("<div class='glass metric-card'>", unsafe_allow_html=True)
k1, k2, k3, k4 = st.columns(4)
with k1:
    st.metric("Records", len(filtered))
with k2:
    st.metric("Customers", filtered["Customer"].nunique() if "Customer" in filtered else "—")
with k3:
    st.metric("Packages", filtered["Package"].nunique() if "Package" in filtered else "—")
with k4:
    qty_series = pd.to_numeric(filtered.get("Qty", pd.Series(dtype=float)), errors="coerce").fillna(0)
    total_qty = int(qty_series.sum()) if not qty_series.empty else 0
    st.metric("Total Qty", total_qty)
st.markdown("</div>", unsafe_allow_html=True)

# Charts
colA, colB = st.columns(2)
with colA:
    st.markdown("<div class='glass'><h4>By Customer</h4>", unsafe_allow_html=True)
    if "Customer" in filtered and not filtered.empty:
        vc = filtered["Customer"].astype(str).value_counts().reset_index()
        if not vc.empty:
            vc.columns = ["Customer", "Count"]
            chart = (
                alt.Chart(vc.head(15)).mark_bar(color="#7aa2ff").encode(
                    x=alt.X("Count:Q", title="Count"),
                    y=alt.Y("Customer:N", sort='-x', title="Customer"),
                    tooltip=[alt.Tooltip("Customer:N"), alt.Tooltip("Count:Q")]
                ).properties(height=320)
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No data after filters")
    else:
        st.info("Add Customer column to see this chart.")
    st.markdown("</div>", unsafe_allow_html=True)

with colB:
    st.markdown("<div class='glass'><h4>By Package</h4>", unsafe_allow_html=True)
    if "Package" in filtered and not filtered.empty:
        vc = filtered["Package"].astype(str).value_counts().reset_index()
        if not vc.empty:
            vc.columns = ["Package", "Count"]
            chart = (
                alt.Chart(vc.head(15)).mark_bar(color="#9fe6a0").encode(
                    x=alt.X("Count:Q", title="Count"),
                    y=alt.Y("Package:N", sort='-x', title="Package"),
                    tooltip=[alt.Tooltip("Package:N"), alt.Tooltip("Count:Q")]
                ).properties(height=320)
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            st.info("No data after filters")
    else:
        st.info("Add Package column to see this chart.")
    st.markdown("</div>", unsafe_allow_html=True)

# Map
st.markdown("<div class='glass'><h4>🗺️ Map</h4>", unsafe_allow_html=True)
if {LAT, LON}.issubset(filtered.columns) and filtered[LAT].notna().any() and filtered[LON].notna().any():
    mdf = filtered.dropna(subset=[LAT, LON]).copy()
    def status_color(val):
        s = str(val).lower()
        if "received" in s:
            return [80, 200, 120]
        if "hold" in s:
            return [255, 150, 0]
        if "fund" in s:
            return [255, 90, 90]
        return [120, 200, 255]
    if "Current Status" in mdf.columns:
        mdf["__color__"] = mdf["Current Status"].apply(status_color)
    else:
        mdf["__color__"] = [120, 200, 255] * len(mdf)

    # Tooltip uses a single-line string with 
 (no multiline literals)
    if "Customer" in mdf.columns and "Location" in mdf.columns:
        tooltip = {"text": "{Customer}\n{Location}"}
    elif "Customer" in mdf.columns:
        tooltip = {"text": "{Customer}"}
    elif "Location" in mdf.columns:
        tooltip = {"text": "{Location}"}
    else:
        tooltip = {"text": "Point"}

    layer = pdk.Layer(
        "ScatterplotLayer",
        mdf,
        get_position=[LON, LAT],
        get_radius=60000,
        get_color="__color__",
        pickable=True,
    )
    view = pdk.ViewState(
        latitude=float(pd.to_numeric(mdf[LAT]).mean()),
        longitude=float(pd.to_numeric(mdf[LON]).mean()),
        zoom=4,
    )
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, map_style="dark", tooltip=tooltip))
else:
    st.warning("Map needs numeric lat/lon values. Click Geocode above to populate them from Location.")

st.markdown("</div>", unsafe_allow_html=True)

# Editor & Save
st.markdown("<div class='glass'><h4>✏️ Edit Data / Remarks</h4>", unsafe_allow_html=True)
edited = st.data_editor(filtered, num_rows="dynamic", use_container_width=True, height=380)

colS1, colS2 = st.columns([1, 2])
with colS1:
    if st.button("💾 Apply Edits to Full Dataset"):
        upd = edited.set_index(ROW_ID)
        base_idx = base.set_index(ROW_ID)
        base_idx.update(upd)
        st.session_state.df_base = base_idx.reset_index()
        st.success("Edits applied to full dataset in session.")
with colS2:
    if st.button("⬇️ Save & Download CSV (Full Dataset)"):
        buff = io.StringIO()
        st.session_state.df_base.to_csv(buff, index=False)
        st.download_button("Download Updated CSV", buff.getvalue(), file_name="updated_" + st.session_state.file_name, mime="text/csv")

st.markdown("</div>", unsafe_allow_html=True)
