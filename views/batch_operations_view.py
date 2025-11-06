# views/batch_operations_view.py

import streamlit as st
import pandas as pd
from datetime import date
from data_models import finance_model, dormitory_model, worker_model, employer_dashboard_model

def render():
    """渲染「進階批次作業」頁面"""
    st.header("進階批次作業")
    st.info("此頁面用於對篩選出的人員，批次執行複雜的住宿異動或費用變更。")

    # --- 步驟一：設定篩選條件 (同 rent_view) ---
    st.subheader("步驟一：設定篩選條件")
    
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

    # --- 步驟二：人員總覽與排除 (同 rent_view) ---
    st.subheader("步驟二：檢視與排除人員")
    workers_df = finance_model.get_workers_for_fee_management(filters)

    if workers_df.empty:
        st.info("在您選擇的篩選條件下，目前沒有找到任何在住人員。")
        return

    view_col, exclude_col = st.columns([3, 1])
    with view_col:
        st.dataframe(workers_df, width='stretch', hide_index=True)

    with exclude_col:
        worker_options_for_exclude = pd.Series(workers_df.unique_id.values, index=workers_df.姓名).to_dict()
        excluded_names = st.multiselect(
            "排除以下人員 (可多選)",
            options=list(worker_options_for_exclude.keys())
        )
        excluded_ids = [worker_options_for_exclude[name] for name in excluded_names]


    # --- 步驟三：批次更新 (全新表單) ---
    st.subheader("步驟三：選擇要執行的批次操作")
    
    with st.form("batch_complex_update_form"):
        st.warning("注意：此操作將會修改所有上方列表顯示的人員 (已排除者除外)，請謹慎操作。")
        
        # 使用頁籤來分隔不同的操作
        tab_accom, tab_fee, tab_departure = st.tabs(["🏠 批次換宿", "💰 批次更新費用", "🛫 批次設定離住"])

        # --- 頁籤1：批次換宿 ---
        with tab_accom:
            st.markdown("##### 住宿異動 (換宿)")
            st.caption("填寫此頁籤會結束所選人員的舊住宿紀錄，並建立新的住宿紀錄。")
            
            @st.cache_data
            def get_all_dorms_list(): # 換宿需要所有宿舍的選項
                return dormitory_model.get_dorms_for_selection()
            
            all_dorms_list = get_all_dorms_list()
            all_dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in all_dorms_list}
            
            c1_accom, c2_accom, c3_accom = st.columns(3)
            form_new_dorm_id = c1_accom.selectbox("新宿舍地址", [None] + list(all_dorm_options.keys()), format_func=lambda x: " (不變更)" if x is None else all_dorm_options[x], key="form_new_dorm")
            
            rooms_in_new_dorm = dormitory_model.get_rooms_for_selection(form_new_dorm_id) if form_new_dorm_id else []
            new_room_options = {r['id']: r['room_number'] for r in rooms_in_new_dorm}
            form_new_room_id = c2_accom.selectbox("新房號", [None] + list(new_room_options.keys()), format_func=lambda x: " (不變更)" if x is None else new_room_options[x], key="form_new_room")
            
            form_new_start_date = c3_accom.date_input("新住宿起始日", value=None)
            st.caption("**重要**：必須同時選擇「新房號」和「新住宿起始日」，此項操作才會生效。")

        # --- 頁籤2：批次更新費用 ---
        with tab_fee:
            st.markdown("##### 費用更新")
            st.caption("填寫此頁籤會為所選人員新增一筆或多筆費用歷史紀錄。")
            
            form_fee_effective_date = st.date_input("費用生效日期", value=None, help="所有下方費用的統一計費起算日")
            
            fee_c1, fee_c2 = st.columns(2)
            # 使用 -1 作為 "不更新" 的標記
            form_monthly_fee = fee_c1.number_input("月費(房租)", min_value=-1, value=-1, help="填入 -1 表示不更新此項。")
            form_utilities_fee = fee_c2.number_input("水電費", min_value=-1, value=-1, help="填入 -1 表示不更新此項。")
            form_cleaning_fee = fee_c1.number_input("清潔費", min_value=-1, value=-1, help="填入 -1 表示不更新此項。")
            form_charging_cleaning_fee = fee_c2.number_input("充電清潔費", min_value=-1, value=-1, help="填入 -1 表示不更新此項。")
            form_restoration_fee = fee_c1.number_input("宿舍復歸費", min_value=-1, value=-1, help="填入 -1 表示不更新此項。")
            st.caption("**重要**：必須填寫「費用生效日期」且至少一項費用不為 -1，此項操作才會生效。")

        # --- 頁籤3：批次設定離住 ---
        with tab_departure:
            st.markdown("##### 離住設定")
            st.caption("填寫此頁籤會更新所選人員的最終離住日期，並結束其最新的住宿紀錄。")
            form_new_end_date = st.date_input("最終離住日期", value=None)
            st.caption("**重要**：必須填寫「最終離住日期」，此項操作才會生效。")

        st.markdown("---")
        submitted = st.form_submit_button("🚀 執行批次更新", type="primary")
        
        if submitted:
            # 1. 收集要更新的員工 ID
            target_df = workers_df[~workers_df['unique_id'].isin(excluded_ids)]
            worker_ids_to_update = target_df['unique_id'].tolist()
            
            if not worker_ids_to_update:
                st.error("沒有選取任何要更新的員工（可能全部被排除）。")
            else:
                # 2. 建立 updates 字典
                updates_payload = {}
                
                # 處理住宿異動
                if form_new_room_id is not None and form_new_start_date is not None:
                    updates_payload["new_room_id"] = form_new_room_id
                    updates_payload["new_start_date"] = form_new_start_date
                
                # 處理費用
                fees_dict = {
                    'monthly_fee': form_monthly_fee,
                    'utilities_fee': form_utilities_fee,
                    'cleaning_fee': form_cleaning_fee,
                    'charging_cleaning_fee': form_charging_cleaning_fee,
                    'restoration_fee': form_restoration_fee
                }
                # 過濾掉 -1 (不更新) 的項目
                fees_to_update = {k: v for k, v in fees_dict.items() if v >= 0}
                
                if fees_to_update and form_fee_effective_date is not None:
                    updates_payload["fees_to_update"] = fees_to_update
                    updates_payload["fee_effective_date"] = form_fee_effective_date
                    
                # 處理離住
                if form_new_end_date is not None:
                    updates_payload["new_end_date"] = form_new_end_date
                
                # 3. 呼叫後端函式
                if not updates_payload:
                    st.warning("您沒有填寫任何有效的更新操作（例如，換宿忘了填日期，或費用忘了填生效日）。")
                else:
                    with st.spinner(f"正在為 {len(worker_ids_to_update)} 位員工執行批次更新..."):
                        # 呼叫我們在步驟一建立的新函式
                        success, message = worker_model.batch_update_workers_complex(
                            worker_ids_to_update, updates_payload
                        )
                    
                    if success:
                        st.success(message)
                        st.cache_data.clear() # 清除所有快取
                        st.rerun()
                    else:
                        st.error(message)