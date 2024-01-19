import math

import altair as alt
import pandas as pd
import pydeck as pdk
from osmnx import features_from_bbox
from pydeck.types import String
from pyproj import Geod
from scipy.signal import find_peaks
from utils import AIRBORNE_WHERE, TOFF_LAN_WHERE, airport_zones, db_query

import streamlit as st

st.set_page_config(
    page_title="Blagnacoscope · Data exploration & filtering",
    page_icon="✈️",
)

DB_CONN = st.connection("db", type="sql")


def intro():
    st.markdown(
        """
    The database of flights is a single table in an SQlite database which contains a snapshot of flights in the airspace
    around Toulouse Blagnac airport every 30 seconds.

    Each record in the database corresponds to an
    [ADS-B](https://en.wikipedia.org/wiki/Automatic_Dependent_Surveillance%E2%80%93Broadcast) ping of an aircraft,
    containing it 3D position, speed, heading, and metadata relevant to the aircraft and the flight.

    Below are tables and charts giving an overview of the columns of the database and some of their statistics.
    """
    )


def histogram(db_conn, column):
    query = f"select {column}, count({column}) as count"
    df = db_query(db_conn, query, where=AIRBORNE_WHERE, groupby=column)

    c = alt.Chart(df, title=f"Histogram of {column}").mark_bar().encode(x=column, y="count").interactive()
    st.altair_chart(c, use_container_width=True)


def radial_histogram(db_conn, column):
    query = f"select {column}, count({column}) as count"
    df = db_query(db_conn, query, where=AIRBORNE_WHERE, groupby=column)

    def deg_to_rad(degrees):
        return (degrees / 360) * 2 * math.pi

    df["theta"] = df[column].apply(deg_to_rad)
    df["theta2"] = df[column].apply(lambda x: deg_to_rad(x + 1))
    total_count = df["count"].sum()
    df["percent"] = df["count"].apply(lambda x: x / total_count)
    df["text"] = df[column].apply(lambda x: f"{x}°")

    base = alt.Chart(df, title=f"Radial histogram of {column}")
    c = (
        base.encode(
            theta=alt.Theta("theta", scale=alt.Scale(domain=[0, 2 * math.pi])),
            theta2="theta2",
            radius=alt.Radius("count", scale=alt.Scale(type="log")),
            color=alt.Color("count", legend=None, scale=alt.Scale(type="log")),
            order=column,
            tooltip=[column, alt.Tooltip("percent", format=".2%")],
        )
        .mark_arc(stroke=None)
        .interactive()
    )

    # Add text labels next to the most prominent peaks of the histogram

    peaks, *_ = find_peaks(df["count"].values, prominence=500, distance=5)
    peaks = [int(heading) for heading in peaks]

    c2 = (
        c.mark_text(radiusOffset=10, fontSize=12)
        .encode(text="text")
        .transform_filter(alt.FieldOneOfPredicate("heading", peaks))
    )
    st.altair_chart(c + c2, use_container_width=True)


def two_dee_histogram(db_conn, column1, column2, bins=50):
    query = f"select {column1}, {column2}"
    df = db_query(db_conn, query, where=AIRBORNE_WHERE)

    c = (
        alt.Chart(df, title=f"2D histogram of {column2} vs {column1}")
        .mark_rect()
        .encode(
            alt.X(f"{column1}:Q").bin(maxbins=bins),
            alt.Y(f"{column2}:Q").bin(maxbins=bins),
            alt.Color("count():Q").scale(),
        )
        .interactive()
    )
    st.altair_chart(c, use_container_width=True)


def table_structure(db_conn):
    st.header("Table structure", divider=True)
    st.markdown("The database table generated by the scraper looks like this:")
    df = db_query(db_conn, "select *", where="altitude != 0", limit=1).transpose().rename(columns={0: "value"})
    st.dataframe(df)

    st.subheader("Keeping only airborne aircraft", divider=True)
    airborne_df = db_query(db_conn, "select count(*) as count", where=AIRBORNE_WHERE)
    all_df = db_query(db_conn, "select count(*) as count")
    pct_airborne = 100 * airborne_df["count"].iloc[0] / all_df["count"].iloc[0]
    st.markdown(
        f"""
We are only interested in monitoring aircraft that is airborne. The database contains two fields which
may be of interest to filter out aircraft that are on the ground:
- `on_ground` (boolean): I don't really know where this field comes from — is it contained directly in the ADS-B raw
   signal, or is it inferred by FlightRadar24? In any case, it doesn't cost much to only keep records where
   `on_ground = 0`
- `ground_speed`: We can set a minimum speed threshold — say 20 knots — under which we know for a fact that aircraft
   cannot be airborne

Using the filtering condition `{AIRBORNE_WHERE},` out of the {all_df['count'].iloc[0]:,} records in the database, only
{pct_airborne:.1f}% are records of aircraft that are airborne.

**In all of the following analyses (stats, graphs, queries), only the records of aircraft that are airborne will be
considered.**
    """
    )

    st.subheader(
        "Statistics on the database columns",
        divider=True,
    )
    dfs = []
    for column in [
        "latitude",
        "longitude",
        "heading",
        "altitude",
        "ground_speed",
        "vertical_speed",
    ]:
        query = "select " f"min({column}) as min, " f"max({column}) as max, " f"round(avg({column}), 2) as avg "
        df = db_query(db_conn, query, where=AIRBORNE_WHERE).transpose().rename(columns={0: column})
        dfs.append(df)
    col1, col2 = st.columns(2)
    with col1:
        st.caption("Columns with numbers")
        st.dataframe(pd.concat(objs=dfs, axis=1).transpose())
    query = "select "
    for column in [
        "icao_24bit",
        "squawk",
        "aircraft_code",
        "registration",
        "origin_airport_iata",
        "destination_airport_iata",
        "number",
        "airline_iata",
        "callsign",
        "airline_icao",
    ]:
        query += f" round(avg(case when {column} != 'N/A' then 100.0 else 0 end), 1) as {column}, "
    query = query[:-2]
    df = db_query(db_conn, query, where=AIRBORNE_WHERE).transpose().rename(columns={0: "% of valid data"})
    with col2:
        st.caption("Columns with strings")
        st.dataframe(df)


def histograms(db_conn):
    st.header("Histograms of various columns", divider=True)

    st.subheader("Heading", divider=True)
    radial_histogram(db_conn, "heading")
    st.markdown(
        """
*Heading* is the compass angle of the aircraft with respect to the North. It goes clockwise from 0 to 360°: North is 0°,
East is 90°, South is 180°, and West is 270°.

The chart above is a radial histogram of the heading of each ADS-B ping recorded.

On it, we can clearly see 4 major peaks:
- 142° and 322°, which correspond to the directions of the [two parallel runways of
  Toulouse-Blagnac — LFBO](https://en.wikipedia.org/wiki/Toulouse%E2%80%93Blagnac_Airport#Runways)
- 53° and 352°, which correspond to the directions of the two high-altitude commercial aircraft routes that can be seen
  on the heatmap above. We can note that these routes are only flown one-way (from South to North). It would be
  interesting to identify which origin/destination the aircraft flying these routes have, and see where their "return"
  routes pass.

There are also some minor peaks:
- 155° and 335°, which correspond to the takeoff/landing directions of [Aérodrome de Toulouse-Lasbordes -
  LFCL](https://fr.wikipedia.org/wiki/A%C3%A9rodrome_de_Toulouse_-_Lasbordes)

*Note: The radial axis in the histogram above is logarithmic, and not linear, in order to be able to distinguish
patterns aside from the 4 major peaks. You can hover your mouse over the graph to see the actual relative importance
of the peaks.*
"""
    )

    st.subheader("Altitude", divider=True)
    histogram(db_conn, "altitude")
    st.markdown(
        """
On this histogram, we can see 3 major peaks around "round values" of altitude: 34 000ft, 36 000ft, and 38 000ft.
This is due to the fact that when in flight, aicraft fly at a given discrete
[flight level](https://en.wikipedia.org/wiki/Flight_level). These 3 peaks correspond to the ADS-B pings of the aicraft
following the two high-altitude routes mentionned earlier.
"""
    )

    st.subheader("Ground speed", divider=True)
    histogram(db_conn, "ground_speed")
    st.markdown(
        """
Nothing too surprising here:
- One big "bump" centered around 130kts, which is a typical range of speeds for commercial aircraft taking off and
  landing.
- Another "bump" at speeds around 450 - 500kts for the aircraft flying the high-altitude routes.

When looking more closely, we can also see some lower but very narrow peaks around round values of speed at 80kts,
90kts, 100kts, and 110kts.
Wild guess: this could be due to small training aircraft flying the runway circuit loop of LFCL and trying to follow a
speed given by their instructor?
"""
    )

    st.subheader("Correlations", divider=True)
    columns = [("heading", "altitude"), ("ground_speed", "altitude")]
    tabs = st.tabs([f"{el2} vs {el1}" for (el1, el2) in columns])
    for column, tab in zip(columns, tabs):
        with tab:
            two_dee_histogram(db_conn, *column)


def heatmap_section(db_conn):
    st.header("Heatmap", divider=True)

    df = db_query(db_conn, "select latitude, longitude", where=AIRBORNE_WHERE)

    gdf = features_from_bbox(43.76, 43.49, 1.18, 1.55, tags={"aeroway": ["aerodrome", "runway"]})
    runways = gdf[(gdf.aeroway == "runway") & (gdf.geom_type == "LineString") & (gdf.surface == "asphalt")]
    runways["path"] = runways.geometry.apply(lambda geom: list(geom.coords))
    # Remove tiny "aeromodelism" runway
    runways = runways[runways.to_crs(runways.estimate_utm_crs()).length > 300]

    def _runway_heading(linestring):
        coords = linestring.coords
        p1 = coords[0]
        p2 = coords[-1]
        geod = Geod(ellps="WGS84")
        az, *_ = geod.inv(*p1, *p2)
        return az

    runways["heading"] = runways.geometry.apply(_runway_heading)

    airports = gdf[(gdf.aeroway == "aerodrome")]
    airports["coordinates"] = airports.centroid.apply(lambda centroid: (centroid.x, centroid.y))

    airports = airports[["geometry", "name", "icao", "coordinates"]]
    runways = runways[["geometry", "heading", "path"]]

    j = airports.sjoin(runways, how="inner")
    icao_heading_lookup = dict(j.groupby("icao")["heading"].mean())

    airports["heading"] = airports.icao.apply(lambda x: icao_heading_lookup[x])
    airports["angle"] = airports.heading.apply(lambda x: (90 - x) % 180 + 180)

    st.pydeck_chart(
        pdk.Deck(
            map_style=None,
            initial_view_state=pdk.ViewState(
                latitude=43.62,
                longitude=1.36,
                zoom=9.8,
            ),
            layers=[
                pdk.Layer(
                    "HeatmapLayer",
                    data=df,
                    get_position="[longitude, latitude]",
                    opacity=0.9,
                    radius_pixels=20,
                ),
                pdk.Layer(
                    "PathLayer",
                    data=runways,
                    get_path="path",
                    get_color=(21, 130, 55),
                    get_width=5,
                    width_min_pixels=3,
                ),
                pdk.Layer(
                    "TextLayer",
                    data=airports,
                    character_set=String("auto"),
                    get_position="coordinates",
                    get_color=(255, 255, 255),
                    get_size=15,
                    get_text="icao",
                    get_angle="angle",
                    get_pixel_offset=(-15, 0),
                    outline_width=40,
                    outline_color=(0, 0, 0),
                    font_settings={"sdf": True, "cutoff": 0.1},
                ),
            ],
        )
    )
    st.markdown(
        f"""
The map above shows the runways of the {len(airports)} airports present in the zone covered by data
(in :green[green]), and a heatmap of all of the ADS-B pings contained in the database.
        """
    )
    st.dataframe(airports[["icao", "name"]], hide_index=True)
    st.markdown(
        """
On the heatmap, you can see:
- The takeoff/landing trajectories of LFBO (you can even distinguish the paths for both parallel runways if
  you zoom in)
- The runway circuit loop of LFCL
- The trajectories of two high-altitude commercial flight paths that intersect near LFBO
        """
    )


def filtering(DB_CONN):
    st.header("Filtering takeoffs and landings", divider=True)
    st.markdown(
        f"""
Now that we've seen the properties of the data at hand, we can get down to business and start filtering the data to
only keep ADS-B pings for aircraft that are in a takeoff or landing phase at LFBO.

For this, we add several conditions to the previous filtering condition for airborne aircraft:
1. The aircraft's heading must be close to LFBO's runways heading (143° or 323°)
2. The aircraft's altitude must be below a certain threshold (to avoid false positives of aircraft overflying LFBO at
  high altitude)
3. The aircraft's geographical position must be aligned with the axis of LFBO's runways

The first two filtering conditions can be applied with the following SQL `where` clause:
```
{TOFF_LAN_WHERE}
```
The third one is a bit more tricky. Ideally, it would also be done in SQL using
[Spatialite](https://www.gaia-gis.it/fossil/libspatialite/index) (a geospatial extension for SQLite), but loading
Spatialite in SQLAlchemy is a bit of a pain (requires a python version compiled to allow for SQLite extensions for
example), and I can't be bothered with it right now.
We'll therefore stick with a plain old `point.within(polygon)` in [shapely](https://shapely.readthedocs.io/) /
[geopandas](https://geopandas.org/en/stable/) after the SQL query.
"""
    )

    df = db_query(DB_CONN, "select *", where=TOFF_LAN_WHERE)
    zone = airport_zones()
    x, y = zone.exterior.coords.xy
    coordinates = [(xx, yy) for xx, yy in zip(x, y)]
    df2 = pd.DataFrame({"coordinates": [coordinates]})

    st.pydeck_chart(
        pdk.Deck(
            map_style=None,
            initial_view_state=pdk.ViewState(
                latitude=43.62,
                longitude=1.36,
                zoom=9.8,
            ),
            layers=[
                pdk.Layer(
                    "HeatmapLayer",
                    data=df,
                    get_position="[longitude, latitude]",
                    opacity=0.9,
                    radius_pixels=20,
                ),
                pdk.Layer(
                    "PolygonLayer",
                    data=df2,
                    get_polygon="coordinates",
                    get_fill_color=(21, 130, 55, 100),
                ),
            ],
        )
    )

    st.markdown(
        """
The heatmap above shows:
- the points resulting from the SQL query shown above
- the polygon that is used afterwards in python to only keep points within it
"""
    )


# Dirty hack to make Altair/Vega chart tooltips still visible when viewing a chart in fullscreen/expanded mode
# (taken from https://discuss.streamlit.io/t/tool-tips-in-fullscreen-mode-for-charts/6800/9)
st.markdown("<style>#vg-tooltip-element{z-index: 1000051}</style>", unsafe_allow_html=True)

st.title("Data exploration & filtering")
intro()
table_structure(DB_CONN)
heatmap_section(DB_CONN)
histograms(DB_CONN)
filtering(DB_CONN)
