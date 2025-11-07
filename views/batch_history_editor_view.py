# /views/batch_history_editor_view.py

import streamlit as st
import pandas as pd
from datetime import date, timedelta
from data_models import finance_model, dormitory_model, worker_model, employer_dashboard_model
import numpy as np

# 確保 worker_model 模組中有 get_workers_by_history_count, get_accommodation_history_for_workers, get_fee_history_for_workers, batch_edit_history
# 這些函式是在 worker_model.py v2.15 中新增/修改的

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

    @st.cache_data
    def get_workers_with_min_history(count):
        return worker_model.get_worker_ids_by_history_count(count)

    col1, col2, col3 = st.columns(3)
    
    my_dorms = get_my_dorms()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍。")
        return
    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}
    selected_dorm_ids = col1.multiselect(
        "篩選宿舍地址 (可多選)",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options[x]
    )

    my_employers = get_all_employers()
    if not my_employers:
        st.warning("目前資料庫中沒有任何雇主資料可供篩選。")
        return
    selected_employers = col2.multiselect(
        "篩選雇主 (可多選)",
        options=my_employers
    )
    
    min_history_count = col3.number_input(
        "篩選至少有 N 段住宿歷史的人", 
        min_value=1, 
        value=1, 
        help="設為 2 可快速找出所有曾換宿的員工。"
    )

    st.markdown("---")
    st.subheader("步驟二：篩選歷史紀錄的日期範圍 (選填)")
    st.caption("您可以篩選出在特定時間範圍內發生變動（入住、離住、費用生效）的紀錄。")

    date_filter_on = st.checkbox("啟用日期區間篩選")
    filter_start_date = None
    filter_end_date = None
    date_range_tuple = None

    if date_filter_on:
        dr1, dr2 = st.columns(2)
        filter_start_date = dr1.date_input("起始日", value=date.today() - timedelta(days=30))
        filter_end_date = dr2.date_input("結束日", value=date.today())
        if filter_start_date and filter_end_date:
            if filter_start_date > filter_end_date:
                st.error("起始日不能晚於結束日。")
                return
            date_range_tuple = (filter_start_date, filter_end_date)
        else:
            st.warning("請選擇起始日和結束日。")
            return
            
    # --- 步驟三：取得員工 ID ---
    @st.cache_data
    def get_filtered_worker_ids(dorm_ids_tuple, employer_names_tuple, min_count):
        # 這是我們的基礎員工列表 (在住)
        workers_df = finance_model.get_workers_for_fee_management({
            "dorm_ids": list(dorm_ids_tuple) or None, 
            "employer_names": list(employer_names_tuple) or None
        })
        # 檢查 DataFrame 是否為空，或 'unique_id' 欄位是否存在
        if workers_df.empty or 'unique_id' not in workers_df.columns:
            worker_ids_from_filters = set()
        else:
            worker_ids_from_filters = set(workers_df['unique_id'].tolist())

        # 獲取符合歷史筆數的員工
        worker_ids_from_count = set(get_workers_with_min_history(min_count))

        # 進行邏輯交集/聯集
        if selected_dorm_ids or selected_employers:
            if min_count > 1:
                # (有選宿舍/雇主) AND (歷史 > 1)
                final_worker_ids = list(worker_ids_from_filters.intersection(worker_ids_from_count))
            else:
                # (有選宿舍/雇主)
                final_worker_ids = list(worker_ids_from_filters)
        else:
            if min_count > 1:
                # (僅篩選 歷史 > 1)
                final_worker_ids = list(worker_ids_from_count)
            else:
                # (無任何篩選) -> 警告
                return None
        
        return final_worker_ids

    # 必須將 list 轉為 tuple 才能被 @st.cache_data 快取
    worker_ids_to_edit = get_filtered_worker_ids(
        tuple(selected_dorm_ids), 
        tuple(selected_employers), 
        min_history_count
    )

    if worker_ids_to_edit is None:
        st.info("請至少選擇一個篩選條件（宿舍、雇主，或將住宿歷史設為 2 以上）。")
        return
    
    if not worker_ids_to_edit:
        st.info("在您選擇的篩選條件下，目前沒有找到任何符合的在住人員。")
        return

    st.caption(f"已篩選出 {len(worker_ids_to_edit)} 位符合條件的在住人員。正在載入他們的歷史紀錄...")
    st.markdown("---")
    st.subheader("步驟三：批次編輯歷史紀錄")
    
    tab_accom, tab_fee = st.tabs(["🏠 編輯住宿歷史", "💰 編輯費用歷史"])

    # --- 頁籤1：編輯住宿歷史 ---
    with tab_accom:
        st.markdown("##### 篩選出人員的「住宿歷史」")
        
        @st.cache_data
        def get_accom_history(worker_ids_tuple, date_range):
            return worker_model.get_accommodation_history_for_workers(list(worker_ids_tuple), date_range)

        original_accom_df = get_accom_history(tuple(worker_ids_to_edit), date_range_tuple)

        if original_accom_df.empty:
            st.warning("這些員工沒有任何符合條件的住宿歷史紀錄可供編輯。")
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
                    "雇主": st.column_config.TextColumn(disabled=True),
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
        def get_fee_history(worker_ids_tuple, date_range):
            return worker_model.get_fee_history_for_workers(list(worker_ids_tuple), date_range)

        original_fee_df = get_fee_history(tuple(worker_ids_to_edit), date_range_tuple)
        
        if original_fee_df.empty:
            st.warning("這些員工沒有任何符合條件的費用歷史紀錄可供編輯。")
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