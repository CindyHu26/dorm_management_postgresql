import streamlit as st
import pandas as pd
from datetime import date
from data_models import placement_model, dormitory_model

def render():
    """渲染「空床位智慧查詢」頁面"""
    st.info("此工具能協助您根據新進員工的條件與指定日期，快速找到我司管理宿舍中所有符合入住條件的空床位。")

    # --- 1. 載入選項 ---
    @st.cache_data
    def get_data_for_filters():
        # 取得宿舍列表 (用於指定特定宿舍)
        dorms = dormitory_model.get_my_company_dorms_for_selection()
        # 取得地點對照表 (用於縣市區域連動)
        loc_df = dormitory_model.get_locations_dataframe()
        return dorms, loc_df

    my_dorms, loc_df = get_data_for_filters()
    
    # 宿舍選項 (保留全部，不隨縣市連動，方便跨區選)
    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms} if my_dorms else {}
    
    # 縣市選項 (排除空值)
    all_cities = sorted(loc_df['city'].dropna().unique().tolist()) if not loc_df.empty else []

    # --- 2. 篩選條件排版 ---
    c_main1, c_main2 = st.columns([1, 2])

    with c_main1:
        st.markdown("##### 核心條件")
        gender_filter = st.selectbox("員工性別", options=["女", "男"])
        query_date = st.date_input("查詢日期", value=date.today())

    with c_main2:
        st.markdown("##### 地點範圍 (滿足任一條件即顯示)")
        loc_c1, loc_c2 = st.columns(2)
        
        # A. 縣市選擇
        selected_cities = loc_c1.multiselect("篩選縣市", options=all_cities, placeholder="不限")
        
        # B. 區域選擇 (根據縣市連動)
        if selected_cities:
            # 如果有選縣市，只顯示該縣市底下的區域
            filtered_districts = sorted(loc_df[loc_df['city'].isin(selected_cities)]['district'].dropna().unique().tolist())
        else:
            # 如果沒選縣市，顯示所有區域
            filtered_districts = sorted(loc_df['district'].dropna().unique().tolist()) if not loc_df.empty else []

        selected_districts = loc_c2.multiselect("篩選區域", options=filtered_districts, placeholder="不限")
        
        # C. 特定宿舍 (保持獨立，不被篩選掉，滿足跨縣市需求)
        selected_dorm_ids = st.multiselect(
            "指定特定宿舍 (可跨縣市搜尋)",
            options=list(dorm_options.keys()),
            format_func=lambda x: dorm_options.get(x),
            placeholder="不指定"
        )
    
    st.markdown("---")

    # --- 3. 執行查詢 ---
    if st.button(f"🔍 搜尋空床位", type="primary"):
        with st.spinner("正在搜尋符合條件的空床位..."):
            filters = {
                "gender": gender_filter,
                "query_date": query_date,
                "dorm_ids": selected_dorm_ids,
                "cities": selected_cities,     # 傳入縣市
                "districts": selected_districts # 傳入區域
            }
            results_df = placement_model.find_available_rooms(filters)

        st.subheader(f"查詢結果 ({query_date})")
        if results_df.empty:
            st.warning("找不到符合條件的空床位。請嘗試放寬地點篩選條件。")
        else:
            st.success(f"共找到 {len(results_df)} 間有空床位的房間：")
            
            # 調整顯示欄位順序
            display_cols = ["宿舍地址", "縣市", "區域", "房號", "空床位數", "房間性別政策", "房內現住人員", "房間備註"]
            
            st.dataframe(
                results_df[display_cols].sort_values(by=["縣市", "區域", "空床位數"], ascending=[True, True, False]),
                width="stretch",
                hide_index=True
            )