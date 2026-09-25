import streamlit as st
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from shapely.geometry import Polygon, MultiPolygon, LineString
from shapely.ops import unary_union
import numpy as np
import os
import zipfile

st.set_page_config(page_title="TNCDBR 2019 Advanced Layout Generator", layout="wide")

st.title("🏗️ TNCDBR 2019 Advanced Urban Subdivision Workspace")
st.markdown("""
This production-ready workspace partitions parcel boundaries based on **TNCDBR 2019 rules**. 
It dynamically accommodates mixed-use commercial pockets, custom road grids, and generates downloadable **GeoJSON files** for GIS/AutoCAD workflows.
""")

# --- SIDEBAR INTERFACE CONTROLS ---
st.sidebar.header("🕹️ Global Infrastructure Rules")
road_width = st.sidebar.slider("Primary Access Spine Width (meters)", 9.0, 24.0, 12.0, 1.0, 
                               help="TNCDBR Rule 47: Minimum extendable layout road width is 9.0m.")

st.sidebar.header("🏠 Residential Plots Zoning")
res_w = st.sidebar.slider("Res. Plot Width (m)", 6.0, 15.0, 8.0, 0.5)
res_h = st.sidebar.slider("Res. Plot Depth (m)", 10.0, 25.0, 11.0, 0.5)
res_area_min = res_w * res_h
st.sidebar.caption(f"Calculated Res. Size: {res_area_min:.1f} m² (Statutory Min: 72 m²)")

st.sidebar.header("🏢 Commercial Blocks Zoning")
enable_commercial = st.sidebar.checkbox("Integrate Commercial Zone", value=True)
comm_split = st.sidebar.slider("Commercial Area Allocation (% of Saleable)", 10, 40, 20, 5) if enable_commercial else 0
comm_w = st.sidebar.slider("Comm. Plot Width (m)", 12.0, 40.0, 20.0, 1.0) if enable_commercial else 15.0
comm_h = st.sidebar.slider("Comm. Plot Depth (m)", 15.0, 50.0, 25.0, 1.0) if enable_commercial else 20.0

st.sidebar.header("📂 Spatial Boundary Input")
uploaded_file = st.sidebar.file_uploader("Upload Boundary (KML or Shapefile .zip)", type=["kml", "zip"])

def process_advanced_layout(file_path, r_w, r_w_val, r_h_val, c_enabled, c_pct, c_w_val, c_h_val):
    if file_path.lower().endswith('.kml'):
        try:
            import fiona
            fiona.drvsupport.supported_drivers['KML'] = 'rw'
            gdf = gpd.read_file(file_path, driver='KML')
        except Exception:
            gdf = gpd.read_file(file_path)
    else:
        gdf = gpd.read_file(file_path)

    if gdf.crs is None or gdf.crs.is_geographic:
        gdf = gdf.to_crs(epsg=32644)  # Reproject to UTM Zone 44N for precise metric metrics

    parcel = gdf.unary_union
    total_area = parcel.area
    
    # Statutory Requirements Calculations
    req_osr = total_area * 0.10          
    req_public = total_area * 0.01       
    
    min_x, min_y, max_x, max_y = parcel.bounds
    width, height = max_x - min_x, max_y - min_y

    # Slice statutory zones safely
    osr_w = np.sqrt(req_osr)
    osr_poly = Polygon([(min_x, max_y), (min_x + osr_w, max_y), (min_x + osr_w, max_y - osr_w), (min_x, max_y - osr_w)]).intersection(parcel)
    
    public_w = np.sqrt(req_public)
    public_poly = Polygon([(min_x, min_y), (min_x + public_w, min_y), (min_x + public_w, min_y + public_w), (min_x, min_y + public_w)]).intersection(parcel)

    remaining_parcel = parcel.difference(osr_poly).difference(public_poly)
    
    # Process Layout Infrastructure Road Spine
    mid_x, mid_y = min_x + (width / 2), min_y + (height / 2)
    h_road = LineString([(min_x, mid_y), (max_x, mid_y)]).buffer(r_w / 2)
    v_road = LineString([(mid_x, min_y), (mid_x, max_y)]).buffer(r_w / 2)
    road_network = unary_union([h_road, v_road]).intersection(parcel)

    plot_blocks = remaining_parcel.difference(road_network)
    export_features = []
    
    def add_export_geometry(geom, zone_type):
        if isinstance(geom, Polygon) and not geom.is_empty:
            export_features.append(gpd.GeoDataFrame([{'geometry': geom, 'zone': zone_type}], crs="EPSG:32644"))
        elif isinstance(geom, MultiPolygon):
            for poly in geom.geoms:
                if not poly.is_empty:
                    export_features.append(gpd.GeoDataFrame([{'geometry': poly, 'zone': zone_type}], crs="EPSG:32644"))

    add_export_geometry(osr_poly, "OSR_Park_10pct")
    add_export_geometry(public_poly, "Public_Utilities_1pct")
    add_export_geometry(road_network, "Road_Network")

    res_plots_count = 0
    comm_plots_count = 0
    
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')
    ax.axis('off')
    
    ax.fill(*osr_poly.exterior.xy, facecolor='#27ae60', edgecolor='#1e8449', alpha=0.7)
    ax.fill(*public_poly.exterior.xy, facecolor='#f1c40f', edgecolor='#f39c12', alpha=0.7)
    
    if isinstance(road_network, Polygon):
        ax.fill(*road_network.exterior.xy, color='#7f8c8d', alpha=0.8)
    elif isinstance(road_network, MultiPolygon):
        for poly in road_network.geoms:
            ax.fill(*poly.exterior.xy, color='#7f8c8d', alpha=0.8)

    comm_threshold_x = min_x + (width * (1.0 - (c_pct / 100.0))) if c_enabled else max_x

    if isinstance(plot_blocks, Polygon):
        blocks_list = [plot_blocks]
    elif isinstance(plot_blocks, MultiPolygon):
        blocks_list = plot_blocks.geoms
    else:
        blocks_list = []

    for block in blocks_list:
        b_minx, b_miny, b_maxx, b_maxy = block.bounds
        
        is_comm_block = c_enabled and (b_maxx > comm_threshold_x)
        p_w = c_w_val if is_comm_block else r_w_val
        p_h = c_h_val if is_comm_block else r_h_val
        f_color = '#af7ac5' if is_comm_block else '#ebedef'
        e_color = '#8e44ad' if is_comm_block else '#bdc3c7'
        b_color = '#f5eef8' if is_comm_block else '#d5f5e3'
        s_color = '#9b59b6' if is_comm_block else '#2ecc71'
        
        x_coords = np.arange(b_minx, b_maxx, p_w + 1.0)
        y_coords = np.arange(b_miny, b_maxy, p_h + 1.0)
        
        for x in x_coords:
            for y in y_coords:
                potential_plot = Polygon([(x, y), (x + p_w, y), (x + p_w, y + p_h), (x, y + p_h)])
                if block.contains(potential_plot):
                    if is_comm_block:
                        comm_plots_count += 1
                        zone_label = f"Commercial_Plot_{comm_plots_count}"
                    else:
                        res_plots_count += 1
                        zone_label = f"Residential_Plot_{res_plots_count}"
                        
                    add_export_geometry(potential_plot, zone_label)
                    
                    ax.fill(*potential_plot.exterior.xy, facecolor=f_color, edgecolor=e_color, linewidth=0.6)
                    footprint = potential_plot.buffer(-1.5)
                    if not footprint.is_empty and isinstance(footprint, Polygon):
                        ax.fill(*footprint.exterior.xy, facecolor=b_color, edgecolor=s_color, alpha=0.4, linewidth=0.3)

    final_gdf = gpd.GeoDataFrame(gpd.pd.concat(export_features, ignore_index=True), crs="EPSG:32644")
    geojson_out = final_gdf.to_crs(epsg=4326).to_json()

    metrics = {
        "total_area": total_area,
        "osr_area": osr_poly.area,
        "public_area": public_poly.area,
        "road_area": road_network.area,
        "res_count": res_plots_count,
        "comm_count": comm_plots_count,
        "geojson": geojson_out
    }
    
    return fig, metrics

if uploaded_file is not None:
    temp_dir = "temp_spatial_workspace"
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, uploaded_file.name)
    
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
        
    if uploaded_file.name.endswith('.zip'):
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
            shp_files = [f for f in os.listdir(temp_dir) if f.endswith('.shp')]
            if shp_files:
                file_path = os.path.join(temp_dir, shp_files[0])

    try:
        if res_area_min < 72.0:
            st.error("⚠️ TNCDBR 2019 Violation: Your configured residential plot setup falls under the 72 sq.m legal threshold limitation.")
        else:
            with st.spinner("Processing generative mixed-use parcel calculations..."):
                fig, metrics = process_advanced_layout(
                    file_path, road_width, res_w, res_h, 
                    enable_commercial, comm_split, comm_w, comm_h
                )
                
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Subdivision Layout Blueprint Preview")
                st.pyplot(fig)
                
            with col2:
                st.subheader("Statutory Compliance Area Statement")
                
                data_matrix = {
                    "Land Allocation Component": ["OSR Park Space (10%)", "Public Utilities (1%)", "Road Infrastructure"],
                    "Calculated Metrics (m²)": [f"{metrics['osr_area']:.2f}", f"{metrics['public_area']:.2f}", f"{metrics['road_area']:.2f}"],
                    "Ratio Summary": [f"{(metrics['osr_area']/metrics['total_area'])*100:.1f}%", f"{(metrics['public_area']/metrics['total_area'])*100:.1f}%", f"{(metrics['road_area']/metrics['total_area'])*100:.1f}%"]
                }
                st.table(data_matrix)
                
                st.metric(label="✅ Verified Residential Plots", value=f"{metrics['res_count']} Units")
                if enable_commercial:
                    st.metric(label="🏢 Verified Commercial Blocks", value=f"{metrics['comm_count']} Units")
                
                st.subheader("💾 Export & Delivery System")
                st.markdown("Download the fully vectorized plot layout as a GeoJSON file. You can import this file directly into AutoCAD, ArcGIS, or QGIS.")
                
                st.download_button(
                    label="Download Layout Vector (GeoJSON)",
                    data=metrics['geojson'],
                    file_name="tncdbr_finalized_layout.geojson",
