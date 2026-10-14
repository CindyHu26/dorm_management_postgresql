import pandas as pd
import streamlit as st

from data_models import dormitory_model, employer_workplace_model


@st.cache_data
def get_filter_options_df():
    return dormitory_model.get_map_coordinate_filter_options()


@st.cache_data
def get_editor_df(search_term="", primary_manager="全部", city="全部", district="全部"):
    return dormitory_model.get_map_coordinate_editor_dataframe(
        search_term=search_term,
        primary_manager=primary_manager,
        city=city,
        district=district
    )


@st.cache_data
def get_workplace_editor_df(search_term=""):
    records = []
    term = (search_term or "").strip().lower()

    def to_float(value):
        if value is None or pd.isna(value):
            return None
        return float(value)

    for wp in employer_workplace_model.get_all_workplaces():
        row = {
            "id": wp.get("id"),
            "雇主編號": wp.get("employer_id") or "",
            "雇主簡稱": wp.get("employer_name") or "",
            "工作地址": wp.get("address") or "",
            "郵遞區號": wp.get("postal_code") or "",
            "緯度": to_float(wp.get("latitude")),
            "經度": to_float(wp.get("longitude")),
        }
        searchable = " ".join(
            str(row.get(col, ""))
            for col in ["雇主編號", "雇主簡稱", "工作地址", "郵遞區號"]
        ).lower()
        if term and term not in searchable:
            continue
        records.append(row)

    return pd.DataFrame(
        records,
        columns=["id", "雇主編號", "雇主簡稱", "工作地址", "郵遞區號", "緯度", "經度"],
    )


def _parse_coordinate_pair(raw_value):
    raw = str(raw_value).strip()
    normalized_text = raw.replace("，", ",").replace("、", ",").replace(" ", "")
    parts = [part for part in normalized_text.split(",") if part != ""]
    if len(parts) != 2:
        raise ValueError("格式不正確，請使用 `lat,lng` 或 `lng,lat`。")

    try:
        first = float(parts[0])
        second = float(parts[1])
    except ValueError as exc:
        raise ValueError("座標不是有效數字。") from exc

    if 20 <= first <= 27 and 118 <= second <= 123:
        return first, second
    if 118 <= first <= 123 and 20 <= second <= 27:
        return second, first

    raise ValueError("座標不在台灣常用範圍內。")


def _render_dorm_coordinate_editor():
    st.info("此頁面專門維護宿舍的地圖顯示地址、緯度與經度。座標請填十進位格式，台灣常見範圍約為緯度 20-27、經度 118-123。")

    filter_df = get_filter_options_df()

    manager_options = ["全部"] + sorted([v for v in filter_df["primary_manager"].unique().tolist() if v]) if not filter_df.empty else ["全部"]

    c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
    search_term = c1.text_input("搜尋宿舍", placeholder="可輸入宿舍編號、名稱、原始地址、正規化地址")
    selected_manager = c2.selectbox("主要管理人", options=manager_options)

    city_source_df = filter_df.copy()
    if selected_manager != "全部" and not city_source_df.empty:
        city_source_df = city_source_df[city_source_df["primary_manager"] == selected_manager]
    city_options = ["全部"] + sorted([v for v in city_source_df["city"].unique().tolist() if v]) if not city_source_df.empty else ["全部"]
    selected_city = c3.selectbox("縣市", options=city_options)

    district_source_df = city_source_df.copy()
    if selected_city != "全部" and not district_source_df.empty:
        district_source_df = district_source_df[district_source_df["city"] == selected_city]
    district_options = ["全部"] + sorted([v for v in district_source_df["district"].unique().tolist() if v]) if not district_source_df.empty else ["全部"]
    selected_district = c4.selectbox("區域", options=district_options)

    editor_df = get_editor_df(
        search_term=search_term.strip(),
        primary_manager=selected_manager,
        city=selected_city,
        district=selected_district
    )

    if editor_df.empty:
        st.warning("目前沒有符合條件的宿舍資料。")
        return

    if "座標貼上" not in editor_df.columns:
        editor_df["座標貼上"] = ""

    st.caption(f"目前顯示 {len(editor_df)} 筆宿舍。可直接在表格中批次編輯，清空緯度與經度可視為取消定位。")
    st.caption("「座標貼上」可直接貼 `25.0479240,121.5170810`。若格式看起來像 `經度,緯度`，系統會自動判斷並交換。")

    with st.form("map_coordinate_editor_form"):
        edited_df = st.data_editor(
            editor_df,
            key="map_coordinate_editor",
            hide_index=True,
            width="stretch",
            column_config={
                "id": None,
                "宿舍編號": st.column_config.TextColumn("宿舍編號", disabled=True),
                "宿舍名稱": st.column_config.TextColumn("宿舍名稱", disabled=True),
                "原始地址": st.column_config.TextColumn("原始地址", disabled=True, width="large"),
                "正規化地址": st.column_config.TextColumn("正規化地址", disabled=True, width="large"),
                "縣市": st.column_config.TextColumn("縣市", disabled=True),
                "區域": st.column_config.TextColumn("區域", disabled=True),
                "主要管理人": st.column_config.TextColumn("主要管理人", disabled=True),
                "地圖顯示地址": st.column_config.TextColumn("地圖顯示地址", help="可自訂地圖顯示用地址。留空可改回系統地址。", width="large"),
                "座標貼上": st.column_config.TextColumn("座標貼上", help="可直接貼上 lat,lng 或 lng,lat。儲存時會自動拆分。", width="medium"),
                "緯度": st.column_config.NumberColumn("緯度", format="%.7f", min_value=20.0, max_value=27.0),
                "經度": st.column_config.NumberColumn("經度", format="%.7f", min_value=118.0, max_value=123.0),
                "最後定位時間": st.column_config.DatetimeColumn("最後定位時間", format="YYYY-MM-DD HH:mm:ss", disabled=True),
            },
            disabled=[
                "宿舍編號", "宿舍名稱", "原始地址", "正規化地址",
                "縣市", "區域", "主要管理人", "最後定位時間"
            ]
        )

        submitted = st.form_submit_button("儲存座標變更")
        if submitted:
            normalized_df = edited_df.copy()

            for idx, row in normalized_df.iterrows():
                pasted_value = row.get("座標貼上")
                if pd.isna(pasted_value) or str(pasted_value).strip() == "":
                    continue

                try:
                    lat, lng = _parse_coordinate_pair(pasted_value)
                except ValueError as exc:
                    st.error(f"宿舍 ID {int(row['id'])} 的「座標貼上」{exc}")
                    return

                normalized_df.at[idx, "緯度"] = lat
                normalized_df.at[idx, "經度"] = lng

            for _, row in normalized_df.iterrows():
                lat = row.get("緯度")
                lng = row.get("經度")
                if pd.isna(lat) and pd.isna(lng):
                    continue
                if pd.isna(lat) or pd.isna(lng):
                    st.error(f"宿舍 ID {int(row['id'])} 的經緯度需成對填寫。")
                    return

            success, message = dormitory_model.batch_update_map_coordinates(normalized_df)
            if success:
                st.success(message)
                get_filter_options_df.clear()
                get_editor_df.clear()
                st.rerun()
            else:
                st.error(message)


def _render_workplace_coordinate_editor():
    st.info("此頁面維護雇主工作地址、郵遞區號與座標，供寄件與地圖找房使用。")

    search_term = st.text_input("搜尋雇主工作地址", placeholder="可輸入雇主編號、雇主簡稱、工作地址、郵遞區號")
    editor_df = get_workplace_editor_df(search_term=search_term.strip())

    if editor_df.empty:
        editor_df = pd.DataFrame(columns=["id", "雇主編號", "雇主簡稱", "工作地址", "郵遞區號", "座標貼上", "緯度", "經度"])
    else:
        for col in ["雇主編號", "雇主簡稱", "工作地址", "郵遞區號"]:
            if col in editor_df.columns:
                editor_df[col] = editor_df[col].fillna("")
        text_cols = [col for col in ["雇主編號", "雇主簡稱", "工作地址"] if col in editor_df.columns]
        if text_cols and editor_df[text_cols].astype(str).apply(lambda col: col.str.strip()).eq("").to_numpy().all():
            st.warning("雇主工作地址資料表已有資料列，但雇主編號、雇主簡稱與工作地址都是空白；請重新匯入或直接在下方表格補資料。")

    if "座標貼上" not in editor_df.columns:
        editor_df["座標貼上"] = ""

    st.caption(f"目前顯示 {len(editor_df)} 筆雇主工作地址。可直接修改既有資料，也可在表格底部新增一列。")
    st.caption("「座標貼上」可直接貼 `25.0479240,121.5170810` 或 `121.5170810,25.0479240`，儲存時會自動拆成緯度與經度。")

    with st.form("employer_workplace_editor_form"):
        edited_df = st.data_editor(
            editor_df,
            key="employer_workplace_editor",
            hide_index=True,
            width="stretch",
            num_rows="dynamic",
            column_config={
                "id": None,
                "雇主編號": st.column_config.TextColumn("雇主編號", width="small"),
                "雇主簡稱": st.column_config.TextColumn("雇主簡稱", required=True, width="small"),
                "工作地址": st.column_config.TextColumn("工作地址", width="large"),
                "郵遞區號": st.column_config.TextColumn("郵遞區號", width="small"),
                "座標貼上": st.column_config.TextColumn("座標貼上", help="可直接貼上 lat,lng 或 lng,lat。儲存時會自動拆分。", width="medium"),
                "緯度": st.column_config.NumberColumn("緯度", format="%.7f", min_value=20.0, max_value=27.0),
                "經度": st.column_config.NumberColumn("經度", format="%.7f", min_value=118.0, max_value=123.0),
            },
        )

        submitted = st.form_submit_button("儲存雇主工作地址")
        if submitted:
            normalized_df = edited_df.copy()

            for idx, row in normalized_df.iterrows():
                pasted_value = row.get("座標貼上")
                if pd.isna(pasted_value) or str(pasted_value).strip() == "":
                    continue

                employer_label = str(row.get("雇主簡稱") or row.get("雇主編號") or f"第 {idx + 1} 列")
                try:
                    lat, lng = _parse_coordinate_pair(pasted_value)
                except ValueError as exc:
                    st.error(f"{employer_label} 的「座標貼上」{exc}")
                    return

                normalized_df.at[idx, "緯度"] = lat
                normalized_df.at[idx, "經度"] = lng

            for idx, row in normalized_df.iterrows():
                employer_name = row.get("雇主簡稱")
                employer_id = row.get("雇主編號")
                address = row.get("工作地址")
                postal_code = row.get("郵遞區號")
                lat = row.get("緯度")
                lng = row.get("經度")

                is_blank_row = all(
                    pd.isna(value) or str(value).strip() == ""
                    for value in [employer_name, employer_id, address, postal_code, lat, lng]
                )
                if is_blank_row:
                    continue

                if pd.isna(employer_name) or str(employer_name).strip() == "":
                    st.error(f"第 {idx + 1} 列缺少雇主簡稱，請補上後再儲存。")
                    return
                if pd.isna(lat) and pd.isna(lng):
                    continue
                if pd.isna(lat) or pd.isna(lng):
                    st.error(f"{employer_name} 的經緯度需成對填寫。")
                    return

            success, message = employer_workplace_model.batch_update_workplaces(normalized_df)
            if success:
                st.success(message)
                get_workplace_editor_df.clear()
                st.rerun()
            else:
                st.error(message)


def render():
    dorm_tab, workplace_tab = st.tabs(["宿舍座標", "雇主工作地址"])
    with dorm_tab:
        _render_dorm_coordinate_editor()
    with workplace_tab:
        _render_workplace_coordinate_editor()
