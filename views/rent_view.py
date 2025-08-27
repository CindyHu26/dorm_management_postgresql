import streamlit as st
import pandas as pd
from data_models import finance_model, dormitory_model, employer_dashboard_model

def render():
    """渲染「房租管理」頁面"""
    st.header("我司管理宿舍 - 房租總覽與批次更新")

    # 【核心修改】將函式定義移到 render 函式的頂部
    @st.cache_data
    def get_my_dorms():
        return dormitory_model.get_my_company_dorms_for_selection()

    @st.cache_data
    def get_all_employers():
        return employer_dashboard_model.get_all_employers()

    # --- 1. 篩選條件選擇 ---
    st.subheader("步驟一：選擇篩選方式與目標")
    
    filter_type = st.radio(
        "請選擇篩選方式：",
        ["依宿舍地址", "依雇主"],
        horizontal=True
    )

    filters = {
        "filter_by": "",
        "values": []
    }
    
    if filter_type == "依宿舍地址":
        my_dorms = get_my_dorms()
        if not my_dorms:
            st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍。")
            return

        dorm_options = {d['id']: d['original_address'] for d in my_dorms}
        
        selected_dorm_ids = st.multiselect(
            "您可以選擇一個或多個宿舍進行管理：",
            options=list(dorm_options.keys()),
            format_func=lambda x: dorm_options[x]
        )
        if selected_dorm_ids:
            filters["filter_by"] = "dorm"
            filters["values"] = selected_dorm_ids

    elif filter_type == "依雇主":
        my_employers = get_all_employers()
        if not my_employers:
            st.warning("目前資料庫中沒有任何雇主資料可供篩選。")
            return
            
        selected_employers = st.multiselect(
            "您可以選擇一個或多個雇主進行管理：",
            options=my_employers
        )
        if selected_employers:
            filters["filter_by"] = "employer"
            filters["values"] = selected_employers

    if not filters["values"]:
        st.info("請從上方選擇至少一個篩選目標以載入人員資料。")
        return

    # --- 2. 人員房租總覽 ---
    st.subheader("步驟二：檢視人員房租")
    # 傳遞 filters 字典給後端
    workers_df = finance_model.get_workers_for_rent_management(filters)

    if workers_df.empty:
        st.info("在您選擇的篩選條件下，目前沒有找到任何在住人員。")
    else:
        st.dataframe(workers_df, use_container_width=True, hide_index=True)

    # --- 3. 批次更新 ---
    st.subheader("步驟三：批次更新房租 (可選)")
    with st.form("batch_update_rent_form"):
        st.warning("注意：此操作將會修改所有上方列表顯示的人員的房租，請謹慎操作。")
        
        update_nulls_only = st.checkbox("✅ 只更新目前房租為「未設定」的人員")
        
        c1, c2, c3 = st.columns(3)
        
        old_rent = c1.number_input("原房租金額", min_value=0, step=100, help="請輸入您要變更的『舊』租金金額。", disabled=update_nulls_only)
        new_rent = c2.number_input("新房租金額", min_value=0, step=100, help="請輸入要更新成的『新』租金金額。")
        
        submitted = c3.form_submit_button("執行批次更新")
        
        if submitted:
            effective_old_rent = 0 if update_nulls_only else old_rent

            if not update_nulls_only and effective_old_rent == new_rent:
                st.error("新舊房租金額相同，無需更新。")
            else:
                with st.spinner("正在更新中..."):
                    success, message = finance_model.batch_update_rent(
                        filters, 
                        effective_old_rent, 
                        new_rent, 
                        update_nulls=update_nulls_only
                    )
                    if success:
                        st.success(message)
                        # 因為函式已經被移到外部，所以現在可以安全地呼叫 .clear()
                        get_my_dorms.clear()
                        get_all_employers.clear()
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)