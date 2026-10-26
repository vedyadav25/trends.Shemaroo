import xml.etree.ElementTree as ET
import streamlit as st
import pandas as pd
import requests
import re
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from pytrends.request import TrendReq

# Persistent local history for Google Trends snapshots. The database is saved beside this script.
GOOGLE_HISTORY_DB = Path.cwd() / "google_trends_history.sqlite3"

def save_google_snapshot(dataframe):
    """Append a timestamped Google Trends snapshot to the local SQLite database."""
    if dataframe is None or dataframe.empty:
        return 0
    saved = dataframe.copy()
    if "Snapshot Time" not in saved.columns:
        saved["Snapshot Time"] = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(GOOGLE_HISTORY_DB) as connection:
        saved.to_sql("google_trends_snapshots", connection, if_exists="append", index=False)
    return len(saved)

def read_google_history(country=None, limit=5000):
    """Read recent saved snapshots from the local SQLite database."""
    if not GOOGLE_HISTORY_DB.exists():
        return pd.DataFrame()
    with sqlite3.connect(GOOGLE_HISTORY_DB) as connection:
        try:
            if country:
                result = pd.read_sql_query(
                    "SELECT * FROM google_trends_snapshots WHERE Country = ? ORDER BY rowid DESC LIMIT ?",
                    connection, params=(country, int(limit))
                )
            else:
                result = pd.read_sql_query(
                    "SELECT * FROM google_trends_snapshots ORDER BY rowid DESC LIMIT ?",
                    connection, params=(int(limit),)
                )
        except (pd.errors.DatabaseError, sqlite3.OperationalError):
            return pd.DataFrame()
    return result

#Header
st.set_page_config(
    page_title="TrendScope Shemaroo",
    page_icon="📈",
    layout="wide"
)

st.title("📈 TrendScope Shemaroo")
st.caption("Google and YouTube Trends")

google_tab, youtube_tab, keyword_tab, explore_youtube_tab, live_tab = st.tabs([
    "🔎 Google Trends",
    "▶️ YouTube Trends",
    "🔑 YouTube Keyword Research",
    "📺 Google Trends Explore (YouTube)",
    "🔥 Google Trends Live"
])


# ---------------- GOOGLE TRENDS -----------------------------------------------------------------------------------------------------
with google_tab:
    st.header("Google🔵🔴🟡🟢 Trends")
    st.link_button(
        "Open full Google Trends Trending Now",
        "https://trends.google.com/trending?geo=IN"
    )
    st.caption(
        "Sort Google’s trending topics by its original ranking, approximate "
        "traffic, or publication time."
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        country_options = {
            "India": "IN",
            "United States": "US",
            "United Kingdom": "GB",
            "Canada": "CA",
            "Australia": "AU",
            "Pakistan": "PK",
            "United Arab Emirates": "AE",
            "Singapore": "SG",
            "Japan": "JP",
            "Germany": "DE"
        }
        country_name = st.selectbox(
            "Select Country", list(country_options.keys()), key="google_country"
        )

    with col2:
        time_filter = st.selectbox(
            "Select Time Period",
            ["Latest available trends", "Past 24 hours", "Past 7 days"],
            key="google_time_filter"
        )

    with col3:
        category_options = {
            "All Categories": None,
            "Entertainment": 3,
            "Business": 12,
            "Technology / Computers & Electronics": 5,
            "Sports": 20,
            "Health": 45,
            "Science": 174,
            "Top Stories": 0,
            "Autos & Vehicles": 1,
            "Beauty & Fitness": 44,
            "Books & Literature": 22,
            "Food & Drink": 71,
            "Games": 8,
            "Shopping": 18,
            "Travel": 67
        }
        category_name = st.selectbox(
            "Select Category", list(category_options.keys()), key="google_category"
        )

    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        date_filter = st.selectbox(
            "Started trending",
            [
                "Past 4 hours",
                "Past 24 hours",
                "Past 48 hours",
                "Past 7 days",
                "All available dates"
            ],
            index=1,
            key="google_date_filter"
        )

    with filter_col2:
        sort_by = st.selectbox(
            "Sort topics by",
            [
                "Relevance (Google's original order)",
                "Title (A–Z)",
                "Recency (newest first)",
                "Approximate search traffic (highest first)"
            ],
            key="google_sort_by"
        )

    with filter_col3:
        rows_per_page = st.selectbox(
            "Rows per page",
            [15, 25, 50],
            index=1,
            key="google_rows_per_page"
        )

    search_topic = st.text_input(
        "Search trends",
        placeholder="Enter a topic or keyword...",
        key="google_search_topic"
    )
    st.caption(
        "Active-only status and percentage growth are not reliably included "
        "in the RSS data source. Use the official Google Trends page for "
        "those live fields and detailed trend breakdowns."
    )

    def parse_approx_traffic(value):
        """Convert labels such as '200K+' into sortable numeric values."""
        if value is None:
            return 0
        text = str(value).strip().upper().replace(",", "").replace("+", "")
        match = re.search(r"(\d+(?:\.\d+)?)\s*([KMB]?)", text)
        if not match:
            return 0
        number = float(match.group(1))
        multiplier = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
        return number * multiplier.get(match.group(2), 1)

    control_a, control_b, control_c = st.columns([1, 1, 1])
    with control_a:
        manual_refresh = st.button("Load / refresh Google Trends", key="load_google_trends")
    with control_b:
        auto_save_enabled = st.checkbox(
            "Automatically save snapshots", value=False, key="google_auto_save_enabled",
            help="Keep this Streamlit app running. Google Trends is fetched at the selected interval and appended to a local SQLite database."
        )
    with control_c:
        auto_save_minutes = st.selectbox(
            "Save interval", [5, 10, 15, 30, 60], index=2,
            format_func=lambda minutes: f"Every {minutes} minutes",
            key="google_auto_save_interval"
        )

    auto_refresh_available = False
    if auto_save_enabled:
        try:
            from streamlit_autorefresh import st_autorefresh
            st_autorefresh(interval=60_000, key="google_trends_periodic_tick")
            auto_refresh_available = True
        except ImportError:
            st.warning("Automatic saving needs streamlit-autorefresh. In your terminal run: python -m pip install streamlit-autorefresh")

    last_fetch_text = st.session_state.get("google_trends_last_saved_at")
    should_fetch = manual_refresh
    if auto_save_enabled and auto_refresh_available:
        last_fetch = st.session_state.get("google_trends_last_fetch_epoch", 0)
        import time
        if time.time() - last_fetch >= auto_save_minutes * 60:
            should_fetch = True

    def _google_timestamp(value):
        """Convert a Google Trends timestamp array/value into UTC pandas time."""
        if isinstance(value, list) and value:
            value = value[0]
        if value in (None, ""):
            return pd.NaT
        try:
            numeric = float(value)
            # Google may return epoch seconds or milliseconds.
            unit = "ms" if numeric > 10_000_000_000 else "s"
            return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
        except (TypeError, ValueError):
            return pd.to_datetime(value, utc=True, errors="coerce")

    def _find_google_trend_rows(obj):
        """Find the largest list of positional trend records in Google's batch response."""
        candidates = []
        def walk(node):
            if isinstance(node, list):
                valid = [item for item in node if (
                    isinstance(item, list) and len(item) >= 10
                    and isinstance(item[0], str) and item[0].strip()
                    and isinstance(item[9], list)
                )]
                if valid:
                    candidates.append(valid)
                for child in node:
                    walk(child)
            elif isinstance(node, dict):
                for child in node.values():
                    walk(child)
        walk(obj)
        return max(candidates, key=len) if candidates else []

    def fetch_full_trending_now(geo, hours, country_label, category_label):
        """Fetch the fuller Trending Now page dataset; RSS is a limited fallback."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36",
            "Referer": f"https://trends.google.com/trending?geo={geo}&hl=en-US",
        }
        endpoint = (
            "https://trends.google.com/_/TrendsUi/data/batchexecute"
            "?rpcids=i0OFE&source-path=%2Ftrending&hl=en-US&rt=c"
        )
        inner_args = json.dumps([None, None, geo, 0, "en-US", int(hours)], separators=(",", ":"))
        form_payload = json.dumps([[ ["i0OFE", inner_args, None, "generic"] ]], separators=(",", ":"))
        source_name = "Google Trending Now page"
        try:
            response = requests.post(
                endpoint, data={"f.req": form_payload}, headers=headers, timeout=30
            )
            response.raise_for_status()
            body = response.text.lstrip()
            if body.startswith(")]}'"):
                body = body[4:].lstrip("\r\n")
            parsed = None
            # batchexecute uses length-prefixed JSON chunks; inspect each chunk safely.
            lines = body.splitlines()
            for i, line in enumerate(lines):
                if line.strip().isdigit() and i + 1 < len(lines):
                    try:
                        chunk = json.loads(lines[i + 1])
                        for entry in chunk if isinstance(chunk, list) else []:
                            if isinstance(entry, list) and len(entry) > 2 and entry[0] == "wrb.fr" and entry[1] == "i0OFE":
                                parsed = json.loads(entry[2]) if isinstance(entry[2], str) else entry[2]
                                break
                        if parsed is not None:
                            break
                    except (json.JSONDecodeError, TypeError):
                        continue
            if parsed is None:
                # Some response variants are a single JSON payload after the prefix.
                try:
                    outer = json.loads(body)
                    for entry in outer if isinstance(outer, list) else []:
                        if isinstance(entry, list) and len(entry) > 2 and entry[0] == "wrb.fr" and entry[1] == "i0OFE":
                            parsed = json.loads(entry[2]) if isinstance(entry[2], str) else entry[2]
                            break
                except (json.JSONDecodeError, TypeError):
                    pass
            trend_items = _find_google_trend_rows(parsed) if parsed is not None else []
            if not trend_items:
                raise ValueError("Google's Trending Now response format was not recognized")

            rows = []
            for rank, item in enumerate(trend_items, start=1):
                title = str(item[0]).strip()
                if not title:
                    continue
                started = _google_timestamp(item[3] if len(item) > 3 else None)
                ended = _google_timestamp(item[4] if len(item) > 4 else None)
                volume = item[6] if len(item) > 6 else ""
                growth = item[8] if len(item) > 8 else None
                breakdown = item[9] if len(item) > 9 and isinstance(item[9], list) else []
                category_ids = item[10] if len(item) > 10 and isinstance(item[10], list) else []
                rows.append({
                    "Rank": rank,
                    "Trending Topic": title,
                    "Traffic": str(volume) + "+" if str(volume).isdigit() else str(volume or ""),
                    "Published": started,
                    "Started At": started,
                    "Ended At": ended,
                    "Growth (%)": growth,
                    "Related Searches": ", ".join(str(x) for x in breakdown if x),
                    "Category IDs": ", ".join(str(x) for x in category_ids),
                    "Country": country_label,
                    "Category": category_label,
                    "Source": source_name,
                })
            if not rows:
                raise ValueError("Google returned no trend rows")
            return pd.DataFrame(rows)
        except Exception as primary_error:
            # RSS remains useful as a fallback, but is a shorter list and may not match page ranking.
            rss_response = requests.get(
                "https://trends.google.com/trending/rss", params={"geo": geo},
                headers=headers, timeout=30
            )
            rss_response.raise_for_status()
            rss_root = ET.fromstring(rss_response.content)
            rss_namespace = {"ht": "https://trends.google.com/trending/rss"}
            fallback_rows = []
            for item in rss_root.findall("./channel/item"):
                title = item.findtext("title", default="").strip()
                if not title:
                    continue
                fallback_rows.append({
                    "Rank": len(fallback_rows) + 1,
                    "Trending Topic": title,
                    "Traffic": item.findtext("ht:approx_traffic", default="", namespaces=rss_namespace),
                    "Published": pd.to_datetime(item.findtext("pubDate", default=""), errors="coerce", utc=True),
                    "Started At": pd.to_datetime(item.findtext("pubDate", default=""), errors="coerce", utc=True),
                    "Ended At": pd.NaT,
                    "Growth (%)": None,
                    "Related Searches": "",
                    "Category IDs": "",
                    "Country": country_label,
                    "Category": category_label,
                    "Source": "Google Trends RSS fallback (limited)",
                })
            if fallback_rows:
                st.warning(
                    "Google's full Trending Now feed could not be read, so a limited RSS list is shown. "
                    "Its relevance order may differ from the website. Details: " + str(primary_error)
                )
                return pd.DataFrame(fallback_rows)
            raise primary_error

    if should_fetch:
        try:
            hours_by_filter = {
                "Past 4 hours": 4,
                "Past 24 hours": 24,
                "Past 48 hours": 48,
                "Past 7 days": 168,
                "All available dates": 168
            }
            hours = hours_by_filter.get(date_filter, 24)
            selected_category = category_options[category_name]
            df_google = fetch_full_trending_now(
                country_options[country_name], hours, country_name, category_name
            )
            # Apply category locally because Google's page endpoint may not filter it server-side.
            if selected_category is not None and not df_google.empty:
                if df_google["Source"].astype(str).str.contains("RSS fallback", case=False).any():
                    st.warning("Category filtering is unavailable in the limited RSS fallback; showing the available RSS topics instead.")
                else:
                    wanted = str(selected_category)
                    df_google = df_google[
                        df_google["Category IDs"].fillna("").apply(
                            lambda value: wanted in [part.strip() for part in str(value).split(",")]
                        )
                    ].copy()
                    if not df_google.empty:
                        df_google["Rank"] = range(1, len(df_google) + 1)

            if not df_google.empty:
                snapshot_time = datetime.now(timezone.utc).isoformat()
                df_google["Snapshot Time"] = snapshot_time
                df_google["Published"] = pd.to_datetime(
                    df_google["Published"], errors="coerce", utc=True
                )
                df_google["Traffic (approx.)"] = df_google["Traffic"].apply(parse_approx_traffic)
                st.session_state["google_trends_data"] = df_google
                st.session_state["google_trends_context"] = (
                    country_name, category_name, time_filter
                )
                saved_count = save_google_snapshot(df_google)
                import time
                st.session_state["google_trends_last_fetch_epoch"] = time.time()
                st.session_state["google_trends_last_saved_at"] = snapshot_time
                st.success(
                    f"Fetched {len(df_google)} topics from {df_google['Source'].iloc[0]} "
                    f"and saved {saved_count} snapshot rows to local history."
                )
            else:
                st.session_state["google_trends_data"] = pd.DataFrame()
                st.session_state["google_trends_context"] = (
                    country_name, category_name, time_filter
                )
                st.warning("No trends matched this country, time window, and category.")

        except Exception as e:
            st.error(f"Google Trends error: {e}")

    # Keep results when the user changes the sort dropdown.
    df_google = st.session_state.get("google_trends_data")
    if df_google is not None:
        df_display = df_google.copy()
        if not df_display.empty:
            now = pd.Timestamp.now(tz="UTC")
            if date_filter == "Past 4 hours":
                df_display = df_display[
                    df_display["Published"].notna()
                    & (df_display["Published"] >= now - pd.Timedelta(hours=4))
                ]
            elif date_filter == "Past 24 hours":
                df_display = df_display[
                    df_display["Published"].notna()
                    & (df_display["Published"] >= now - pd.Timedelta(hours=24))
                ]
            elif date_filter == "Past 48 hours":
                df_display = df_display[
                    df_display["Published"].notna()
                    & (df_display["Published"] >= now - pd.Timedelta(hours=48))
                ]
            elif date_filter == "Past 7 days":
                df_display = df_display[
                    df_display["Published"].notna()
                    & (df_display["Published"] >= now - pd.Timedelta(days=7))
                ]

            if search_topic.strip():
                df_display = df_display[
                    df_display["Trending Topic"].str.contains(
                        search_topic.strip(), case=False, na=False, regex=False
                    )
                ]

            if sort_by == "Approximate search traffic (highest first)":
                df_display = df_display.sort_values(
                    "Traffic (approx.)", ascending=False, kind="stable"
                )
            elif sort_by == "Recency (newest first)":
                df_display = df_display.sort_values(
                    "Published", ascending=False, na_position="last", kind="stable"
                )
            elif sort_by == "Title (A–Z)":
                df_display = df_display.sort_values(
                    "Trending Topic", ascending=True,
                    key=lambda s: s.str.casefold(), kind="stable"
                )
            # Relevance keeps the original order supplied by Google.
            df_display["Published"] = df_display["Published"].astype(str)
            df_display["Published"] = df_display["Published"].astype(str)
            df_display = df_display.drop(
                columns=["Traffic (approx.)", "Snapshot Time", "Started At", "Ended At", "Category IDs"],
                errors="ignore"
            )

            total_matches = len(df_display)
            total_pages = max(1, (total_matches + rows_per_page - 1) // rows_per_page)
            page_number = st.number_input(
                "Page", min_value=1, max_value=total_pages,
                value=1, step=1, key="google_page_number"
            )
            start_row = (int(page_number) - 1) * rows_per_page
            page_df = df_display.iloc[start_row:start_row + rows_per_page]

            context = st.session_state.get("google_trends_context")
            if context:
                st.success(
                    f"{total_matches} matching topics | {context[0]} | {context[1]} "
                    f"| Page {int(page_number)} of {total_pages}"
                )

            st.dataframe(page_df, use_container_width=True, hide_index=True)
            st.download_button(
                "Download filtered Google Trends CSV",
                df_display.to_csv(index=False).encode("utf-8-sig"),
                file_name="google_trends.csv",
                mime="text/csv",
                key="download_google_trends"
            )
            st.caption(
                "Relevance preserves the order returned by Google's Trending Now page endpoint. "
                "Traffic is an approximate search-volume signal, not an exact count. If the app "
                "falls back to RSS, the list is shorter and may not match Google's full page."
            )
        else:
            st.warning(
                "No topics match this publication-date filter. Try All available dates "
                "or reload trends for another country/category."
            )


    if auto_save_enabled:
        st.info(
            f"Automatic saving is enabled at {auto_save_minutes}-minute intervals. "
            "Keep this app running; snapshots are saved on this computer, not to Google's servers."
        )
    if last_fetch_text:
        st.caption(f"Most recent saved snapshot: {last_fetch_text}")

    st.subheader("Saved Google Trends History")
    history_country = st.selectbox(
        "History country", ["All countries"] + list(country_options.keys()),
        key="google_history_country"
    )
    history_data = read_google_history(
        None if history_country == "All countries" else history_country, limit=5000
    )
    if not history_data.empty:
        st.caption(f"Showing {len(history_data)} most recent saved rows. Each row includes its snapshot time, so changes across refreshes can be compared.")
        st.dataframe(history_data, use_container_width=True, hide_index=True)
        st.download_button(
            "Download saved Google Trends history CSV",
            history_data.to_csv(index=False).encode("utf-8-sig"),
            file_name="google_trends_history.csv",
            mime="text/csv",
            key="download_google_trends_history"
        )
    else:
        st.info("No saved history yet. Click Load / refresh Google Trends, or enable automatic saving.")

# ---------------- YOUTUBE KEYWORD RESEARCH -----------------------------------------------------------------------------------------------
with keyword_tab:
    st.header("🔑 YouTube Keyword Research")
    st.caption(
        "Discover related keywords and compare relative YouTube interest."
    )

    country_options_kw = {
        "India": "IN",
        "United States": "US",
        "United Kingdom": "GB",
        "Canada": "CA",
        "Australia": "AU"
    }

    selected_country_kw = st.selectbox(
        "Select Country",
        list(country_options_kw.keys()),
        key="kw_country"
    )
    selected_period_kw = st.selectbox(
            "Select Time Period",
            [
                "Past 7 days",
                "Past 30 days",
                "Past 90 days",
                "Past 12 months"
            ],
            index=2,
            key="kw_period"
        )

    timeframe_options = {
            "Past 7 days": "now 7-d",
            "Past 30 days": "today 1-m",
            "Past 90 days": "today 3-m",
            "Past 12 months": "today 12-m"
        }

    if st.button("Load YouTube Keyword Trends", key="kw_load"):
            discovery_terms = [
                "trending",
                "news",
                "movies",
                "songs",
                "comedy",
                "cricket",
                "viral",
                "shorts",
                "entertainment",
                "technology"
            ]

            all_keywords = []

            try:
                with st.spinner("Discovering related keywords..."):
                    for seed in discovery_terms:
                        response = requests.get(
                            "https://suggestqueries.google.com/complete/search",
                            params={
                                "client": "firefox",
                                "ds": "yt",
                                "q": seed,
                                "gl": country_options_kw[selected_country_kw]
                            },
                            headers={"User-Agent": "Mozilla/5.0"},
                            timeout=20
                        )
                        response.raise_for_status()

                        for keyword in response.json()[1]:
                            all_keywords.append(keyword)

                unique_keywords = list(dict.fromkeys(all_keywords))

                if not unique_keywords:
                    st.warning("No keyword suggestions returned.")
                else:
                    st.success(
                        f"Discovered {len(unique_keywords)} unique keywords."
                    )

                    # Trends compares up to five terms per request.
                    trend_rows = []
                    progress = st.progress(0)

                    terms_to_check = unique_keywords[:20]
                    batches = [
                        terms_to_check[i:i + 5]
                        for i in range(0, len(terms_to_check), 5)
                    ]

                    for batch_number, batch in enumerate(batches):
                        try:
                            trend_client = TrendReq(
                                hl="en-US",
                                tz=330,
                                timeout=(10, 25)
                            )

                            trend_client.build_payload(
                                kw_list=batch,
                                timeframe=timeframe_options[selected_period_kw],
                                geo=country_options_kw[selected_country_kw],
                                gprop="youtube"
                            )

                            trends = trend_client.interest_over_time()

                            if not trends.empty:
                                if "isPartial" in trends.columns:
                                    trends = trends.drop(
                                        columns=["isPartial"]
                                    )

                                for keyword in batch:
                                    if keyword in trends.columns:
                                        values = trends[keyword]
                                        nonzero = values[values > 0]

                                        trend_rows.append({
                                            "Keyword": keyword,
                                            "Latest Interest": (
                                                int(values.iloc[-1])
                                                if len(values) else None
                                            ),
                                            "Average Interest": round(
                                                float(values.mean()), 1
                                            ),
                                            "Peak Interest": int(values.max()),
                                            "Nonzero Trend Periods": int(
                                                (values > 0).sum()
                                            )
                                        })
                        except Exception:
                            # Keep suggestions even if Trends fails.
                            pass

                        progress.progress(
                            (batch_number + 1) / len(batches)
                        )

                    suggestions_df = pd.DataFrame({
                        "Keyword": unique_keywords
                    })

                    if trend_rows:
                        scores_df = pd.DataFrame(trend_rows)
                        final_df = suggestions_df.merge(
                            scores_df,
                            on="Keyword",
                            how="left"
                        )
                    else:
                        final_df = suggestions_df.copy()
                        final_df["Latest Interest"] = None
                        final_df["Average Interest"] = None
                        final_df["Peak Interest"] = None
                        final_df["Nonzero Trend Periods"] = None

                    final_df.insert(
                        0, "Rank",
                        range(1, len(final_df) + 1)
                    )

                    final_df["Country"] = selected_country_kw

                    st.subheader("Keyword Interest Table")
                    st.dataframe(
                        final_df,
                        use_container_width=True,
                        hide_index=True
                    )

                    st.caption(
                        "Interest scores are relative Google Trends indices "
                        "for YouTube Search, on a 0–100 scale. Zero can mean "
                        "insufficient data. Scores from separate batches may "
                        "not be directly comparable. Rank is display order, "
                        "not a search-volume ranking."
                    )

                    st.download_button(
                        "Download Keyword Trends CSV",
                        final_df.to_csv(index=False).encode("utf-8-sig"),
                        file_name="youtube_keyword_trends.csv",
                        mime="text/csv",
                        key="kw_download_trends"
                    )

            except Exception as e:
                st.error("Unable to discover YouTube keyword trends.")
                st.caption(str(e))


# ---------------- YOUTUBE TRENDS ----------------

with youtube_tab:
    st.header("📺 YouTube Popular Videos")

    st.caption(
        "Opens Google Trends Explore with YouTube Search selected "
        "for the last 7 days."
    )

    api_key = st.secrets.get("YOUTUBE_API_KEY", "")

    region = st.selectbox(
        "Country",
        ["IN", "US", "GB", "CA", "AU"],
        index=0
    )

    max_results = st.slider(
        "Number of videos",
        min_value=10,
        max_value=50,
        value=25
    )

    if st.button("Load YouTube Trends"):
        if not api_key:
            st.error(
                "YouTube API key is missing from Streamlit Secrets. "
                "Please check your app settings."
            )
        else:
            try:
                with st.spinner("Fetching popular YouTube videos..."):
                    url = "https://www.googleapis.com/youtube/v3/videos"

                    params = {
                        "part": "snippet,statistics",
                        "chart": "mostPopular",
                        "regionCode": region,
                        "maxResults": max_results,
                        "key": api_key.strip()
                    }

                    response = requests.get(
                        url,
                        params=params,
                        timeout=30
                    )
                    response.raise_for_status()
                    items = response.json().get("items", [])

                    rows = []
                    for item in items:
                        snippet = item.get("snippet", {})
                        stats = item.get("statistics", {})

                        rows.append({
                            "Video ID": item.get("id", ""),
                            "Title": snippet.get("title", ""),
                            "Channel": snippet.get("channelTitle", ""),
                            "Published At": snippet.get("publishedAt", ""),
                            "Views": int(stats.get("viewCount", 0)),
                            "Likes": int(stats.get("likeCount", 0)),
                            "Comments": int(stats.get("commentCount", 0)),
                            "Video URL": (
                                "https://www.youtube.com/watch?v="
                                + item.get("id", "")
                            )
                        })

                    if rows:
                        df = pd.DataFrame(rows)

                        st.dataframe(
                            df,
                            use_container_width=True,
                            hide_index=True
                        )

                        st.download_button(
                            "Download YouTube Trends CSV",
                            df.to_csv(index=False).encode("utf-8"),
                            "youtube_trends.csv",
                            "text/csv"
                        )
                    else:
                        st.warning("No YouTube videos returned.")

            except requests.HTTPError:
                st.error(
                    f"YouTube API error ({response.status_code}). "
                    "Check the API key, quota, and API settings."
                )
            except Exception as e:
                st.error("Unable to load YouTube trends.")
                st.caption(str(e))

    st.link_button(
        "Open YouTube Charts",
        "https://www.youtube.com/feed/trending"
    )


# ---------------- GOOGLE TRENDS EXPLORE: YOUTUBE SEARCH ----------------
with explore_youtube_tab:
    st.header("Google Trends Explore — YouTube Search")
    st.write(
        "Explore relative YouTube Search interest in this tab with a chart, "
        "filterable table, sorting, and CSV export. Values are Google Trends "
        "indices (0–100), not absolute search volumes."
    )
    st.link_button(
        "Open Google Trends Explore — YouTube (Last 7 Days)",
        "https://trends.google.com/trends/explore?date=now%207-d&gprop=youtube&hl=en-US"
    )

    explore_country_options = {
        "India": "IN",
        "Worldwide": "",
        "United States": "US",
        "United Kingdom": "GB",
        "Canada": "CA",
        "Australia": "AU"
    }
    explore_time_options = {
        "Past 7 days": "now 7-d",
        "Past 30 days": "today 1-m",
        "Past 90 days": "today 3-m",
        "Past 12 months": "today 12-m",
        "Past 5 years": "today 5-y"
    }

    control_col1, control_col2 = st.columns(2)
    with control_col1:
        explore_terms_input = st.text_input(
            "Search keyword(s)",
            value="",
            placeholder="e.g. cricket, Bollywood songs, cooking",
            help="Enter up to five comma-separated search terms to compare.",
            key="explore_youtube_terms"
        )
        explore_country_name = st.selectbox(
            "Country / region",
            list(explore_country_options.keys()),
            index=0,
            key="explore_youtube_country"
        )
    with control_col2:
        explore_period_name = st.selectbox(
            "Date range",
            list(explore_time_options.keys()),
            index=0,
            key="explore_youtube_period"
        )
        explore_sort_by = st.selectbox(
            "Sort table by",
            ["Date (oldest first)", "Date (newest first)", "Interest (highest first)"],
            key="explore_youtube_sort"
        )

    explore_table_filter = st.text_input(
        "Filter table rows",
        placeholder="Filter dates or values...",
        key="explore_youtube_table_filter"
    )

    if st.button("Load YouTube Search Interest", key="load_explore_youtube"):
        explore_terms = list(dict.fromkeys(
            term.strip() for term in explore_terms_input.split(",") if term.strip()
        ))[:5]
        if not explore_terms:
            st.warning("Enter at least one keyword before loading the chart.")
        else:
            try:
                with st.spinner("Loading Google Trends YouTube Search data..."):
                    trends_client = TrendReq(hl="en-US", tz=330, timeout=(10, 25))
                    trends_client.build_payload(
                        kw_list=explore_terms,
                        timeframe=explore_time_options[explore_period_name],
                        geo=explore_country_options[explore_country_name],
                        gprop="youtube"
                    )
                    explore_data = trends_client.interest_over_time()
                    if explore_data.empty:
                        st.session_state["explore_youtube_data"] = pd.DataFrame()
                        st.warning("Google Trends returned no data for these keywords and filters. Try another term or date range.")
                    else:
                        explore_data = explore_data.drop(columns=["isPartial"], errors="ignore")
                        explore_data.index.name = "Date"
                        explore_data = explore_data.reset_index()
                        st.session_state["explore_youtube_data"] = explore_data
                        st.session_state["explore_youtube_terms_loaded"] = explore_terms
                        st.session_state["explore_youtube_context"] = (explore_country_name, explore_period_name)
            except Exception as e:
                st.error("Unable to load Google Trends YouTube Search data. Try again in a moment or use the official link above.")
                st.caption(str(e))

    explore_data = st.session_state.get("explore_youtube_data")
    if explore_data is not None and not explore_data.empty:
        explore_display = explore_data.copy()
        loaded_terms = st.session_state.get("explore_youtube_terms_loaded", [])
        if explore_table_filter.strip():
            row_mask = explore_display.astype(str).apply(
                lambda column: column.str.contains(
                    explore_table_filter.strip(), case=False, na=False, regex=False
                )
            ).any(axis=1)
            explore_display = explore_display[row_mask]

        if explore_sort_by == "Date (newest first)":
            explore_display = explore_display.sort_values("Date", ascending=False)
        elif explore_sort_by == "Interest (highest first)" and loaded_terms:
            explore_display = explore_display.sort_values(loaded_terms[0], ascending=False)
        else:
            explore_display = explore_display.sort_values("Date", ascending=True)

        context = st.session_state.get("explore_youtube_context")
        if context:
            st.caption(f"Region: {context[0]} | Date range: {context[1]} | Search terms: {', '.join(loaded_terms)}")

        st.subheader("YouTube Search Interest Chart")
        chart_data = explore_data.set_index("Date")
        st.line_chart(chart_data[loaded_terms] if loaded_terms else chart_data, use_container_width=True)

        st.subheader("Interest Data Table")
        st.dataframe(explore_display, use_container_width=True, hide_index=True)
        st.download_button(
            "Download filtered YouTube Search CSV",
            explore_display.to_csv(index=False).encode("utf-8-sig"),
            file_name="google_trends_youtube_search.csv",
            mime="text/csv",
            key="download_explore_youtube_csv"
        )
        st.caption("Google Trends values are normalized relative interest scores from 0 to 100 for the selected request. They do not represent exact search counts; comparisons are most meaningful for terms loaded together.")
    else:
        st.info("Enter one or more keywords, choose a country and date range, then select **Load YouTube Search Interest** to display the chart and table.")


# ---------------- GOOGLE TRENDS LIVE ----------------
with live_tab:
    st.header("🔥 Google Trends Live")
    st.caption(
        "Explore currently available trending searches and compare keyword interest "
        "over time. Google Trends data is periodically updated, not a second-by-second live feed."
    )
    st.link_button(
        "Open official Google Trends Trending Now",
        "https://trends.google.com/trending?geo=IN"
    )

    live_country_options = {
        "India": "IN",
        "United States": "US",
        "United Kingdom": "GB",
        "Canada": "CA",
        "Australia": "AU",
        "Pakistan": "PK",
        "United Arab Emirates": "AE",
        "Singapore": "SG",
        "Japan": "JP",
        "Germany": "DE",
        "Worldwide": ""
    }
    live_category_options = {
        "All Categories": None,
        "Entertainment": 3,
        "Business": 12,
        "Technology / Computers & Electronics": 5,
        "Sports": 20,
        "Health": 45,
        "Science": 174,
        "Top Stories": 0,
        "Autos & Vehicles": 1,
        "Beauty & Fitness": 44,
        "Books & Literature": 22,
        "Food & Drink": 71,
        "Games": 8,
        "Shopping": 18,
        "Travel": 67
    }
    live_period_options = {
        "Past 4 hours": 4,
        "Past 24 hours": 24,
        "Past 48 hours": 48,
        "Past 7 days": 168
    }

    st.subheader("1. Trending searches")
    live_col1, live_col2, live_col3 = st.columns(3)
    with live_col1:
        live_country_name = st.selectbox(
            "Country for trending searches",
            list(live_country_options.keys()),
            index=0,
            key="live_trending_country"
        )
    with live_col2:
        live_period_name = st.selectbox(
            "Trending time window",
            list(live_period_options.keys()),
            index=1,
            key="live_trending_period"
        )
    with live_col3:
        live_category_name = st.selectbox(
            "Trending category",
            list(live_category_options.keys()),
            index=0,
            key="live_trending_category"
        )

    live_filter_col1, live_filter_col2 = st.columns(2)
    with live_filter_col1:
        live_search_filter = st.text_input(
            "Filter trending topics",
            placeholder="Type a topic or keyword...",
            key="live_trending_filter"
        )
    with live_filter_col2:
        live_sort = st.selectbox(
            "Sort trending topics",
            ["Google's original order", "Topic (A–Z)", "Traffic (highest first)"],
            key="live_trending_sort"
        )

    auto_refresh_options = ["Off", "5 minutes", "10 minutes", "15 minutes"]
    auto_refresh_choice = st.selectbox(
        "Automatic refresh",
        auto_refresh_options,
        index=0,
        help="Automatic refresh requires the optional streamlit-autorefresh package. Manual refresh is always available.",
        key="live_auto_refresh"
    )
    try:
        from streamlit_autorefresh import st_autorefresh
        auto_refresh_available = True
    except ImportError:
        st_autorefresh = None
        auto_refresh_available = False

    auto_refresh_count = None
    if auto_refresh_choice != "Off":
        if auto_refresh_available:
            interval_minutes = int(auto_refresh_choice.split()[0])
            auto_refresh_count = st_autorefresh(
                interval=interval_minutes * 60 * 1000,
                key="live_trends_autorefresh_counter"
            )
        else:
            st.info(
                "To enable automatic refresh, install the optional package with "
                "`pip install streamlit-autorefresh`. You can still refresh manually."
            )

    auto_trigger = False
    if auto_refresh_count is not None:
        last_counter = st.session_state.get("live_last_autorefresh_count")
        if auto_refresh_count != last_counter:
            auto_trigger = True
            st.session_state["live_last_autorefresh_count"] = auto_refresh_count

    refresh_live_clicked = st.button(
        "🔄 Refresh trending searches now",
        key="refresh_live_trending"
    )

    if refresh_live_clicked or auto_trigger:
        try:
            live_params = {
                "geo": live_country_options[live_country_name],
                "hours": live_period_options[live_period_name]
            }
            selected_live_category = live_category_options[live_category_name]
            if selected_live_category is not None:
                live_params["category"] = selected_live_category

            live_response = requests.get(
                "https://trends.google.com/trending/rss",
                params=live_params,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=30
            )
            live_response.raise_for_status()
            live_root = ET.fromstring(live_response.content)
            live_namespace = {"ht": "https://trends.google.com/trending/rss"}
            live_rows = []
            for item in live_root.findall("./channel/item"):
                topic = item.findtext("title", default="").strip()
                if not topic:
                    continue
                traffic_label = item.findtext(
                    "ht:approx_traffic", default="", namespaces=live_namespace
                )
                published_text = item.findtext("pubDate", default="")
                traffic_text = str(traffic_label).upper().replace(",", "").replace("+", "")
                traffic_match = re.search(r"(\d+(?:\.\d+)?)\s*([KMB]?)", traffic_text)
                traffic_value = 0
                if traffic_match:
                    traffic_value = float(traffic_match.group(1)) * {
                        "": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000
                    }.get(traffic_match.group(2), 1)
                live_rows.append({
                    "Rank": len(live_rows) + 1,
                    "Trending Topic": topic,
                    "Approx. Traffic": traffic_label,
                    "Traffic (numeric estimate)": traffic_value,
                    "Published": published_text,
                    "Country": live_country_name,
                    "Category": live_category_name
                })

            st.session_state["live_trending_data"] = pd.DataFrame(live_rows)
            st.session_state["live_trending_context"] = (
                live_country_name, live_period_name, live_category_name
            )
            if live_rows:
                st.success(f"Loaded {len(live_rows)} trending topics.")
            else:
                st.warning("Google Trends returned no trending topics for these filters.")
        except Exception as e:
            st.error("Unable to refresh Google Trends trending searches.")
            st.caption(str(e))

    live_df = st.session_state.get("live_trending_data")
    if live_df is not None:
        live_display = live_df.copy()
        if not live_display.empty:
            if live_search_filter.strip():
                live_display = live_display[
                    live_display["Trending Topic"].str.contains(
                        live_search_filter.strip(), case=False, na=False, regex=False
                    )
                ]
            if live_sort == "Topic (A–Z)":
                live_display = live_display.sort_values(
                    "Trending Topic", key=lambda col: col.str.casefold(), kind="stable"
                )
            elif live_sort == "Traffic (highest first)":
                live_display = live_display.sort_values(
                    "Traffic (numeric estimate)", ascending=False, kind="stable"
                )

            live_context = st.session_state.get("live_trending_context")
            if live_context:
                st.caption(
                    f"Loaded for {live_context[0]} | {live_context[1]} | {live_context[2]}"
                )

            chart_df = live_display.head(15).copy()
            if not chart_df.empty:
                st.subheader("Trending topics chart")
                st.bar_chart(
                    chart_df.set_index("Trending Topic")[["Traffic (numeric estimate)"]],
                    use_container_width=True
                )
            st.dataframe(
                live_display.drop(columns=["Traffic (numeric estimate)"], errors="ignore"),
                use_container_width=True,
                hide_index=True
            )
            st.download_button(
                "Download trending searches CSV",
                live_display.drop(columns=["Traffic (numeric estimate)"], errors="ignore")
                    .to_csv(index=False).encode("utf-8-sig"),
                file_name="google_trends_live_searches.csv",
                mime="text/csv",
                key="download_live_trending_csv"
            )
        else:
            st.info("No trending-search rows are currently loaded. Click Refresh trending searches now.")

    st.divider()
    st.subheader("2. Keyword search interest over time")
    st.caption(
        "Enter up to five keywords. Scores are relative Google Trends indices (0–100), "
        "not exact search counts."
    )
    interest_col1, interest_col2 = st.columns(2)
    with interest_col1:
        live_keywords_input = st.text_input(
            "Keywords to compare",
            placeholder="e.g. cricket, Bollywood, artificial intelligence",
            key="live_interest_keywords"
        )
        live_interest_country_name = st.selectbox(
            "Country for keyword interest",
            list(live_country_options.keys()),
            index=0,
            key="live_interest_country"
        )
    with interest_col2:
        live_interest_period_name = st.selectbox(
            "Keyword interest date range",
            ["Past 7 days", "Past 30 days", "Past 90 days", "Past 12 months", "Past 5 years"],
            index=0,
            key="live_interest_period"
        )
        live_interest_sort = st.selectbox(
            "Sort keyword table by",
            ["Date (oldest first)", "Date (newest first)", "First keyword interest (highest first)"],
            key="live_interest_sort"
        )

    live_interest_timeframes = {
        "Past 7 days": "now 7-d",
        "Past 30 days": "today 1-m",
        "Past 90 days": "today 3-m",
        "Past 12 months": "today 12-m",
        "Past 5 years": "today 5-y"
    }

    if st.button("Load / refresh keyword interest", key="load_live_keyword_interest"):
        live_terms = list(dict.fromkeys(
            term.strip() for term in live_keywords_input.split(",") if term.strip()
        ))[:5]
        if not live_terms:
            st.warning("Enter at least one keyword.")
        else:
            try:
                with st.spinner("Loading keyword interest from Google Trends..."):
                    live_trend_client = TrendReq(hl="en-US", tz=330, timeout=(10, 25))
                    live_trend_client.build_payload(
                        kw_list=live_terms,
                        timeframe=live_interest_timeframes[live_interest_period_name],
                        geo=live_country_options[live_interest_country_name],
                        gprop=""
                    )
                    live_interest_data = live_trend_client.interest_over_time()
                    if live_interest_data.empty:
                        st.session_state["live_keyword_interest_data"] = pd.DataFrame()
                        st.session_state["live_keyword_interest_terms"] = live_terms
                        st.warning("No keyword-interest data was returned. Try different keywords or a wider date range.")
                    else:
                        live_interest_data = live_interest_data.drop(
                            columns=["isPartial"], errors="ignore"
                        )
                        live_interest_data.index.name = "Date"
                        live_interest_data = live_interest_data.reset_index()
                        st.session_state["live_keyword_interest_data"] = live_interest_data
                        st.session_state["live_keyword_interest_terms"] = live_terms
                        st.session_state["live_keyword_interest_context"] = (
                            live_interest_country_name, live_interest_period_name
                        )
            except Exception as e:
                st.error("Unable to load Google Trends keyword interest. Try again or use the official Google Trends link.")
                st.caption(str(e))

    live_interest_data = st.session_state.get("live_keyword_interest_data")
    if live_interest_data is not None and not live_interest_data.empty:
        live_interest_display = live_interest_data.copy()
        live_loaded_terms = st.session_state.get("live_keyword_interest_terms", [])
        if live_interest_sort == "Date (newest first)":
            live_interest_display = live_interest_display.sort_values("Date", ascending=False)
        elif live_interest_sort == "First keyword interest (highest first)" and live_loaded_terms:
            live_interest_display = live_interest_display.sort_values(
                live_loaded_terms[0], ascending=False
            )
        else:
            live_interest_display = live_interest_display.sort_values("Date", ascending=True)

        live_interest_context = st.session_state.get("live_keyword_interest_context")
        if live_interest_context:
            st.caption(
                f"Keyword interest region: {live_interest_context[0]} | "
                f"Date range: {live_interest_context[1]} | "
                f"Keywords: {', '.join(live_loaded_terms)}"
            )
        st.line_chart(
            live_interest_display.set_index("Date")[live_loaded_terms],
            use_container_width=True
        )
        st.dataframe(
            live_interest_display,
            use_container_width=True,
            hide_index=True
        )
        st.download_button(
            "Download keyword interest CSV",
            live_interest_display.to_csv(index=False).encode("utf-8-sig"),
            file_name="google_trends_live_keyword_interest.csv",
            mime="text/csv",
            key="download_live_keyword_interest_csv"
        )
    else:
        st.info("Enter keywords and select Load / refresh keyword interest to see the chart and table.")


st.divider()
st.caption("TrendScope | Google + YouTube")

#
import subprocess
import sys

subprocess.Popen([
    sys.executable, "-m", "streamlit", "run",
    r"D:\TrendScope_India\app.py",
    "--server.address", "0.0.0.0",
    "--server.port", "8502"
])
