import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import json
import math
from datetime import date

from data_models import dormitory_model, placement_model, employer_workplace_model


@st.cache_data
def get_data_for_filters():
    dorms = dormitory_model.get_my_company_dorms_for_selection()
    loc_df = dormitory_model.get_locations_dataframe()
    return dorms, loc_df


def _build_map_dataframe(results_df: pd.DataFrame) -> pd.DataFrame:
    if results_df.empty:
        return pd.DataFrame()

    map_df = results_df.copy()
    map_df = map_df.dropna(subset=["緯度", "經度"])
    if map_df.empty:
        return pd.DataFrame()

    aggregated_df = (
        map_df.groupby(["dorm_id", "宿舍地址", "地圖顯示地址", "縣市", "區域", "緯度", "經度"], dropna=False)
        .agg(
            可入住房間數=("房號", "count"),
            總空床位數=("空床位數", "sum")
        )
        .reset_index()
    )
    aggregated_df["顯示地址"] = aggregated_df["地圖顯示地址"].fillna("").replace("", pd.NA).fillna(aggregated_df["宿舍地址"])
    aggregated_df["latitude"] = aggregated_df["緯度"].astype(float)
    aggregated_df["longitude"] = aggregated_df["經度"].astype(float)
    aggregated_df["label"] = aggregated_df["顯示地址"].fillna(aggregated_df["宿舍地址"])
    aggregated_df = aggregated_df.fillna("")
    return aggregated_df


def _calculate_distance_km(lat1, lng1, lat2, lng2):
    radius_km = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lng = math.radians(lng2 - lng1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


def _parse_coordinate(value):
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return float(text)


def _parse_coordinate_pair(value):
    if value is None:
        return None, None

    text = str(value).strip()
    if not text:
        return None, None

    normalized_text = text.replace("，", ",").replace("、", ",").replace(" ", "")
    parts = [part for part in normalized_text.split(",") if part != ""]
    if len(parts) != 2:
        raise ValueError("請使用 lat,lng 或 lng,lat 格式。")

    first = float(parts[0])
    second = float(parts[1])

    if 20 <= first <= 27 and 118 <= second <= 123:
        return first, second
    if 118 <= first <= 123 and 20 <= second <= 27:
        return second, first

    raise ValueError("座標不在台灣常用範圍內。")


def _render_leaflet_map(map_df: pd.DataFrame, center_info=None):
    map_records = map_df.to_dict(orient="records")
    center_lat = float(center_info["latitude"]) if center_info else float(map_df["latitude"].mean())
    center_lng = float(center_info["longitude"]) if center_info else float(map_df["longitude"].mean())
    safe_records = []
    for row in map_records:
        vacancy_count = int(row.get("總空床位數", 0))
        total_beds = int(row.get("總床位數", 0))
        current_occupants = int(row.get("目前入住數", 0))
        marker_color = "#2f9e44" if vacancy_count > 0 else "#c92a2a"
        dorm_name = str(row.get("宿舍名稱", "")).strip()
        address = str(row.get("顯示地址", ""))
        label_prefix = f"{dorm_name}/" if dorm_name else ""
        safe_records.append({
            "address": address,
            "dorm_name": dorm_name,
            "city": str(row.get("縣市", "")),
            "district": str(row.get("區域", "")),
            "room_count": int(row.get("可入住房間數", 0)),
            "vacancy_count": int(row.get("總空床位數", 0)),
            "total_beds": total_beds,
            "current_occupants": current_occupants,
            "latitude": float(row.get("latitude")),
            "longitude": float(row.get("longitude")),
            "label": f"{label_prefix}{address} ({current_occupants}人/{vacancy_count}床空)",
            "marker_color": marker_color,
        })

    html = f"""
    <link
        rel="stylesheet"
        href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
        integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="
        crossorigin=""
    />
    <style>
      #map {{
        width: 100%;
        height: 560px;
        border-radius: 12px;
        overflow: hidden;
      }}
      .addr-label {{
        background: rgba(255, 250, 245, 0.92);
        border: 1px solid #d8b8ab;
        border-radius: 6px;
        box-shadow: none;
        color: #222;
        font-size: 13px;
        font-weight: 600;
        line-height: 1.35;
        padding: 3px 7px;
        white-space: nowrap;
      }}
      .addr-label::before {{
        display: none;
      }}
    </style>
    <div id="map"></div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo="
        crossorigin=""></script>
    <script>
      const points = {json.dumps(safe_records, ensure_ascii=False)};
      const centerInfo = {json.dumps(center_info, ensure_ascii=False) if center_info else 'null'};
      const map = L.map('map').setView([{center_lat}, {center_lng}], 11);

      L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
      }}).addTo(map);

      const bounds = [];
      if (centerInfo) {{
        const centerMarker = L.marker([centerInfo.latitude, centerInfo.longitude]).addTo(map);
        centerMarker.bindPopup(`
          <div style="min-width:220px;line-height:1.5;">
            <div style="font-weight:700;">${{centerInfo.label}}</div>
            <div>查詢半徑: ${{centerInfo.radius_km}} 公里</div>
          </div>
        `);
        centerMarker.bindTooltip(centerInfo.label, {{
          permanent: true,
          direction: 'top',
          offset: [0, -10],
          className: 'addr-label'
        }});

        const circle = L.circle([centerInfo.latitude, centerInfo.longitude], {{
          radius: centerInfo.radius_km * 1000,
          color: '#1c7ed6',
          weight: 2,
          fillColor: '#74c0fc',
          fillOpacity: 0.12
        }}).addTo(map);
        bounds.push([centerInfo.latitude, centerInfo.longitude]);
      }}

      points.forEach((point) => {{
        const marker = L.circleMarker([point.latitude, point.longitude], {{
          radius: 7,
          color: point.marker_color,
          weight: 1,
          fillColor: point.marker_color,
          fillOpacity: 0.88
        }}).addTo(map);

        marker.bindPopup(`
          <div style="min-width:220px;line-height:1.5;">
            <div style="font-weight:700;">${{point.dorm_name ? point.dorm_name + '/' : ''}}${{point.address}}</div>
            <div>${{point.city}} ${{point.district}}</div>
            <div>總床位數: ${{point.total_beds}}</div>
            <div>目前入住數: ${{point.current_occupants}}</div>
            <div>可入住房間數: ${{point.room_count}}</div>
            <div>總空床位數: ${{point.vacancy_count}}</div>
          </div>
        `);

        marker.bindTooltip(point.label, {{
          permanent: true,
          direction: 'right',
          offset: [10, 0],
          className: 'addr-label'
        }});

        bounds.push([point.latitude, point.longitude]);
      }});

      if (bounds.length > 0) {{
        map.fitBounds(bounds, {{ padding: [30, 30] }});
      }}
    </script>
    """
    components.html(html, height=580)


def render():
    st.info("先用既有空床位邏輯做最小可用版。搜尋後會列出可入住房間，並把有座標的宿舍畫到地圖上。")

    my_dorms, loc_df = get_data_for_filters()

    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms} if my_dorms else {}
    all_cities = sorted(loc_df['city'].dropna().unique().tolist()) if not loc_df.empty else []

    c1, c2 = st.columns([1, 2])
    with c1:
        query_date = st.date_input("查詢日期", value=date.today())

    with c2:
        selected_cities = st.multiselect("限定縣市", options=all_cities, placeholder="不指定則全區")
        if selected_cities and not loc_df.empty:
            district_options = sorted(loc_df[loc_df["city"].isin(selected_cities)]["district"].dropna().unique().tolist())
        else:
            district_options = sorted(loc_df["district"].dropna().unique().tolist()) if not loc_df.empty else []
        selected_districts = st.multiselect("限定區域", options=district_options, placeholder="不指定則全區")
        selected_dorm_ids = st.multiselect(
            "指定特定宿舍",
            options=list(dorm_options.keys()),
            format_func=lambda x: dorm_options.get(x),
            placeholder="可跨縣市指定"
        )

    with st.expander("中心點範圍查詢", expanded=False):
        workplaces = employer_workplace_model.get_all_workplaces()
        workplace_by_id = {wp["id"]: wp for wp in workplaces if wp.get("latitude") and wp.get("longitude")}
        workplace_options = [None] + list(workplace_by_id.keys())

        def format_workplace_option(workplace_id):
            if workplace_id is None:
                return "自行輸入座標"
            wp = workplace_by_id.get(workplace_id, {})
            employer_id = str(wp.get("employer_id") or "無編號").strip()
            employer_name = str(wp.get("employer_name") or "").strip()
            address = str(wp.get("address") or "").strip()
            address_label = f" - {address}" if address else ""
            return f"{employer_id}｜{employer_name}{address_label} ({wp.get('latitude')}, {wp.get('longitude')})"

        selected_wp_id = st.selectbox(
            "選擇雇主工作地址作為中心",
            options=workplace_options,
            format_func=format_workplace_option,
            help="可在選單中輸入雇主編號、雇主簡稱或工作地址搜尋。"
        )

        default_coord = ""
        selected_wp = workplace_by_id.get(selected_wp_id) if selected_wp_id is not None else None
        if selected_wp:
            default_coord = f"{selected_wp['latitude']},{selected_wp['longitude']}"

        rc1, rc2 = st.columns([3, 1])
        # 使用 session_state 來動態更新輸入框的預設值
        center_coord_raw = rc1.text_input("中心座標 (lat,lng 或 lng,lat)", value=default_coord, placeholder="例如：25.0479240,121.5170810")
        radius_km = rc2.number_input("半徑公里", min_value=1.0, max_value=50.0, value=5.0, step=1.0)

    if st.button("搜尋地圖找房", type="primary"):
        with st.spinner("正在查詢可入住房間..."):
            filters = {
                "query_date": query_date,
                "dorm_ids": selected_dorm_ids,
                "cities": selected_cities,
                "districts": selected_districts
            }
            st.session_state["map_search_results_df"] = placement_model.find_available_rooms(filters)
            st.session_state["map_search_summary_df"] = placement_model.get_dorm_vacancy_summary(filters)
            st.session_state["map_search_query_date"] = query_date
            st.session_state["map_search_center_coord_raw"] = center_coord_raw
            st.session_state["map_search_radius_km"] = radius_km

    # ── 結果顯示區：讀取 session_state，與按鈕是否剛被點無關 ──────────────────
    if "map_search_summary_df" not in st.session_state:
        return

    results_df = st.session_state["map_search_results_df"]
    summary_df = st.session_state["map_search_summary_df"].copy()
    saved_query_date = st.session_state["map_search_query_date"]
    saved_center_coord_raw = st.session_state.get("map_search_center_coord_raw", "")
    saved_radius_km = st.session_state.get("map_search_radius_km", 5.0)

    st.subheader(f"查詢結果 ({saved_query_date})")
    if summary_df.empty:
        st.warning("找不到符合條件的宿舍資料。")
        return

    vacancy_filter = st.radio(
        "宿舍顯示篩選",
        ["全部", "有空床位", "無空床位"],
        horizontal=True
    )

    if vacancy_filter == "有空床位":
        summary_df = summary_df[summary_df["總空床位數"] > 0].copy()
    elif vacancy_filter == "無空床位":
        summary_df = summary_df[summary_df["總空床位數"] <= 0].copy()

    if summary_df.empty:
        st.warning("目前篩選條件下沒有符合的宿舍。")
        return

    summary_with_coords_df = summary_df.dropna(subset=["緯度", "經度"]).copy()
    map_df = summary_with_coords_df.copy()
    if not map_df.empty:
        map_df["顯示地址"] = map_df["地圖顯示地址"].fillna("").replace("", pd.NA).fillna(map_df["宿舍地址"])
        map_df["latitude"] = map_df["緯度"].astype(float)
        map_df["longitude"] = map_df["經度"].astype(float)
        map_df = map_df.fillna("")

    center_info = None
    center_lat = None
    center_lng = None
    if saved_center_coord_raw:
        try:
            center_lat, center_lng = _parse_coordinate_pair(saved_center_coord_raw)
        except ValueError:
            st.error("中心點座標格式不正確，請輸入 `lat,lng` 或 `lng,lat`。")
            return

    if center_lat is not None and center_lng is not None and not map_df.empty:
        center_info = {
            "label": "查詢中心點",
            "latitude": float(center_lat),
            "longitude": float(center_lng),
            "radius_km": float(saved_radius_km),
        }
        map_df["距離公里"] = map_df.apply(
            lambda row: _calculate_distance_km(center_info["latitude"], center_info["longitude"], row["latitude"], row["longitude"]),
            axis=1
        )
        summary_df = summary_df.merge(
            map_df[["dorm_id", "距離公里"]],
            on="dorm_id",
            how="left"
        )
        map_df = map_df[map_df["距離公里"] <= float(saved_radius_km)].copy()
        summary_df = summary_df[summary_df["距離公里"].notna() & (summary_df["距離公里"] <= float(saved_radius_km))].copy()
        if not results_df.empty:
            valid_dorm_ids = summary_df["dorm_id"].tolist()
            results_df = results_df[results_df["dorm_id"].isin(valid_dorm_ids)].copy()

    st.markdown("##### 宿舍地圖")
    if map_df.empty:
        if center_info and not summary_with_coords_df.empty:
            st.warning(f"查無 {float(saved_radius_km):.0f} 公里內的宿舍，請放大搜尋半徑或調整中心座標。")
        else:
            st.warning("目前查詢結果沒有可顯示的座標資料，請先到「地圖座標維護」補上經緯度。")
    else:
        _render_leaflet_map(map_df, center_info=center_info)

    st.markdown("##### 宿舍列表")

    # 若所有結果的縣市/區域相同，不重複顯示該欄
    show_city = summary_df["縣市"].nunique() > 1
    show_district = summary_df["區域"].nunique() > 1

    if vacancy_filter == "無空床位":
        display_cols = ["宿舍名稱", "宿舍地址"]
        if show_city:
            display_cols.append("縣市")
        if show_district:
            display_cols.append("區域")
        display_cols += ["房間數", "總床位數", "目前入住數", "總空床位數"]
        if "距離公里" in summary_df.columns:
            display_cols.append("距離公里")
        # 先對完整 summary_df 排序，再切欄（避免隱藏欄造成 KeyError）
        sort_cols = [c for c in ["縣市", "區域", "宿舍地址"] if c in summary_df.columns]
        display_df = summary_df.sort_values(
            by=sort_cols, ascending=[True] * len(sort_cols)
        )[display_cols]
    else:
        display_cols = ["宿舍名稱", "宿舍地址"]
        if show_city:
            display_cols.append("縣市")
        if show_district:
            display_cols.append("區域")
        display_cols += ["可入住房間數", "總空床位數", "全部空床位數", "總床位數", "目前入住數"]
        if "距離公里" in summary_df.columns:
            display_cols.append("距離公里")
        display_df = summary_df.sort_values(
            by=["總空床位數", "可入住房間數"], ascending=[False, False]
        )[display_cols]
    st.dataframe(
        display_df,
        width="stretch",
        hide_index=True
    )

    metric_c1, metric_c2, metric_c3 = st.columns(3)
    metric_c1.metric("宿舍數", len(summary_df))
    metric_c2.metric("可入住房間數", int(summary_df["可入住房間數"].sum()))
    metric_c3.metric("總空床位數", int(summary_df["總空床位數"].sum()))

    if not results_df.empty and vacancy_filter != "無空床位":
        st.markdown("##### 可入住房間明細")
        # 同樣：縣市/區域只有一個值時不顯示
        show_city_room = results_df["縣市"].nunique() > 1
        show_district_room = results_df["區域"].nunique() > 1
        room_display_cols = ["宿舍地址"]
        if show_city_room:
            room_display_cols.append("縣市")
        if show_district_room:
            room_display_cols.append("區域")
        room_display_cols += ["房號", "空床位數", "房間性別政策", "房內現住人員", "房間備註"]
        # 先對完整 results_df 排序，再切欄
        room_sort_cols = [c for c in ["縣市", "區域", "空床位數"] if c in results_df.columns]
        room_sort_asc = [True if c != "空床位數" else False for c in room_sort_cols]
        st.dataframe(
            results_df.sort_values(by=room_sort_cols, ascending=room_sort_asc)[room_display_cols],
            width="stretch",
            hide_index=True
        )

