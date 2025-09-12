import streamlit as st
import pandas as pd
from data_models import placement_model, dormitory_model

def render():
    """渲染「空床位智慧查詢」頁面"""
    st.header("空床位智慧查詢")
    st.info("此工具能協助您根據新進員工的條件，快速找到我司管理宿舍中所有符合入住條件的空床位。")

    # --- 1. 篩選條件 ---
    @st.cache_data
    def get_my_dorms():
        return dormitory_model.get_my_company_dorms_for_selection()

    my_dorms = get_my_dorms()
    
    c1, c2 = st.columns(2)
    
    gender_filter = c1.selectbox(
        "預計入住員工性別：",
        options=["女", "男"]
    )
    
    dorm_options = {d['id']: d['original_address'] for d in my_dorms} if my_dorms else {}
    
    # --- 【核心修改】將 selectbox 更換為 multiselect ---
    selected_dorm_ids = c2.multiselect(
        "指定宿舍地址 (可選，預設為全部)：",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options.get(x)
    )
    # --- 修改結束 ---
    
    st.markdown("---")

    # --- 2. 顯示結果 ---
    if st.button(f"🔍 查詢可入住的『{gender_filter}性』床位", type="primary"):
        with st.spinner("正在為您進行智能配對，請稍候..."):
            filters = {
                "gender": gender_filter,
                "dorm_ids": selected_dorm_ids # 將選擇的宿舍ID列表傳入
            }
            results_df = placement_model.find_available_rooms(filters)

        st.subheader("查詢結果")
        if results_df.empty:
            st.success(f"在您選擇的範圍內，找不到符合條件的 {gender_filter}性 空床位。")
        else:
            st.info(f"找到 {len(results_df)} 間有合適空床位的房間，已按空床位數排序：")
            st.dataframe(
                results_df.sort_values(by="空床位數", ascending=False),
                width="stretch",
                hide_index=True
            )