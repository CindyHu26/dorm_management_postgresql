# /views/placement_view.py

import streamlit as st
import pandas as pd
from datetime import date # 引入 date 模組
from data_models import placement_model, dormitory_model

def render():
    """渲染「空床位智慧查詢」頁面"""
    st.header("空床位智慧查詢")
    st.info("此工具能協助您根據新進員工的條件與指定日期，快速找到我司管理宿舍中所有符合入住條件的空床位。")

    # --- 1. 篩選條件 ---
    @st.cache_data
    def get_my_dorms():
        return dormitory_model.get_my_company_dorms_for_selection()

    my_dorms = get_my_dorms()
    
    # --- 增加日期選擇器，並調整排版 ---
    c1, c2, c3 = st.columns(3)
    
    with c1:
        gender_filter = st.selectbox(
            "預計入住員工性別：",
            options=["女", "男"]
        )
    
    with c2:
        query_date = st.date_input(
            "查詢日期：",
            value=date.today(),
            help="系統將會查詢在此日期當天有空床位的房間。"
        )
    
    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms} if my_dorms else {}
    
    with c3:
        selected_dorm_ids = st.multiselect(
            "指定宿舍地址 (可選，預設為全部)：",
            options=list(dorm_options.keys()),
            format_func=lambda x: dorm_options.get(x)
        )
    
    st.markdown("---")

    # --- 2. 顯示結果 ---
    if st.button(f"🔍 查詢 {query_date} 可入住的『{gender_filter}性』床位", type="primary"):
        with st.spinner("正在為您進行智能配對，請稍候..."):
            # --- 【核心修改 2】將查詢日期傳入後端 ---
            filters = {
                "gender": gender_filter,
                "dorm_ids": selected_dorm_ids,
                "query_date": query_date 
            }
            results_df = placement_model.find_available_rooms(filters)

        st.subheader(f"查詢結果 ({query_date})")
        if results_df.empty:
            st.success(f"在您選擇的範圍內，於 {query_date} 找不到符合條件的 {gender_filter}性 空床位。")
        else:
            st.info(f"找到 {len(results_df)} 間在 {query_date} 當天有合適空床位的房間，已按空床位數排序：")
            st.dataframe(
                results_df.sort_values(by="空床位數", ascending=False),
                width="stretch",
                hide_index=True
            )