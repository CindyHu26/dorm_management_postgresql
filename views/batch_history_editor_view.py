# (v3.1 - 改用 Radio 取代 Tab 以解決跳頁問題)

import streamlit as st
import pandas as pd
from datetime import date, timedelta
from data_models import finance_model, dormitory_model, worker_model, employer_dashboard_model
import numpy as np

def render():
    """渲染「住宿/費用/狀態 歷史批次編輯器」頁面"""
    st.header("歷史紀錄批次編輯器")
    st.info("此頁面用於批次「修改」已存在的歷史紀錄，或批次「新增」特殊狀態。")
    
    # --- 步驟一：設定篩選條件 ---
    st.subheader("步驟一：篩選要編輯的員工")
    
    @st.cache_data
    def get_options_data():
        dorms = dormitory_model.get_my_company_dorms_for_selection()
        employers = employer_dashboard_model.get_all_employers()
        return dorms, employers

    dorms_list, employers_list = get_options_data()
    dorm_map = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms_list}
    
    col1, col2, col3 = st.columns(3)
    
    # 1. 宿舍篩選
    selected_dorm_ids = col1.multiselect(
        "篩選宿舍地址 (可多選)",
        options=list(dorm_map.keys()),
        format_func=lambda x: dorm_map[x],
        key="hist_filter_dorm"
    )

    # 2. 房號篩選 (連動)
    room_options = {}
    if selected_dorm_ids:
        for d_id in selected_dorm_ids:
            rooms = dormitory_model.get_rooms_for_selection(d_id)
            for r in rooms:
                room_options[r['id']] = r['room_number']
    
    selected_room_ids = col2.multiselect(
        "篩選房號 (需先選宿舍)",
        options=list(room_options.keys()),
        format_func=lambda x: room_options[x],
        key="hist_filter_room",
        disabled=not selected_dorm_ids
    )

    # 3. 雇主篩選
    selected_employers = col3.multiselect(
        "篩選雇主 (可多選)",
        options=employers_list,
        key="hist_filter_emp"
    )
    
    # 4. 歷史數量篩選 (僅用於住宿/費用歷史)
    st.markdown("---")
    st.markdown("##### 進階篩選 (僅適用於「住宿/費用」歷史)")
    min_history_count = st.number_input(
        "篩選至少有 N 段住宿歷史的人", 
        min_value=1, 
        value=1, 
        help="設為 2 可快速找出所有曾換宿的員工。"
    )

    date_filter_on = st.checkbox("啟用日期區間篩選 (僅適用於「住宿/費用」歷史)")
    date_range_tuple = None
    if date_filter_on:
        dr1, dr2 = st.columns(2)
        filter_start_date = dr1.date_input("起始日", value=date.today() - timedelta(days=30))
        filter_end_date = dr2.date_input("結束日", value=date.today())
        if filter_start_date and filter_end_date:
            if filter_start_date > filter_end_date:
                st.error("起始日不能晚於結束日。")
            else:
                date_range_tuple = (filter_start_date, filter_end_date)

    # --- 準備篩選參數 ---
    @st.cache_data
    def get_filtered_worker_ids(dorm_ids, employer_names, room_ids, min_count):
        # 1. 基礎篩選 (宿舍/雇主/房號)
        filters = {
            "dorm_ids": dorm_ids, 
            "employer_names": employer_names,
            "room_ids": room_ids
        }
        df = worker_model.get_workers_for_batch_edit(filters)
        if df.empty: return []
        
        base_ids = set(df['unique_id'].tolist())

        # 2. 歷史數量篩選
        if min_count > 1:
            history_ids = set(worker_model.get_worker_ids_by_history_count(min_count))
            final_ids = list(base_ids.intersection(history_ids))
        else:
            final_ids = list(base_ids)
            
        return final_ids

    # --- 取得 Worker IDs ---
    worker_ids_to_edit = []
    if selected_dorm_ids or selected_employers or selected_room_ids:
         worker_ids_to_edit = get_filtered_worker_ids(selected_dorm_ids, selected_employers, selected_room_ids, min_history_count)

    # --- 步驟三：批次編輯 (改用 Radio) ---
    st.markdown("---")
    st.subheader("步驟三：批次編輯")
    
    # 【核心修改】使用 Radio 取代 Tabs
    edit_mode = st.radio(
        "請選擇編輯模式：",
        options=["🏠 編輯住宿歷史", "💰 編輯費用歷史", "🛠️ 批次編輯特殊狀況"],
        horizontal=True,
        key="history_edit_mode_radio"
    )

    protection_options = {
        "手動調整": "保護「住宿位置/日期」，但允許爬蟲未來更新「離住日」。 (建議選項)",
        "系統自動更新": "不保護。在下次執行時，用系統資料覆蓋此次修改。",
        "手動管理(他仲)": "完全鎖定。未來將跳過這些人，不更新任何資料（包括離住日）。"
    }

    # ==========================================================================
    # 模式 1: 編輯住宿歷史
    # ==========================================================================
    if edit_mode == "🏠 編輯住宿歷史":
        if not worker_ids_to_edit:
            st.info("請先在上方選擇篩選條件以載入資料。")
        else:
            st.caption(f"共篩選出 {len(worker_ids_to_edit)} 位員工。")
            @st.cache_data
            def get_accom_history(worker_ids, date_range):
                return worker_model.get_accommodation_history_for_workers(worker_ids, date_range)

            original_accom_df = get_accom_history(worker_ids_to_edit, date_range_tuple)

            if original_accom_df.empty:
                st.warning("這些員工沒有符合條件的住宿歷史紀錄。")
            else:
                edited_accom_df = st.data_editor(
                    original_accom_df,
                    key="accom_editor",
                    hide_index=True,
                    width='stretch',
                    column_config={
                        "id": st.column_config.NumberColumn("紀錄ID", disabled=True),
                        "worker_unique_id": None,
                        "雇主": st.column_config.TextColumn(disabled=True),
                        "員工姓名": st.column_config.TextColumn(disabled=True),
                        "宿舍地址": st.column_config.TextColumn(disabled=True),
                        "房號": st.column_config.TextColumn(disabled=True),
                        "床位編號": st.column_config.TextColumn(max_chars=20),
                        "入住日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                        "離住日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                        "備註": st.column_config.TextColumn(max_chars=255)
                    },
                    disabled=["id", "worker_unique_id", "雇主", "員工姓名", "宿舍地址", "房號"]
                )
                
                st.markdown("---")
                accom_protection_level = st.selectbox("選擇更新後的保護層級*", list(protection_options.keys()), format_func=lambda x: protection_options[x], key="accom_prot")
                
                if st.button("🚀 儲存住宿歷史變更", type="primary"):
                    with st.spinner("處理中..."):
                        success, message = worker_model.batch_edit_history(
                            original_accom_df, edited_accom_df, "AccommodationHistory", "id",
                            ["worker_unique_id", "床位編號", "入住日", "離住日", "備註"], accom_protection_level
                        )
                    if success: st.success(message); st.cache_data.clear(); st.rerun()
                    else: st.error(message)

    # ==========================================================================
    # 模式 2: 編輯費用歷史
    # ==========================================================================
    elif edit_mode == "💰 編輯費用歷史":
        if not worker_ids_to_edit:
            st.info("請先在上方選擇篩選條件以載入資料。")
        else:
            @st.cache_data
            def get_fee_history(worker_ids, date_range):
                return worker_model.get_fee_history_for_workers(worker_ids, date_range)

            original_fee_df = get_fee_history(worker_ids_to_edit, date_range_tuple)
            
            if original_fee_df.empty:
                st.warning("這些員工沒有符合條件的費用歷史紀錄。")
            else:
                edited_fee_df = st.data_editor(
                    original_fee_df,
                    key="fee_editor",
                    hide_index=True,
                    width='stretch',
                    column_config={
                        "id": st.column_config.NumberColumn("紀錄ID", disabled=True),
                        "worker_unique_id": None,
                        "雇主": st.column_config.TextColumn(disabled=True),
                        "員工姓名": st.column_config.TextColumn(disabled=True),
                        "費用類型": st.column_config.TextColumn(disabled=True),
                        "金額": st.column_config.NumberColumn(format="%d"),
                        "生效日期": st.column_config.DateColumn(format="YYYY-MM-DD")
                    },
                    disabled=["id", "worker_unique_id", "雇主", "員工姓名", "費用類型"]
                )
                
                st.markdown("---")
                fee_protection_level = st.selectbox("選擇更新後的保護層級*", list(protection_options.keys()), format_func=lambda x: protection_options[x], key="fee_prot")
                
                if st.button("🚀 儲存費用歷史變更", type="primary"):
                    with st.spinner("處理中..."):
                        success, message = worker_model.batch_edit_history(
                            original_fee_df, edited_fee_df, "FeeHistory", "id",
                            ["worker_unique_id", "金額", "生效日期"], fee_protection_level
                        )
                    if success: st.success(message); st.cache_data.clear(); st.rerun()
                    else: st.error(message)

    # ==========================================================================
    # 模式 3: 批次編輯特殊狀況
    # ==========================================================================
    elif edit_mode == "🛠️ 批次編輯特殊狀況":
        st.info("此功能可批次為員工新增一筆新的狀態紀錄。若「新狀態」留空，則代表將狀態改回正常（結束上一筆特殊狀態）。")
        
        status_filters = {
            "dorm_ids": selected_dorm_ids,
            "employer_names": selected_employers,
            "room_ids": selected_room_ids
        }
        
        if not selected_dorm_ids and not selected_employers and not selected_room_ids:
             st.info("請先在上方選擇篩選條件。")
        else:
            @st.cache_data
            def get_status_data(f):
                return worker_model.get_worker_current_status_for_batch(f)

            status_df = get_status_data(status_filters)

            if status_df.empty:
                st.warning("查無符合條件的在住人員。")
            else:
                # 準備 Data Editor
                status_df["新狀態"] = None
                status_df["新狀態起始日"] = pd.NaT
                
                status_options = ["", "掛宿外住(不收費)", "掛宿外住(收費)", "費用不同", "其他"]

                edited_status_df = st.data_editor(
                    status_df,
                    key="status_editor",
                    hide_index=True,
                    width='stretch',
                    column_config={
                        "unique_id": None,
                        "最新住宿起始日": None, # 隱藏，但後端會用到
                        "雇主": st.column_config.TextColumn(disabled=True),
                        "姓名": st.column_config.TextColumn(disabled=True),
                        "宿舍地址": st.column_config.TextColumn(disabled=True),
                        "房號": st.column_config.TextColumn(disabled=True),
                        "目前狀態": st.column_config.TextColumn(disabled=True),
                        "狀態起始日": st.column_config.DateColumn(format="YYYY-MM-DD", disabled=True),
                        
                        "新狀態": st.column_config.SelectboxColumn(
                            "新狀態 (必填，留空=回歸正常)",
                            options=status_options,
                            required=False
                        ),
                        "新狀態起始日": st.column_config.DateColumn(
                            "新狀態起始日 (若空則用住宿起始日)",
                            format="YYYY-MM-DD",
                            help="若留空，系統將自動填入該員工最新一筆住宿的起始日。"
                        )
                    }
                )
                
                st.markdown("---")
                if st.button("🚀 執行批次狀態變更", type="primary"):
                    # 找出有變更的行
                    updates = []
                    for _, row in edited_status_df.iterrows():
                        new_status = row['新狀態']
                        # 判斷是否需要更新：
                        # 1. 新狀態不是 None (使用者有選，可能是選了某個狀態，或選了空白)
                        # 2. 且 新狀態 != 目前狀態
                        if new_status is not None and new_status != row['目前狀態']:
                            updates.append({
                                'worker_id': row['unique_id'],
                                'new_status': new_status,
                                'start_date': row['新狀態起始日'], # 可能是 NaT
                                'accom_start_date': row['最新住宿起始日']
                            })

                    if not updates:
                        st.warning("沒有偵測到任何有效的狀態變更。")
                    else:
                        with st.spinner(f"正在更新 {len(updates)} 位員工的狀態..."):
                            s_count, f_count, msg = worker_model.batch_update_worker_status(updates)
                        
                        if s_count > 0:
                            st.success(msg)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(msg)
                        