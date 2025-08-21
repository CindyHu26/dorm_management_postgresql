import streamlit as st
import pandas as pd
from data_models import finance_model, dormitory_model

def render():
    """渲染「房租管理」頁面"""
    st.header("我司管理宿舍 - 房租總覽與批次更新")

    # --- 1. 宿舍選擇 ---
    st.subheader("步驟一：選擇要管理的宿舍")
    
    @st.cache_data
    def get_my_dorms():
        return dormitory_model.get_my_company_dorms_for_selection()

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

    if not selected_dorm_ids:
        st.info("請從上方選擇至少一個宿舍以載入人員資料。")
        return

    # --- 2. 人員房租總覽 ---
    st.subheader("步驟二：檢視人員房租")
    workers_df = finance_model.get_workers_for_rent_management(selected_dorm_ids)

    if workers_df.empty:
        st.info("選定的宿舍中目前沒有在住人員。")
    else:
        st.dataframe(workers_df, use_container_width=True, hide_index=True)

    # --- 3. 批次更新 ---
    st.subheader("步驟三：批次更新房租 (可選)")
    with st.form("batch_update_rent_form"):
        st.warning("注意：此操作將會修改所有符合條件人員的房租，請謹慎操作。")
        
        update_nulls_only = st.checkbox("✅ 只更新目前房租為「未設定」的人員")
        
        c1, c2, c3 = st.columns(3)
        
        # 當勾選上方選項時，自動禁用「原房租金額」
        old_rent = c1.number_input("原房租金額", min_value=0, step=100, help="請輸入您要變更的『舊』租金金額。", disabled=update_nulls_only)
        new_rent = c2.number_input("新房租金額", min_value=0, step=100, help="請輸入要更新成的『新』租金金額。")
        
        submitted = c3.form_submit_button("執行批次更新")
        
        if submitted:
            # 根據是否勾選，決定 old_rent 的值
            effective_old_rent = 0 if update_nulls_only else old_rent

            if not update_nulls_only and effective_old_rent == new_rent:
                st.error("新舊房租金額相同，無需更新。")
            else:
                with st.spinner("正在更新中..."):
                    # 將 update_nulls_only 旗標傳遞給後端
                    success, message = finance_model.batch_update_rent(
                        selected_dorm_ids, 
                        effective_old_rent, 
                        new_rent, 
                        update_nulls=update_nulls_only
                    )
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                    else:
                        st.error(message)