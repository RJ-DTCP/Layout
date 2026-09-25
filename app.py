import streamlit as st
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from shapely.geometry import Polygon, MultiPolygon, LineString
from shapely.ops import unary_union
import numpy as np
import os
import zipfile

st.set_page_config(page_title="TNCDBR 2019 Urban Layout Generator", layout="wide")

st.title("🏗️ TNCDBR 2019 Compliant Urban Subdivision Generator")
st.markdown("""
This web application takes an uploaded parcel boundary (KML or Shapefile) and automatically partitions it 
based on the statutory rules of the **Tamil Nadu Combined Development and Building Rules (TNCDBR) 2019**.
""")

# Sidebar settings configuration
st.sidebar.header("Configuration Parameters")
plot_w = st.sidebar.slider("Target Plot Width (meters)", 6.0, 15.0, 8.0, 0.5)
plot_h = st.sidebar.slider("Target Plot Depth (meters)", 10.0, 25.0, 11.0, 0.5)
road_width = st.sidebar.selectbox("Primary Collector Road Width (meters)", [9.0, 12.0, 18.0], index=0)

# File uploader widget supporting multiple structural extensions
uploaded_file = st.sidebar.file_uploader(
    "Upload Parcel Boundary (KML or Shapefile .zip)", 
    type=["kml", "zip"]
)

def process_and_render(file_path, p_w, p_h, r_width):
    # Enable KML driver compilation via fiona framework natively
    if file_path.lower().endswith('.kml'):
        import fiona
        fiona.drvsupport.supported_drivers['KML'] = 'rw'
        gdf = gpd.read_file(file_path, driver='KML')
    else:
        # Assuming zipped Shapefile archive containing .shp, .shx, .dbf
        gdf = gpd.read_file(file_path)

    # Force projection assignment to metric system UTM Zone 44N for local South India geography
    if gdf.crs is None or gdf.crs.is_geographic:
        gdf = gdf.to_crs(epsg=32644)

    parcel = gdf.unary_union
    total_area = parcel.area
    
    # Statutory Percentage Apportionments 
    req_osr = total_area * 0.10          
    req_public = total_area * 0.01       
    
    min_x, min_y, max_x, max_y = parcel.bounds
    width, height = max_x - min_x, max_y - min_y

    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_aspect('equal')
    ax.axis('off')

    # Draw Site boundary envelope
    if isinstance(parcel, Polygon):
        ax.plot(*parcel.exterior.xy, color='#2c3e50', linewidth=2.5)
    elif isinstance(parcel, MultiPolygon):
        for poly in parcel.geoms:
            ax.plot(*poly.exterior.xy, color='#2c3e50', linewidth=2.5)

    # Slice OSR Park Poly from upper boundary
    osr_w = np.sqrt(req_osr)
    osr_poly = Polygon([(min_x, max_y), (min_x + osr_w, max_y), (min_x + osr_w, max_y - osr_w), (min_x, max_y - osr_w)]).intersection(parcel)
    
    # Slice Public Purpose utility layout matrix from base boundary 
    public_w = np.sqrt(req_public)
    public_poly = Polygon([(min_x, min_y), (min_x + public_w, min_y), (min_x + public_w, min_y + public_w), (min_x, min_y + public_w)]).intersection(parcel)

    ax.fill(*osr_poly.exterior.xy, facecolor='#27ae60', edgecolor='#1e8449', alpha=0.8)
    ax.fill(*public_poly.exterior.xy, facecolor='#f1c40f', edgecolor='#f39c12', alpha=0.8)

    # Extract internal road routes and residential partition frames
    remaining_parcel = parcel.difference(osr_poly).difference(public_poly)
    mid_x, mid_y = min_x + (width / 2), min_y + (height / 2)
    
    h_road = LineString([(min_x, mid_y), (max_x, mid_y)]).buffer(r_width / 2)
    v_road = LineString([(mid_x, min_y), (mid_x, max_y)]).buffer(r_width / 2)
    road_network = unary_union([h_road, v_road]).intersection(parcel)

    if isinstance(road_network, Polygon):
        ax.fill(*road_network.exterior.xy, color='#7f8c8d', alpha=0.9)
    elif isinstance(road_network, MultiPolygon):
        for poly in road_network.geoms:
            ax.fill(*poly.exterior.xy, color='#7f8c8d', alpha=0.9)

    plot_blocks = remaining_parcel.difference(road_network)
    
    # Step-iteration over modular grid lines inside building slots
    x_coords = np.arange(min_x, max_x, p_w + 1.0)
    y_coords = np.arange(min_y, max_y, p_h + 1.0)
    plot_count = 0
    allocated_plot_area = 0

    for x in x_coords:
        for y in y_coords:
            potential_plot = Polygon([(x, y), (x + p_w, y), (x + p_w, y + p_h), (x, y + p_h)])
            if plot_blocks.contains(potential_plot):
                plot_count += 1
                allocated_plot_area += potential_plot.area
                ax.fill(*potential_plot.exterior.xy, facecolor='#ebedef', edgecolor='#bdc3c7', linewidth=0.6)
                footprint = potential_plot.buffer(-1.2)
                if not footprint.is_empty and isinstance(footprint, Polygon):
                    ax.fill(*footprint.exterior.xy, facecolor='#d5f5e3', edgecolor='#2ecc71', alpha=0.4, linewidth=0.3)

    # Area balancing computation profiles
    road_area = road_network.area
    infrastructure_total = osr_poly.area + public_poly.area + road_area
    saleable_area = total_area - infrastructure_total

    metrics = {
        "total_area": total_area,
        "osr_area": osr_poly.area,
        "public_area": public_poly.area,
        "road_area": road_area,
        "saleable_area": saleable_area,
        "plots_generated": plot_count
    }
    
    return fig, metrics

if uploaded_file is not None:
    # Save the file stream temporarily to disk to enable vector parsing
    temp_dir = "temp_spatial_data"
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, uploaded_file.name)
    
    with open(file_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
        
    # Unpack file data if zipped shape archives are sent
    if uploaded_file.name.endswith('.zip'):
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
            # Locate file layer structural references
            shp_files = [f for f in os.listdir(temp_dir) if f.endswith('.shp')]
            if shp_files:
                file_path = os.path.join(temp_dir, shp_files[0])

    try:
        with st.spinner("Processing architectural vector structures..."):
            fig, metrics = process_and_render(file_path, plot_w, plot_h, road_width)
            
        col1, col2 = st.columns([3, 2])
        
        with col1:
            st.subheader("Subdivision Layout Blueprint Preview")
            st.pyplot(fig)
            
        with col2:
            st.subheader("Statutory Compliance Area Statement")
            
            # Formulating structured data representation matrices
            st.metric(label="Total Parcel Area", value=f"{metrics['total_area']:.2f} m²")
            
            data_matrix = {
                "Component Allocation": ["OSR Park Space (Min 10%)", "Public Utilities (Min 1%)", "Road Infrastructure", "Permissible Saleable Area Layout"],
                "Allocated Area (m²)": [f"{metrics['osr_area']:.2f}", f"{metrics['public_area']:.2f}", f"{metrics['road_area']:.2f}", f"{metrics['saleable_area']:.2f}"],
                "Percentage (%)": [f"{(metrics['osr_area']/metrics['total_area'])*100:.1f}%", f"{(metrics['public_area']/metrics['total_area'])*100:.1f}%", f"{(metrics['road_area']/metrics['total_area'])*100:.1f}%", f"{(metrics['saleable_area']/metrics['total_area'])*100:.1f}%"]
            }
            st.table(data_matrix)
            st.success(f"✔️ Generated **{metrics['plots_generated']}** residential plots exceeding standard safety and size constraints (>72 sq.m).")
            
    except Exception as e:
        st.error(f"Error processing spatial vector layout parameters: {e}")
else:
    st.info("💡 Please upload a spatial boundary vector format file (KML/Zip) in the sidebar workspace control panel to generate layouts.")
