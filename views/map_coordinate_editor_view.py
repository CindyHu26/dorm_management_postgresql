import pandas as pd
import streamlit as st

from data_models import dormitory_model


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


def render():
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

                raw = str(pasted_value).strip()
                normalized_text = raw.replace("，", ",").replace("、", ",").replace(" ", "")
                parts = [part for part in normalized_text.split(",") if part != ""]
                if len(parts) != 2:
                    st.error(f"宿舍 ID {int(row['id'])} 的「座標貼上」格式不正確，請使用 `lat,lng` 或 `lng,lat`。")
                    return

                try:
                    first = float(parts[0])
                    second = float(parts[1])
                except ValueError:
                    st.error(f"宿舍 ID {int(row['id'])} 的「座標貼上」不是有效數字。")
                    return

                if 20 <= first <= 27 and 118 <= second <= 123:
                    lat, lng = first, second
                elif 118 <= first <= 123 and 20 <= second <= 27:
                    lat, lng = second, first
                else:
                    st.error(f"宿舍 ID {int(row['id'])} 的貼上座標不在台灣常用範圍內。")
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
