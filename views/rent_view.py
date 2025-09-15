import streamlit as st
import pandas as pd
from datetime import date
from data_models import finance_model, dormitory_model, employer_dashboard_model

def render():
    """渲染「工人費用管理」頁面"""
    st.header("我司管理宿舍 - 工人費用總覽與批次更新")

    @st.cache_data
    def get_my_dorms():
        return dormitory_model.get_my_company_dorms_for_selection()

    @st.cache_data
    def get_all_employers():
        return employer_dashboard_model.get_all_employers()

    # --- : 移除 st.radio，改為並列篩選 ---
    st.subheader("步驟一：設定篩選條件")
    
    col1, col2 = st.columns(2)
    
    # 宿舍篩選
    my_dorms = get_my_dorms()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍。")
        return
    dorm_options = {d['id']: d['original_address'] for d in my_dorms}
    selected_dorm_ids = col1.multiselect(
        "篩選宿舍地址 (可不選，或多選)",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options[x]
    )

    # 雇主篩選
    my_employers = get_all_employers()
    if not my_employers:
        st.warning("目前資料庫中沒有任何雇主資料可供篩選。")
        return
    selected_employers = col2.multiselect(
        "篩選雇主 (可不選，或多選)",
        options=my_employers
    )

    # 組合篩選條件
    filters = {
        "dorm_ids": selected_dorm_ids,
        "employer_names": selected_employers
    }

    if not selected_dorm_ids and not selected_employers:
        st.info("請至少選擇一個「宿舍地址」或「雇主」來載入人員資料。")
        return
    # --- 修改結束 ---

    # --- 2. 人員費用總覽 ---
    st.subheader("步驟二：檢視人員費用")
    workers_df = finance_model.get_workers_for_fee_management(filters)

    if workers_df.empty:
        st.info("在您選擇的篩選條件下，目前沒有找到任何在住人員。")
    else:
        st.dataframe(workers_df, width='stretch', hide_index=True)

    # --- 3. 批次更新 ---
    st.subheader("步驟三：批次更新費用 (可選)")
    with st.form("batch_update_fee_form"):
        st.warning("注意：此操作將會修改所有上方列表顯示的人員的費用，請謹慎操作。")
        
        fee_type_options = {"月費(房租)": "monthly_fee", "水電費": "utilities_fee", "清潔費": "cleaning_fee"}
        fee_type_display = st.selectbox("選擇要更新的費用類型", options=list(fee_type_options.keys()))
        fee_type_db_col = fee_type_options[fee_type_display]

        update_nulls_only = st.checkbox(f"✅ 只更新目前「{fee_type_display}」為『未設定』的人員")
        
        c1, c2, c3 = st.columns(3)
        
        old_fee = c1.number_input(f"原「{fee_type_display}」金額", min_value=0, step=100, help=f"請輸入您要變更的『舊』{fee_type_display}金額。", disabled=update_nulls_only)
        new_fee = c2.number_input(f"新「{fee_type_display}」金額", min_value=0, step=100, help=f"請輸入要更新成的『新』{fee_type_display}金額。")
        
        change_date = c3.date_input("生效日期", value=date.today(), help="費用變更從此日期開始生效。若為首次設定，則不會早於人員的入住日期。")
        
        submitted = st.form_submit_button("執行批次更新")
        
        if submitted:
            effective_old_fee = 0 if update_nulls_only else old_fee

            if not update_nulls_only and effective_old_fee == new_fee:
                st.error(f"新舊{fee_type_display}金額相同，無需更新。")
            else:
                with st.spinner("正在更新中..."):
                    success, message = finance_model.batch_update_worker_fees(
                        filters, 
                        fee_type_db_col,
                        fee_type_display,
                        effective_old_fee, 
                        new_fee,
                        change_date,
                        update_nulls=update_nulls_only
                    )
                    if success:
                        st.success(message)
                        get_my_dorms.clear()
                        get_all_employers.clear()
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)