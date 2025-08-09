from collections import Counter

import altair as alt
import pandas as pd
import pydeck as pdk
from matplotlib import colormaps
from scipy import stats
from streamlit_extras.dataframe_explorer import dataframe_explorer
from utils import AIRPORTS, aggregate_takeoffs_landings

import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(
    page_title="Blagnacoscope · Airports, Airlines, Aircraft",
    page_icon="✈️",
    layout="wide",
)


def stats_time(df):
    st.subheader("Days and times", divider=True)
    # TODO: not very satisfying to have to use `ambiguous=True` here...
    df["dt"] = df["datetime"].dt.tz_localize("Europe/Paris", ambiguous=True)
    c = alt.Chart(df).mark_bar().encode(x=alt.X("hours(dt):O"), y="count()", color="rwy_event").interactive()
    st.altair_chart(c, use_container_width=True)
    c = alt.Chart(df).mark_bar().encode(x=alt.X("day(dt):O"), y="count()").interactive()
    st.altair_chart(c, use_container_width=True)


def stats_airlines(df):
    st.subheader("Airlines", divider=True)

    def _top_airport(airports):
        return Counter(airports).most_common(1)[0][0]

    d = df.groupby("airline").agg(
        fr_id=pd.NamedAgg("fr_id", lambda x: round(len(x) / len(df) * 100, 2)),
        registration=pd.NamedAgg("registration", "nunique"),
        aircraft=pd.NamedAgg("aircraft", "nunique"),
        connecting_airport=pd.NamedAgg("connecting_airport", "nunique"),
        top_airport=pd.NamedAgg("connecting_airport", _top_airport),
    )
    st.dataframe(
        d.sort_values(by="fr_id", ascending=False).rename(
            columns={
                "fr_id": "% of flights",
                "registration": "# of aircraft",
                "aircraft": "# of aircraft models",
                "connecting_airport": "# of destinations",
            }
        ),
        use_container_width=True,
    )


def stats_airports(df):
    st.subheader("Airports", divider=True)
    cols = st.columns(3)
    for col, var, data, title in zip(
        cols,
        ["connecting_airport", "origin_airport", "destination_airport"],
        [df, df[df["rwy_event"] == "landing"], df[df["rwy_event"] == "takeoff"]],
        ["flights", "landings", "takeoffs"],
    ):
        col.dataframe(
            data.groupby(var)["fr_id"].count().sort_values(ascending=False) / len(df) * 100,
            column_config={
                "fr_id": st.column_config.NumberColumn(label=f"% of {title}", format="%.2f"),
                var: st.column_config.Column(var.replace("_", " ").capitalize()),
            },
        )
        if var == "connecting_airport":
            st.caption(
                "What are connecting airports?",
                help=(
                    "Connecting airports are the destination airports of flights taking off from Toulouse, "
                    "and the origin airports of flights landing in Toulouse."
                ),
            )


def stats_aircraft(df):
    st.subheader("Aircraft", divider=True)
    col1, col2 = st.columns((1, 2))
    col1.dataframe(
        df.groupby("aircraft")
        .agg({"fr_id": "count", "registration": "nunique"})
        .sort_values(by="fr_id", ascending=False)
        .rename(columns={"fr_id": "# of flights", "registration": "# of aircraft"}),
        column_config={"aircraft": st.column_config.Column("Aircraft type")},
    )

    def _top_airport(airports):
        return Counter(airports).most_common(1)[0][0]

    def _airline_agg(airlines):
        airlines = [airline for airline in airlines if airline != " (N/A)"]
        if not airlines:
            return " (N/A)"
        return Counter(airlines).most_common(1)[0][0]

    col2.dataframe(
        df.groupby("registration")
        .agg({"aircraft": "first", "airline": _airline_agg, "fr_id": "count", "connecting_airport": _top_airport})
        .sort_values(by="fr_id", ascending=False)
        .rename(
            columns={
                "fr_id": "# of flights",
                "aircraft": "Aircraft",
                "airline": "Airline",
                "connecting_airport": "Top airport",
            }
        ),
        column_config={"registration": st.column_config.Column("Aircraft registration")},
        use_container_width=True,
    )


def map(airports):
    st.subheader("Map of origins/destinations", divider=True)
    view_mode = st.radio(
        "Select display mode",
        options=["Globe", "Map"],
        captions=["3D globe", "Flat map, that you can tilt and rotate using Ctrl+click"],
        horizontal=True,
    )
    split_rwy_event = st.toggle("Split takeoffs and landings", disabled=view_mode == "Globe")

    groupby = ["connecting_airport"]
    if split_rwy_event:
        groupby.append("rwy_event")
    data = airports[airports["connecting_airport"] != " (N/A)"].groupby(groupby, as_index=False).agg({"fr_id": "count"})

    data["airport_code"] = data["connecting_airport"].apply(lambda x: x[-4:-1])
    data["latitude"] = data["airport_code"].apply(lambda x: AIRPORTS[x]["latitude"])
    data["longitude"] = data["airport_code"].apply(lambda x: AIRPORTS[x]["longitude"])
    data["latitude_tls"] = AIRPORTS["TLS"]["latitude"]
    data["longitude_tls"] = AIRPORTS["TLS"]["longitude"]
    count_max = data["fr_id"].max()
    count_min = data["fr_id"].min()
    data["count_norm"] = data["fr_id"].apply(lambda x: (x - count_min) / count_max)
    data["width"] = data["count_norm"].apply(lambda x: 2 + x * 30)
    if not split_rwy_event:
        data["rwy_event"] = "N/A"
    data["tilt"] = data["rwy_event"].apply(lambda x: {"takeoff": 15, "landing": -15}.get(x, 0))

    def _count_to_info(row):
        count = row["fr_id"]
        event = row["rwy_event"]
        word = event if event in {"takeoff", "landing"} else "flight"
        if count > 1:
            word += "s"
        pct = count / data["fr_id"].sum() * 100
        return f"{count} {word} ({pct:.2f}%)"

    data["info"] = data.apply(_count_to_info, axis=1)

    def _count_to_color(count, count_series, rwy_event):
        gradient = colormaps[{"takeoff": "Reds", "landing": "Greens"}.get(rwy_event, "cividis")]
        rank = stats.percentileofscore(count_series, count, kind="weak")
        color = gradient(rank / 100)[:3]
        color = [int(el * 255) for el in color]
        return color

    data["color"] = data.apply(
        lambda row: _count_to_color(row["count_norm"], data["count_norm"], row["rwy_event"]), axis=1
    )
    data["color_start"] = data["color"].apply(lambda x: x + [25])
    data["color_end"] = data["color"].apply(lambda x: x + [255])

    arc_layer = pdk.Layer(
        "ArcLayer",
        data=data,
        great_circle=(view_mode == "Globe"),
        get_width="width",
        get_height=0.3,
        get_tilt="tilt",
        get_source_position=["longitude_tls", "latitude_tls"],
        get_target_position=["longitude", "latitude"],
        get_source_color="color_start",
        get_target_color="color_end",
        pickable=True,
        auto_highlight=True,
    )

    # This is needed in GlobeView, because otherwise the globe is empty (no basemap) and you can see through it.
    globe_layers = [
        pdk.Layer(
            "PolygonLayer",
            data=pd.DataFrame({"coordinates": [[[-180, 90], [0, 90], [180, 90], [180, -90], [0, -90], [-180, -90]]]}),
            get_polygon="coordinates",
            get_fill_color=[25, 26, 26],
        ),
        pdk.Layer(
            "GeoJsonLayer",
            "https://d2ad6b4ur7yvpq.cloudfront.net/naturalearth-3.3.0/ne_50m_admin_0_scale_rank.geojson",
            get_fill_color=[52, 51, 50],
            stroked=True,
            get_line_color=[69, 69, 69],
            get_line_width=1000,
            line_width_min_pixels=2,
            line_joint_rounded=True,
        ),
    ]

    # This is completely illegible because text labels are too dense and overlap one another.
    # There's a CollisionFilterExtension in deck.gl to solve this problem, but I haven't found
    # a way to make it work with `pydeck` (https://github.com/visgl/deck.gl/discussions/8329).

    # text_df = pd.DataFrame.from_dict(AIRPORTS, orient="index")
    # text_df["iata"] = text_df.index
    # text_df["fullname"] = text_df.apply(lambda x: f"{x['name']} ({x['iata']})", axis=1)
    # text_df["coordinates"] = text_df.apply(lambda row: (row.longitude, row.latitude), axis=1)
    # text_df = text_df[text_df["iata"].apply(lambda x: x in set(data["airport_code"]))]
    # airports_layer = (
    #     pdk.Layer(
    #         "TextLayer",
    #         data=text_df,
    #         character_set=String("auto"),
    #         get_position="coordinates",
    #         get_color=(255, 255, 255),
    #         get_size=10,
    #         get_text="fullname",
    #         outline_width=40,
    #         outline_color=(0, 0, 0),
    #         font_settings={"sdf": True, "cutoff": 0.1},
    #     ),
    # )

    view_state = pdk.ViewState(
        latitude=43.62,
        longitude=1.36,
        zoom=4,
    )

    deck_args = dict(
        initial_view_state=view_state,
        tooltip={"html": "{connecting_airport}<br/>{info}"},
    )
    if view_mode == "Globe":
        d = pdk.Deck(
            views=pdk.View(type="_GlobeView", controller=True),
            layers=globe_layers + [arc_layer],
            map_provider=None,
            **deck_args,
        )

        # Streamlit's pydeck integration doesn't handle non-MapView views.
        # This workaround uses raw HTML instead, which gets rendered as in iframe in Streamlit.
        # (see https://github.com/streamlit/streamlit/issues/2302)
        components.html(d.to_html(as_string=True), height=800)
    else:
        d = pdk.Deck(
            map_style=None,
            layers=[arc_layer],
            **deck_args,
        )
        st.pydeck_chart(d)


# Dirty hack to make Altair/Vega chart tooltips still visible when viewing a chart in fullscreen/expanded mode
# (taken from https://discuss.streamlit.io/t/tool-tips-in-fullscreen-mode-for-charts/6800/9)
st.markdown("<style>#vg-tooltip-element{z-index: 1000051}</style>", unsafe_allow_html=True)

st.title("Airports, Airlines, Aircraft")
st.markdown(
    """
This page is an interactive dashboard that can be used to dig into the takeoffs / landings data.

You can apply filters on the table just below on the columns of your choice, and these filters will be reflected
on all the tables and the map below.

For example, filter on `airline = EZY` to see all destinations of easyJet flights, or filter on `hour < 6` to see
flights taking off or landing at night.
"""
)
df = aggregate_takeoffs_landings()
filtered_df = dataframe_explorer(df)
st.dataframe(filtered_df, hide_index=True, use_container_width=True)
stats_time(filtered_df)
stats_airlines(filtered_df)
stats_airports(filtered_df)
stats_aircraft(filtered_df)
map(filtered_df)
