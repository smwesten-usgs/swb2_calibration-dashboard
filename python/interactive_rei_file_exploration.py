import pandas as pd
import holoviews as hv
import panel as pn
from bokeh.models import HoverTool
from holoviews import opts
from dataretrieval import nldi, nwis
from pathlib import Path
import geopandas as gpd
import folium

data_dir = Path("../data")
pest_output_dir = Path("../pest_output")

gaging_basins_shapefile = data_dir / 'gage_contributing_areas.shp'
gage_df = gpd.read_file(gaging_basins_shapefile)

# read in the Pest++ *.rei file output
df_orig = pd.read_csv(data_dir / 'pestpp_noptmax0_run.rei', sep='\s+', skiprows=3)

# read in csv containing additional notes about the calibration gages
df_supplemental = pd.read_csv(data_dir / 'notes_regarding_gages_used_for_calibration.csv', dtype=str)
# need to Mickey Mouse around to prevent Pandas from treating these as &#$! integer values and
# losing the leading zero
df_supplemental_stations = df_supplemental.Station.str.split('_',expand=True)[1]
df_supplemental['Station'] = df_supplemental_stations.values

# derive some metadata from the observation and group names
df_meta = df_orig.Name.str.split("_", expand=True)
df_meta2 = df_orig.Group.str.split("__", expand=True)

# give the column names more memorable names
df_meta.columns=(['variable','index_no','gage_no','timeframe','soiltype'])
df_meta2.columns=(['observation_type','region'])

df_meta3 = df_meta.timeframe.str.split("-", expand=True)
df_meta3.columns=(['short_observation_type','junk'])
year_strs = [str(y) for y in range(2000,2024)]
df_meta3 = df_meta3.replace(to_replace=year_strs, value='annual')

# concatenate all of this together
df = pd.concat([df_orig,df_meta,df_meta2,df_meta3], axis='columns')
df = pd.merge(left=df, right=df_supplemental, left_on='gage_no', right_on='Station')
# Enable the Holoviews extension for Bokeh
hv.extension('bokeh')


def read_raster(file_path):
    """Read a raster file using rasterio and return the data and bounds."""
    with rasterio.open(file_path) as src:
        data = src.read(1)  # Read the first band
        bounds = src.bounds  # Get the bounds of the raster
        transform = src.transform  # Get the affine transformation
    return data, bounds, transform


def get_gaging_basin_outlines(gage_no_list):
    """Obtain gaging basin features using dataretrieval package"""
    # this code compliments of Bridget K!
    basin_list = []
    for gage in gage_no_list: # list of USGS streamgage site numbers
        if gage.startswith('0'):
            try:
                # Get the contributing area of the sites
                basin = nldi.get_basin(feature_source = 'nwissite', feature_id = f'USGS-{gage}') # call to grab the basin for each site
                basin['gage_no'] = gage
                basin_list.append(basin)
            except:
                pass    

    all_basins = pd.concat(basin_list)
    all_basins.to_file(gaging_basins_shapefile)

def create_info_df(gage_no_filter):
    info_df = nwis.get_info(sites=gage_no_filter[0])[0]
    df_widget = pn.widgets.DataFrame(info_df, name='Site Info')
    return df_widget

def create_gage_description(gage_no_filter):
    filtered_df = df[
        df['gage_no'].isin(gage_no_filter)
    ]
    
    try:
        #description_txt = filtered_df.Station_Name
        description_txt = f"## {str(filtered_df['Station_Name'].values[0])} ({gage_no_filter[0]})"
    except:
        description_txt = "no selection"

    static_text = pn.pane.Alert(description_txt, alert_type='dark')
    return static_text


def create_gage_info(gage_no_filter):
    filtered_df = df[
        df['gage_no'].isin(gage_no_filter)
    ]
    
    try:
        #description_txt = filtered_df.Station_Name
        description_txt = (f"### NOTES:\n"
                           f"{str(filtered_df['Note_re_baseflow_analysis'].values[0])}\n"
                           f"{str(filtered_df['Additional_notes'].values[0])}"
        )
    except:
        description_txt = "no selection"

    static_text = pn.pane.Markdown(description_txt, hard_line_break=True)
    return static_text


def create_locator_map(gage_no_filter):
    filtered_gage_df = gage_df[
        (gage_df['gage_no'].isin(gage_no_filter))
    ]
    #filtered_df = filtered_df.to_crs(epsg=4326)
    m = folium.Map(location=[42, -96], zoom_start=10, tiles="OpenStreetMap")

    for _, r in filtered_gage_df.iterrows():
        # Without simplifying the representation of each borough,
        # the map might not be displayed
        sim_geo = gpd.GeoSeries(r["geometry"]).simplify(tolerance=0.001)
        geo_j = sim_geo.to_json()
        geo_j = folium.GeoJson(data=geo_j, style_function=lambda x: {"fillColor": "orange"})
        folium.Popup(r["gage_no"]).add_to(geo_j)
        geo_j.add_to(m)

    m.fit_bounds(m.get_bounds(), padding=(30, 30))

    return m

# Create a function to generate the scatter plot
def create_scatter_plot(gage_no_filter, variable_filter):
    filtered_df = df[
        (df['gage_no'].isin(gage_no_filter)) &
        (df['variable'].isin(variable_filter))
    ]
    
    title_txt = ""
    #
    # WTF? Pandas freaks when supplied with the following.
    #title_txt = f"{filtered_df.Station_Name[0]}"

    min_val = min(filtered_df['Modelled'].min(), filtered_df['Measured'].min())
    max_val = max(filtered_df['Modelled'].max(), filtered_df['Measured'].max())

    scatter = hv.Points(filtered_df, kdims=['Modelled', 'Measured'], vdims=['Residual', 'gage_no', 
      'variable', 'short_observation_type', 'observation_type', 'timeframe', 'region', 
      'Weight', 'Note_re_baseflow_analysis', 'Additional_notes', 'Station_Name'])
        
    scatter.opts(
        tools=['hover'],
        width=650,
        height=650,
        size=11,
        alpha=0.6,
        color='short_observation_type',
        cmap='Accent',
        colorbar=True,
        #title=title_txt,
        xlabel='Modelled',
        ylabel='Measured',
        xlim=(min_val, max_val),
        ylim=(min_val, max_val),
    )    
    
    slope = hv.Slope(1.0, 0.0)

    return scatter * slope.opts(color='grey', line_width=3)

gage_no_list = sorted(list(df['gage_no'].unique()))

if (not gaging_basins_shapefile.exists()):
    get_gaging_basin_outlines(gage_no_list)



# Create widgets for filtering
gage_no_selector = pn.widgets.MultiSelect(name='Gage No', options=gage_no_list, value=gage_no_list)
variable_selector = pn.widgets.MultiSelect(name='Variable', options=list(df['variable'].unique()), value=list(df['variable'].unique()[1]))
#timeframe_selector = pn.widgets.MultiSelect(name='Timeframe', options=list(df['timeframe'].unique()), value=list(df['timeframe'].unique()))

# Create a Panel layout
@pn.depends(gage_no_selector.param.value)
def update_gage_info(gage_no):
    return create_gage_info(gage_no)

@pn.depends(gage_no_selector.param.value)
def update_gage_description(gage_no):
    return create_gage_description(gage_no)

@pn.depends(gage_no_selector.param.value)
def update_map(gage_no):
    return create_locator_map(gage_no)

@pn.depends(gage_no_selector.param.value, variable_selector.param.value)
def update_plot(gage_no, variable):
    return create_scatter_plot(gage_no, variable)

# Layout the dashboard
dashboard = pn.GridSpec(sizing_mode='stretch_both', max_height=800)

dashboard[0, :9] = update_gage_description
dashboard[1:2, 0] = gage_no_selector
dashboard[3, 0] = variable_selector
dashboard[1:8,1:4] =update_plot
dashboard[1:8,5:8] =update_map
dashboard[9,0:9] = update_gage_info

# Serve the dashboard
dashboard.servable()