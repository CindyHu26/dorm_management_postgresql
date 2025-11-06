# /views/batch_history_editor_view.py

import streamlit as st
import pandas as pd
from datetime import date
from data_models import finance_model, dormitory_model, worker_model, employer_dashboard_model

def render():
    """渲染「住宿/費用歷史批次編輯器」頁面"""
    st.header("住宿/費用歷史批次編輯器")
    st.info("此頁面用於批次「修改」已存在的歷史紀錄，例如修正錯誤的入住日或生效日。")
    st.warning("⚠️ **警告**：在此處所做的所有修改都會**永久覆蓋**歷史資料，並且會自動將相關員工設為「手動調整」狀態以防止爬蟲覆蓋。")

    # --- 步驟一：設定篩選條件 ---
    st.subheader("步驟一：篩選要編輯的員工")
    
    @st.cache_data
    def get_my_dorms():
        return dormitory_model.get_my_company_dorms_for_selection()

    @st.cache_data
    def get_all_employers():
        return employer_dashboard_model.get_all_employers()

    col1, col2 = st.columns(2)
    
    my_dorms = get_my_dorms()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍。")
        return
    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}
    selected_dorm_ids = col1.multiselect(
        "篩選宿舍地址 (可不選，或多選)",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options[x]
    )

    my_employers = get_all_employers()
    if not my_employers:
        st.warning("目前資料庫中沒有任何雇主資料可供篩選。")
        return
    selected_employers = col2.multiselect(
        "篩選雇主 (可不選，或多選)",
        options=my_employers
    )

    filters = {
        "dorm_ids": selected_dorm_ids,
        "employer_names": selected_employers
    }

    if not selected_dorm_ids and not selected_employers:
        st.info("請至少選擇一個「宿舍地址」或「雇主」來載入人員資料。")
        return

    # --- 步驟二：取得員工 ID ---
    @st.cache_data
    def get_filtered_workers_df(dorm_ids, employer_names):
        # 借用 finance_model 的函式來獲取符合條件的在住員工
        return finance_model.get_workers_for_fee_management({"dorm_ids": dorm_ids, "employer_names": employer_names})

    workers_df = get_filtered_workers_df(tuple(selected_dorm_ids), tuple(selected_employers))
    worker_ids_to_edit = workers_df['unique_id'].tolist()

    if not worker_ids_to_edit:
        st.info("在您選擇的篩選條件下，目前沒有找到任何在住人員。")
        return

    st.caption(f"已篩選出 {len(worker_ids_to_edit)} 位符合條件的在住人員。")
    st.markdown("---")
    st.subheader("步驟二：選擇要編輯的歷史紀錄類型")
    
    tab_accom, tab_fee = st.tabs(["🏠 編輯住宿歷史", "💰 編輯費用歷史"])

    # --- 頁籤1：編輯住宿歷史 ---
    with tab_accom:
        st.markdown("##### 篩選出人員的「住宿歷史」")
        
        @st.cache_data
        def get_accom_history(worker_ids_tuple):
            return worker_model.get_accommodation_history_for_workers(list(worker_ids_tuple))

        # 將 worker_ids 轉為 tuple 才能被 @st.cache_data 快取
        original_accom_df = get_accom_history(tuple(worker_ids_to_edit))

        if original_accom_df.empty:
            st.warning("這些員工沒有任何住宿歷史紀錄可供編輯。")
        else:
            st.caption("您可以直接在下列表格中修改「床位編號」、「入住日」、「離住日」和「備註」。")
            
            edited_accom_df = st.data_editor(
                original_accom_df,
                key="accom_editor",
                hide_index=True,
                width='stretch',
                column_config={
                    "id": st.column_config.NumberColumn("紀錄ID", disabled=True),
                    "worker_unique_id": None, # 隱藏
                    "員工姓名": st.column_config.TextColumn(disabled=True),
                    "宿舍地址": st.column_config.TextColumn(disabled=True),
                    "房號": st.column_config.TextColumn(disabled=True),
                    "床位編號": st.column_config.TextColumn(max_chars=20),
                    "入住日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "離住日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "備註": st.column_config.TextColumn(max_chars=255)
                },
                disabled=["id", "worker_unique_id", "員工姓名", "宿舍地址", "房號"]
            )
            
            if st.button("🚀 儲存住宿歷史變更", type="primary", key="save_accom_history"):
                with st.spinner("正在比對與儲存住宿歷史變更..."):
                    success, message = worker_model.batch_edit_history(
                        original_accom_df, 
                        edited_accom_df,
                        table_name="AccommodationHistory",
                        key_column="id",
                        columns_to_update=["worker_unique_id", "床位編號", "入住日", "離住日", "備註"]
                    )
                if success:
                    st.success(message)
                    get_accom_history.clear() # 清除快取
                else:
                    st.error(message)

    # --- 頁籤2：編輯費用歷史 ---
    with tab_fee:
        st.markdown("##### 篩選出人員的「費用歷史」")
        
        @st.cache_data
        def get_fee_history(worker_ids_tuple):
            return worker_model.get_fee_history_for_workers(list(worker_ids_tuple))

        original_fee_df = get_fee_history(tuple(worker_ids_to_edit))
        
        if original_fee_df.empty:
            st.warning("這些員工沒有任何費用歷史紀錄可供編輯。")
        else:
            st.caption("您可以直接在下列表格中修改「金額」和「生效日期」。")

            edited_fee_df = st.data_editor(
                original_fee_df,
                key="fee_editor",
                hide_index=True,
                width='stretch',
                column_config={
                    "id": st.column_config.NumberColumn("紀錄ID", disabled=True),
                    "worker_unique_id": None, # 隱藏
                    "員工姓名": st.column_config.TextColumn(disabled=True),
                    "費用類型": st.column_config.TextColumn(disabled=True),
                    "金額": st.column_config.NumberColumn(format="%d"),
                    "生效日期": st.column_config.DateColumn(format="YYYY-MM-DD")
                },
                disabled=["id", "worker_unique_id", "員工姓名", "費用類型"]
            )
            
            if st.button("🚀 儲存費用歷史變更", type="primary", key="save_fee_history"):
                with st.spinner("正在比對與儲存費用歷史變更..."):
                    success, message = worker_model.batch_edit_history(
                        original_fee_df,
                        edited_fee_df,
                        table_name="FeeHistory",
                        key_column="id",
                        columns_to_update=["worker_unique_id", "金額", "生效日期"]
                    )
                if success:
                    st.success(message)
                    get_fee_history.clear() # 清除快取
                else:
                    st.error(message)