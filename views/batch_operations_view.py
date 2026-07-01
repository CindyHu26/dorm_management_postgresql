# views/batch_operations_view.py (v2.0 - 新增資料來源批次修改)

import streamlit as st
import pandas as pd
from datetime import date
from data_models import finance_model, dormitory_model, worker_model, employer_dashboard_model

def render():
    """渲染「進階批次作業」頁面"""

    # --- 模式切換 ---
    operation_mode = st.radio(
        "請選擇作業模式：",
        options=["進階批次作業 (換宿/費用/離住)", "批次修改資料來源 (鎖定/解鎖)"],
        horizontal=True,
        label_visibility="collapsed"
    )

    st.markdown("---")

    # ==============================================================================
    # 模式 A: 原有的進階批次作業 (換宿/費用/離住)
    # ==============================================================================
    if operation_mode == "進階批次作業 (換宿/費用/離住)":
        st.info("此模式用於對篩選出的人員，批次執行複雜的住宿異動或費用變更。")

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
            format_func=lambda x: dorm_options[x],
            key="batch_op_dorms"
        )

        my_employers = get_all_employers()
        if not my_employers:
            st.warning("目前資料庫中沒有任何雇主資料可供篩選。")
            return
        selected_employers = col2.multiselect(
            "篩選雇主 (可不選，或多選)",
            options=my_employers,
            key="batch_op_employers"
        )

        filters = {
            "dorm_ids": selected_dorm_ids,
            "employer_names": selected_employers
        }

        if not selected_dorm_ids and not selected_employers:
            st.info("請至少選擇一個「宿舍地址」或「雇主」來載入人員資料。")
            return

        # --- 步驟二：人員總覽與排除 ---
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


        # --- 步驟三：批次更新 ---
        st.subheader("步驟三：選擇要執行的批次操作")
        
        with st.form("batch_complex_update_form"):
            st.warning("注意：此操作將會修改所有上方列表顯示的人員 (已排除者除外)，請謹慎操作。")
            
            tab_accom, tab_fee, tab_departure = st.tabs(["🏠 批次換宿", "💰 批次更新費用", "🛫 批次設定離住"])

            # --- 頁籤1：批次換宿 ---
            with tab_accom:
                st.markdown("##### 住宿異動 (換宿)")
                st.caption("填寫此頁籤會結束所選人員的舊住宿紀錄，並建立新的住宿紀錄。")
                
                @st.cache_data
                def get_all_dorms_list():
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

            st.subheader("步驟四：設定保護層級")
            st.info("執行此次批次作業後，您希望這些員工的資料狀態變為？")
            
            protection_options = {
                "手動調整": "保護「住宿位置/日期」，但允許爬蟲未來更新「離住日」。 (建議選項)",
                "系統自動更新": "不保護。在下次執行時，用系統資料覆蓋此次修改。",
                "手動管理(他仲)": "完全鎖定。未來將跳過這些人，不更新任何資料（包括離住日）。"
            }
            
            form_protection_level = st.selectbox(
                "選擇更新後的保護層級*",
                options=list(protection_options.keys()),
                format_func=lambda x: protection_options[x],
                index=0 # 預設選取 "手動調整"
            )
            st.markdown("---")
            submitted = st.form_submit_button("🚀 執行批次更新", type="primary")
            
            if submitted:
                target_df = workers_df[~workers_df['unique_id'].isin(excluded_ids)]
                worker_ids_to_update = target_df['unique_id'].tolist()
                
                if not worker_ids_to_update:
                    st.error("沒有選取任何要更新的員工（可能全部被排除）。")
                else:
                    updates_payload = {}
                    
                    if form_new_room_id is not None and form_new_start_date is not None:
                        updates_payload["new_room_id"] = form_new_room_id
                        updates_payload["new_start_date"] = form_new_start_date
                    
                    fees_dict = {
                        'monthly_fee': form_monthly_fee,
                        'utilities_fee': form_utilities_fee,
                        'cleaning_fee': form_cleaning_fee,
                        'charging_cleaning_fee': form_charging_cleaning_fee,
                        'restoration_fee': form_restoration_fee
                    }
                    fees_to_update = {k: v for k, v in fees_dict.items() if v >= 0}
                    
                    if fees_to_update and form_fee_effective_date is not None:
                        updates_payload["fees_to_update"] = fees_to_update
                        updates_payload["fee_effective_date"] = form_fee_effective_date
                        
                    if form_new_end_date is not None:
                        updates_payload["new_end_date"] = form_new_end_date
                    
                    if not updates_payload:
                        st.warning("您沒有填寫任何有效的更新操作。")
                    else:
                        with st.spinner(f"正在為 {len(worker_ids_to_update)} 位員工執行批次更新..."):
                            success, message = worker_model.batch_update_workers_complex(
                                worker_ids_to_update, updates_payload, form_protection_level
                            )
                        
                        if success:
                            st.success(message)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(message)

    # ==============================================================================
    # 模式 B: 批次修改資料來源 (鎖定/解鎖)
    # ==============================================================================
    else:
        st.info("此模式用於批次調整人員的資料更新權限（例如：將多位人員設為「手動調整」以保護其房號不被爬蟲覆蓋）。")

        # --- 1. 篩選器 ---
        st.subheader("步驟一：篩選目標人員")
        
        # 載入選項
        @st.cache_data
        def get_options_data():
            dorms = dormitory_model.get_my_company_dorms_for_selection()
            employers = employer_dashboard_model.get_all_employers()
            return dorms, employers

        dorms_list, employers_list = get_options_data()
        
        dorm_map = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms_list}
        
        col_f1, col_f2, col_f3 = st.columns(3)
        
        sel_dorms = col_f1.multiselect("篩選宿舍地址", options=list(dorm_map.keys()), format_func=lambda x: dorm_map[x], key="ds_filter_dorm")
        
        # 房號選項：僅顯示已選宿舍的房號
        room_options = {}
        if sel_dorms:
            for d_id in sel_dorms:
                rooms = dormitory_model.get_rooms_for_selection(d_id)
                for r in rooms:
                    room_options[r['id']] = r['room_number'] # 這裡可能會遇到不同宿舍有相同房號ID? 不會，ID是唯一的
        
        sel_rooms = col_f2.multiselect("篩選房號 (需先選宿舍)", options=list(room_options.keys()), format_func=lambda x: room_options[x], key="ds_filter_room", disabled=not sel_dorms)
        
        sel_employers = col_f3.multiselect("篩選雇主", options=employers_list, key="ds_filter_emp")

        if not sel_dorms and not sel_employers:
            st.info("請至少選擇「宿舍」或「雇主」進行篩選。")
            return

        # --- 2. 撈取資料 ---
        @st.cache_data
        def get_workers_data(filters):
            return worker_model.get_workers_for_batch_edit(filters)
        
        filters = {
            "dorm_ids": sel_dorms,
            "employer_names": sel_employers,
            "room_ids": sel_rooms
        }
        
        edit_df = get_workers_data(filters)

        if edit_df.empty:
            st.warning("查無符合條件的在住人員。")
            return

        st.subheader(f"步驟二：編輯資料來源 (共 {len(edit_df)} 筆)")
        
        # --- 3. Data Editor ---
        data_source_options = ["系統自動更新", "手動調整", "手動管理(他仲)"]
        
        with st.form("ds_editor_form"):
            edited_df = st.data_editor(
                edit_df,
                width='stretch',
                hide_index=True,
                key="ds_data_editor",
                column_config={
                    "unique_id": None, # 隱藏 ID
                    "雇主": st.column_config.TextColumn(disabled=True),
                    "姓名": st.column_config.TextColumn(disabled=True),
                    "宿舍地址": st.column_config.TextColumn(disabled=True),
                    "房號": st.column_config.TextColumn(disabled=True),
                    "資料來源": st.column_config.SelectboxColumn(
                        "資料來源 (可編輯)",
                        options=data_source_options,
                        required=True,
                        help="系統自動更新: 全自動 / 手動調整: 保護住宿 / 手動管理: 完全鎖定"
                    )
                }
            )
            
            st.markdown("---")
            if st.form_submit_button("🚀 儲存變更", type="primary"):
                # 找出有變動的行
                # 因為 data_editor 回傳的是完整的 DF，我們需要比較
                # 但簡單起見，我們直接把這個 DF 傳給後端處理，後端負責 Update
                # 為了效能，這裡可以做一點差異比對，但幾百筆資料直接 Update 也是很快的
                
                with st.spinner("正在更新資料來源..."):
                    success, fail = worker_model.batch_update_worker_data_sources(edited_df)
                
                if fail > 0:
                    st.warning(f"更新完成：{success} 筆成功，{fail} 筆失敗。")
                else:
                    st.success(f"成功更新 {success} 筆人員資料！")
                
                st.cache_data.clear()
                st.rerun()