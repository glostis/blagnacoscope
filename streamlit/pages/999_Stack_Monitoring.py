import subprocess
from datetime import datetime

import altair as alt
import pytz
import streamlit as st
from sqlalchemy.sql import text

from utils import DB_PATH, TABLE, TZ, LOG_PATH

st.set_page_config(
    page_title="Blagnacoscope · Stack Monitoring",
    page_icon="✈️",
)

DB_CONN = st.experimental_connection("db", type="sql")


def chart_nb_records(db_conn, table, time_range):
    utc_now = int(datetime.now().timestamp())

    date_strings = {"day": "%Y-%m-%d %H:%M", "week": "%Y-%m-%d %H"}
    time_cutoffs = {"day": utc_now - 24 * 60 * 60, "week": utc_now - 7 * 24 * 60 * 60}
    time_agg = f"strftime('{date_strings[time_range]}', datetime(time, 'unixepoch'))"
    where_clause = f"time >= {time_cutoffs[time_range]}"
    query = f"select {time_agg} as date_string, count(*) as count from {table} where {where_clause} group by {time_agg};"
    df = db_conn.query(query)

    def _localize_dt(date_string):
        dt = datetime.strptime(date_string, date_strings[time_range])

        # Add the information that `dt` is in UTC timezone
        dt = dt.replace(tzinfo=pytz.utc)
        # Then localize it to Toulouse timezone
        dt = dt.astimezone(TZ)

        return dt

    df["date"] = df.date_string.apply(_localize_dt)

    if df.empty:
        st.markdown(
            f"⚠️ :red[**Error: there is no data for the past {time_range}**] ⚠️"
        )
    else:
        c = (
            alt.Chart(
                df, title=f"Number of records added in DB for the past {time_range}"
            )
            .mark_bar()
            .encode(
                x="date",
                y="count",
                tooltip=[alt.Tooltip("date:T", format="%Y-%m-%d %H:%M"), "count"],
            )
            .interactive()
        )
        st.altair_chart(c, use_container_width=True)


def db_stats(db_conn, table, db_path):
    def sizeof_fmt(num, suffix="B"):
        """From https://stackoverflow.com/a/1094933"""
        for unit in ("", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"):
            if abs(num) < 1024.0:
                return f"{num:3.1f}{unit}{suffix}"
            num /= 1024.0
        return f"{num:.1f}Yi{suffix}"

    with db_conn.session as s:
        stmt = text(f"select count(*) from {table};")
        res = s.execute(stmt)
    total_count = next(res)[0]
    size = db_path.stat().st_size
    return st.write(
        f"#### Sqlite database:\n\n - {total_count:_} rows\n- {sizeof_fmt(size)}"
    )


def tail_log(log_path):
    p = subprocess.run(["tail", str(log_path)], capture_output=True)
    st.markdown("#### Log file:")
    st.text(p.stdout.decode("utf-8").strip())


chart_nb_records(DB_CONN, TABLE, "day")
chart_nb_records(DB_CONN, TABLE, "week")
st.divider()
db_stats(DB_CONN, TABLE, DB_PATH)
tail_log(LOG_PATH)
