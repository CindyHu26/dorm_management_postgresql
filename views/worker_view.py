# views/worker_view.py (v2.10 - NaN 修正版)
import streamlit as st
import pandas as pd
from datetime import datetime, date
from data_models import worker_model, dormitory_model

def render():
    """【v2.10 修改版】渲染「人員管理」頁面，修正 NaN 錯誤"""
    st.header("移工住宿人員管理")
    
    # --- Session State 初始化 (維持不變) ---
    if 'worker_active_tab' not in st.session_state:
        st.session_state.worker_active_tab = "✏️ 編輯核心資料"
    if 'selected_worker_id' not in st.session_state:
        st.session_state.selected_worker_id = None
    if 'last_selected_worker_id' not in st.session_state:
        st.session_state.last_selected_worker_id = None
    if st.session_state.selected_worker_id != st.session_state.last_selected_worker_id:
        st.session_state.worker_active_tab = "✏️ 編輯核心資料"
        st.session_state.last_selected_worker_id = st.session_state.selected_worker_id

    # --- 新增手動管理人員區塊 (維持不變) ---
    with st.expander("➕ 新增手動管理人員 (他仲等)"):
        with st.form("new_manual_worker_form", clear_on_submit=True):
            st.subheader("新人員基本資料")
            c1, c2, c3 = st.columns(3)
            employer_name = c1.text_input("雇主名稱 (必填)")
            worker_name = c2.text_input("移工姓名 (必填)")
            passport_number = c3.text_input("護照號碼 (同名時必填)")
            gender = c1.selectbox("性別", ["", "男", "女"])
            nationality_options = ["", "越南", "印尼", "泰國", "菲律賓", "其他 (請手動輸入)"]
            selected_nationality = c2.selectbox("國籍", options=nationality_options)
            custom_nationality = c2.text_input("手動輸入國籍", help="若上方選擇「其他」，請在此填寫")
            arc_number = c3.text_input("居留證號")
            st.subheader("住宿與費用")
            dorms = dormitory_model.get_dorms_for_selection() or []
            dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms}
            
            sc1, sc2, sc3 = st.columns(3)
            selected_dorm_id_new = sc1.selectbox("宿舍地址", [None] + list(dorm_options.keys()), format_func=lambda x: "未分配" if x is None else dorm_options.get(x), key="new_dorm_select")
            
            rooms = dormitory_model.get_rooms_for_selection(selected_dorm_id_new) or []
            room_options = {r['id']: r['room_number'] for r in rooms}
            selected_room_id_new = sc2.selectbox("房間號碼", [None] + list(room_options.keys()), format_func=lambda x: "未分配" if x is None else room_options.get(x), key="new_room_select")
            
            bed_number_new = sc3.text_input("床位編號")

            f1, f2, f3 = st.columns(3)
            monthly_fee = f1.number_input("月費(房租)", min_value=0, step=100)
            utilities_fee = f2.number_input("水電費", min_value=0, step=100)
            cleaning_fee = f3.number_input("清潔費", min_value=0, step=100)
            f4, f5 = st.columns(2)
            restoration_fee = f4.number_input("宿舍復歸費", min_value=0, step=100)
            charging_cleaning_fee = f5.number_input("充電清潔費", min_value=0, step=100)
            ff1, ff2 = st.columns(2)
            payment_method = ff1.selectbox("付款方", ["", "員工自付", "雇主支付"])
            accommodation_start_date = ff2.date_input("起住日期", value=date.today())
            worker_notes = st.text_area("個人備註")
            st.subheader("初始狀態")
            s1, s2 = st.columns(2)
            initial_status_options = ["", "掛宿外住(不收費)", "掛宿外住(收費)", "費用不同", "其他"]
            initial_status = s1.selectbox("初始狀態 (若為正常在住，此處請留空)", initial_status_options)
            status_notes = s2.text_area("狀態備註")
            submitted = st.form_submit_button("儲存新人員")
            if submitted:
                if not employer_name or not worker_name:
                    st.error("雇主和移工姓名為必填欄位！")
                else:
                    emp_clean = employer_name.strip()
                    name_clean = worker_name.strip()
                    pass_clean = str(passport_number or '').strip()
                    unique_id = f"{emp_clean}_{name_clean}"
                    final_nationality = custom_nationality if selected_nationality == "其他 (請手動輸入)" else selected_nationality
                    if pass_clean:
                        unique_id += f"_{pass_clean}"
                    details = {
                    'unique_id': unique_id, 'employer_name': emp_clean, 'worker_name': name_clean,
                    'passport_number': pass_clean if pass_clean else None,
                    'gender': gender, 'nationality': final_nationality, 'arc_number': arc_number,
                    'dorm_id': selected_dorm_id_new,
                    'room_id': selected_room_id_new, 
                    'monthly_fee': monthly_fee,
                    'utilities_fee': utilities_fee, 'cleaning_fee': cleaning_fee,
                    'restoration_fee': restoration_fee, 'charging_cleaning_fee': charging_cleaning_fee,
                    'payment_method': payment_method,
                    'accommodation_start_date': str(accommodation_start_date) if accommodation_start_date else None,
                    'worker_notes': worker_notes
                    }
                    status_details = {
                        'status': initial_status,
                        'start_date': str(accommodation_start_date) if accommodation_start_date else str(date.today()),
                        'notes': status_notes
                    }
                    success, message, _ = worker_model.add_manual_worker(details, status_details, bed_number=bed_number_new)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

    st.markdown("---")

    # --- 移工總覽區塊 ---
    st.subheader("移工總覽 (所有宿舍)")

    # --- 【核心修改 1】初始化新的 session_state ---
    if 'worker_view_filters' not in st.session_state:
        st.session_state.worker_view_filters = {
            'name_search': '', 'dorm_id': None, 'status': '全部',
            'room_id': None, 'nationality': '全部', 'gender': '全部'
        }

    @st.cache_data
    def get_dorms_list():
        return dormitory_model.get_dorms_for_selection()
    
    # --- 【核心修改 2】取得新篩選器的選項 ---
    @st.cache_data
    def get_nationality_list():
        # 呼叫我們新增的函式
        return ["全部"] + worker_model.get_distinct_nationalities()

    dorms = get_dorms_list() or []
    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms}
    nationality_options = get_nationality_list()
    gender_options = ["全部", "男", "女"]
    
    # --- 【核心修改 3】重新排版篩選器 (2x3) ---
    f_row1_c1, f_row1_c2, f_row1_c3 = st.columns(3)
    f_row2_c1, f_row2_c2, f_row2_c3 = st.columns(3)

    # Row 1
    st.session_state.worker_view_filters['name_search'] = f_row1_c1.text_input(
        "搜尋姓名、雇主或地址", 
        value=st.session_state.worker_view_filters['name_search']
    )
    st.session_state.worker_view_filters['status'] = f_row1_c2.selectbox(
        "篩選在住狀態", 
        ["全部", "在住", "已離住"], 
        index=["全部", "在住", "已離住"].index(st.session_state.worker_view_filters['status'])
    )
    st.session_state.worker_view_filters['gender'] = f_row1_c3.selectbox(
        "篩選性別", 
        gender_options, 
        index=gender_options.index(st.session_state.worker_view_filters['gender'])
    )
    
    # Row 2
    # 宿舍篩選 (Dorm)
    selected_dorm_id = f_row2_c1.selectbox(
        "篩選宿舍", 
        options=[None] + list(dorm_options.keys()), 
        format_func=lambda x: "全部宿舍" if x is None else dorm_options.get(x), 
        index=[None, *dorm_options.keys()].index(st.session_state.worker_view_filters['dorm_id'])
    )
    # --- 【核心修改 4】如果宿舍變更，清空房號篩選 ---
    if selected_dorm_id != st.session_state.worker_view_filters['dorm_id']:
        st.session_state.worker_view_filters['room_id'] = None # Reset room filter
    st.session_state.worker_view_filters['dorm_id'] = selected_dorm_id

    # 房號篩選 (Room) - 依賴宿舍篩選
    rooms_for_filter = dormitory_model.get_rooms_for_selection(st.session_state.worker_view_filters['dorm_id']) or []
    room_filter_options = {r['id']: r['room_number'] for r in rooms_for_filter}
    
    st.session_state.worker_view_filters['room_id'] = f_row2_c2.selectbox(
        "篩選房號", 
        options=[None] + list(room_filter_options.keys()), 
        format_func=lambda x: "全部房號" if x is None else room_filter_options.get(x, "N/A"), 
        index=[None, *room_filter_options.keys()].index(st.session_state.worker_view_filters['room_id']),
        disabled=not st.session_state.worker_view_filters['dorm_id'] # 沒選宿舍就禁用
    )
    
    # 國籍篩選 (Nationality)
    st.session_state.worker_view_filters['nationality'] = f_row2_c3.selectbox(
        "篩選國籍", 
        nationality_options, 
        index=nationality_options.index(st.session_state.worker_view_filters['nationality']) if st.session_state.worker_view_filters['nationality'] in nationality_options else 0
    )
    # --- 篩選器排版結束 ---

    workers_df = worker_model.get_workers_for_view(st.session_state.worker_view_filters)
    
    st.dataframe(workers_df, width="stretch", hide_index=True, column_config={"unique_id": None}) 

    st.markdown("---")

    # --- 編輯/檢視單一移工資料區塊 ---
    st.subheader("編輯/檢視單一移工資料")

    if workers_df.empty:
        st.info("目前沒有符合篩選條件的工人資料可供編輯。")
    else:
        worker_options = {
            row['unique_id']: ( 
                f"{row.get('雇主', 'NA')} / "
                f"{row.get('姓名', 'N/A')} / "
                f"護照:{row.get('護照號碼') or '無'} / "
                f"居留證:{row.get('居留證號碼') or '無'} "
                f"({row.get('實際地址', 'N/A')})"
                f"{' (已離住)' if row.get('在住狀態') == '已離住' else ''}"
            )
            for _, row in workers_df.iterrows()
        }
        
        selected_worker_id = st.selectbox(
            "請從上方總覽列表選擇要操作的移工：",
            options=[None] + list(worker_options.keys()),
            format_func=lambda x: "請選擇..." if x is None else worker_options.get(x),
            key="selected_worker_id"
        )

        if selected_worker_id:
            worker_details = worker_model.get_single_worker_details(selected_worker_id)
            if not worker_details:
                st.error("找不到選定的移工資料，可能已被刪除。")
            else:
                st.markdown(f"#### 管理移工: {worker_details.get('worker_name')} ({worker_details.get('employer_name')})")
                
                tab_names = ["✏️ 編輯核心資料", "🏠 住宿歷史管理", "🕒 狀態歷史管理", "💰 費用歷史"]
                selected_tab = st.radio(
                    "管理選項:",
                    tab_names,
                    key="worker_active_tab",
                    horizontal=True,
                    label_visibility="collapsed"
                )

                if selected_tab == "✏️ 編輯核心資料":
                    with st.form("edit_worker_form"):
                        st.info(f"資料來源: **{worker_details.get('data_source')}**")
                        st.markdown("##### 基本資料 (多由系統同步)")
                        ec1, ec2, ec3 = st.columns(3)
                        ec1.text_input("性別", value=worker_details.get('gender'), disabled=True)
                        ec2.text_input("國籍", value=worker_details.get('nationality'), disabled=True)
                        ec3.text_input("護照號碼", value=worker_details.get('passport_number'), disabled=True)
                        st.markdown("##### 住宿分配")
                        st.info("工人的住宿地點管理已移至「🏠 住宿歷史管理」分頁。")
                        
                        st.markdown("##### 費用 (唯讀)")
                        st.info("ℹ️ 費用項目應至「💰 費用歷史」頁籤進行新增/修改，以保留完整的變更紀錄。此處僅顯示當前最新費用。")
                        
                        # 試著從總覽的 dataframe (已查詢 FeeHistory) 中獲取最新費用
                        worker_row_from_df = workers_df[workers_df['unique_id'] == selected_worker_id].iloc[0]

                        # 建立一個輔助函式來安全地轉換 NaN
                        def get_fee_value(fee_name):
                            val = worker_row_from_df.get(fee_name)
                            if pd.isna(val):
                                return 0
                            return int(val)
                        
                        fc1, fc2, fc3 = st.columns(3)
                        monthly_fee = fc1.number_input("月費(房租)", value=get_fee_value('月費(房租)'), disabled=True)
                        utilities_fee = fc2.number_input("水電費", value=get_fee_value('水電費'), disabled=True)
                        cleaning_fee = fc3.number_input("清潔費", value=get_fee_value('清潔費'), disabled=True)
                        fc4, fc5 = st.columns(2)
                        restoration_fee = fc4.number_input("宿舍復歸費", value=get_fee_value('宿舍復歸費'), disabled=True)
                        charging_cleaning_fee = fc5.number_input("充電清潔費", value=get_fee_value('充電清潔費'), disabled=True)
                        
                        st.markdown("##### 狀態 (可手動修改)")
                        fcc1, fcc2 = st.columns(2)
                        payment_method_options = ["", "員工自付", "雇主支付"]
                        payment_method = fcc1.selectbox("付款方", payment_method_options, index=payment_method_options.index(worker_details.get('payment_method')) if worker_details.get('payment_method') in payment_method_options else 0)

                        with fcc2:
                            end_date_value = worker_details.get('accommodation_end_date')
                            accommodation_end_date = st.date_input("最終離住日期", value=end_date_value)
                            clear_end_date = st.checkbox("清除離住日期 (將狀態改回在住)")

                        worker_notes = st.text_area("個人備註", value=worker_details.get('worker_notes') or "")

                        if st.form_submit_button("儲存核心資料變更"):
                            final_end_date = None if clear_end_date else (str(accommodation_end_date) if accommodation_end_date else None)
                            
                            update_data = {
                                'payment_method': payment_method, 
                                'accommodation_end_date': final_end_date,
                                'worker_notes': worker_notes
                            }

                            success, message = worker_model.update_worker_details(selected_worker_id, update_data)
                            if success: st.success(message); st.cache_data.clear(); st.rerun()
                            else: st.error(message)

                    # --- 【更新危險操作區】 ---
                    st.markdown("---")
                    st.markdown("##### 危險操作區")
                    current_data_source = worker_details.get('data_source')

                    # 顯示當前狀態和解鎖按鈕
                    if current_data_source in ['手動調整', '手動管理(他仲)']:
                        if current_data_source == '手動調整': 
                            st.warning("此工人的「住宿位置」為手動鎖定，不受自動同步影響，但「離住日」仍會更新。")
                        else: 
                            st.error("此工人已被「完全鎖定」，系統不會更新其住宿位置和離住日。")
                        
                        if st.button("🔓 解除鎖定，恢復系統自動同步"):
                            success, message = worker_model.reset_worker_data_source(selected_worker_id)
                            if success: st.success(message); st.cache_data.clear(); st.rerun()
                            else: st.error(message)
                    
                    st.markdown("---")
                    lock_col1, lock_col2 = st.columns(2)

                    with lock_col1:
                        # "手動調整" (部分鎖定) 按鈕
                        if current_data_source == '系統自動更新':
                            st.write("保護此人員的「住宿位置」，但仍允許系統更新「離住日」等資訊。")
                            if st.button("🔒 設為手動調整 (保護住宿)"):
                                success, message = worker_model.set_worker_as_manual_adjustment(selected_worker_id)
                                if success: st.success(message); st.cache_data.clear(); st.rerun()
                                else: st.error(message)
                        elif current_data_source == '手動調整':
                            st.info("ℹ️ 已處於「手動調整」狀態。")

                    with lock_col2:
                        # "手動管理(他仲)" (完全鎖定) 按鈕
                        if current_data_source != '手動管理(他仲)':
                            st.write("保護此人員的「所有資料」（包含住宿與離住日），系統將完全跳過此人。")
                            if st.button("🔒 設為完全鎖定 (保護所有資料)", type="primary"):
                                success, message = worker_model.set_worker_as_fully_manual(selected_worker_id)
                                if success: st.success(message); st.cache_data.clear(); st.rerun()
                                else: st.error(message)
                        elif current_data_source == '手動管理(他仲)':
                            st.info("ℹ️ 已處於「完全鎖定」狀態。")

                    st.markdown("---")
                    confirm_delete = st.checkbox("我了解並確認要刪除此移工的資料")
                    if st.button("🗑️ 刪除此移工", type="primary", disabled=not confirm_delete):
                        success, message = worker_model.delete_worker_by_id(selected_worker_id)
                        if success: st.success(message); st.cache_data.clear(); st.rerun()
                        else: st.error(message)

                elif selected_tab == "🏠 住宿歷史管理":
                    st.markdown("##### 新增一筆住宿紀錄 (換宿)")
                    st.info("當工人更換房間或宿舍時，請在此處新增一筆紀錄。系統將自動結束前一筆紀錄。")

                    ac1, ac2, ac3 = st.columns(3)
                    all_dorms = dormitory_model.get_dorms_for_selection() or []
                    all_dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in all_dorms}
                    selected_dorm_id_ac = ac1.selectbox("新宿舍地址", options=all_dorm_options.keys(), format_func=lambda x: all_dorm_options.get(x), key="ac_dorm_select")
                    rooms_ac = dormitory_model.get_rooms_for_selection(selected_dorm_id_ac) or []
                    room_options_ac = {r['id']: r['room_number'] for r in rooms_ac}
                    selected_room_id_ac = ac2.selectbox("新房間號碼", options=room_options_ac.keys(), format_func=lambda x: room_options_ac.get(x), key="ac_room_select")
                    new_bed_number = ac3.text_input("新床位編號 (例如: A-01)")
                    change_date = st.date_input("換宿生效日期", value=date.today(), key="ac_change_date")

                    if st.button("🚀 執行換宿"):
                        if not selected_room_id_ac: st.error("必須選擇一個新的房間！")
                        else:
                            success, message = worker_model.change_worker_accommodation(selected_worker_id, selected_room_id_ac, change_date, bed_number=new_bed_number)
                            if success: st.success(message); st.cache_data.clear(); st.rerun()
                            else: st.error(message)

                    st.markdown("---")
                    st.markdown("##### 歷史住宿紀錄")
                    accommodation_history_df = worker_model.get_accommodation_history_for_worker(selected_worker_id)
                    st.dataframe(accommodation_history_df, width="stretch", hide_index=True, column_config={"id": None})

                    st.markdown("---")
                    st.subheader("編輯或刪除單筆住宿歷史")

                    if accommodation_history_df.empty: st.info("此員工尚無任何住宿歷史紀錄可供編輯。")
                    else:
                        history_options = {row['id']: f"{row['起始日']} ~ {row.get('結束日', '至今')} | {row['宿舍地址']} {row['房號']} (床位: {row.get('床位編號') or '未指定'})" for _, row in accommodation_history_df.iterrows()}
                        selected_history_id = st.selectbox("請從上方列表選擇一筆紀錄進行操作：", [None] + list(history_options.keys()), format_func=lambda x: "請選擇..." if x is None else history_options.get(x), key=f"history_selector_{selected_worker_id}")
                        if selected_history_id:
                            history_details = worker_model.get_single_accommodation_details(selected_history_id)
                            if history_details:
                                with st.form(f"edit_history_form_{selected_history_id}"):
                                    st.markdown(f"###### 正在編輯 ID: {history_details['id']} 的紀錄")

                                    current_room_id = history_details.get('room_id')
                                    current_dorm_id = dormitory_model.get_dorm_id_from_room_id(current_room_id)

                                    all_dorms_edit = dormitory_model.get_dorms_for_selection() or []
                                    all_dorm_options_edit = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in all_dorms_edit}
                                    dorm_keys_edit = list(all_dorm_options_edit.keys())
                                    try:
                                        dorm_index = dorm_keys_edit.index(current_dorm_id) if current_dorm_id in dorm_keys_edit else 0
                                    except ValueError:
                                        dorm_index = 0

                                    def clear_room_state_on_dorm_change():
                                        """當宿舍選單變更時，清除房間選單的狀態。"""
                                        room_key = f"edit_hist_room_{selected_history_id}"
                                        if room_key in st.session_state:
                                            # 使用 del 來完全移除狀態
                                            del st.session_state[room_key]

                                    edit_dorm_id = st.selectbox("宿舍地址", options=dorm_keys_edit, format_func=lambda x: all_dorm_options_edit.get(x), index=dorm_index, key=f"edit_hist_dorm_{selected_history_id}")

                                    rooms_edit = dormitory_model.get_rooms_for_selection(edit_dorm_id) or []
                                    room_options_edit = {r['id']: r['room_number'] for r in rooms_edit}
                                    room_keys_edit = list(room_options_edit.keys())
                                    # 只有當 宿舍ID 等於 原始宿舍ID 時，才嘗試尋找原始房間
                                    room_index = 0 # 預設為 0
                                    if edit_dorm_id == current_dorm_id:
                                        try:
                                            room_index = room_keys_edit.index(current_room_id) if current_room_id in room_keys_edit else 0
                                        except ValueError:
                                            room_index = 0
                                    # 如果宿舍ID已經改變，room_index 會維持 0，
                                    # 並且因為 clear_room_state_on_dorm_change 函式清除了 key，
                                    # selectbox 會正確顯示 index 0 的選項。

                                    edit_room_id = st.selectbox(
                                        "房間號碼", 
                                        options=room_keys_edit, 
                                        format_func=lambda x: room_options_edit.get(x), 
                                        index=room_index, # <-- 使用新的 room_index 邏輯
                                        key=f"edit_hist_room_{selected_history_id}"
                                    )

                                    ehc1, ehc2, ehc3 = st.columns(3)
                                    edit_start_date = ehc1.date_input("起始日", value=history_details.get('start_date'))
                                    
                                    with ehc2:
                                        edit_end_date = st.date_input("結束日 (留空表示仍在住)", value=history_details.get('end_date'))
                                        clear_end_date_history = st.checkbox("清除結束日 (設為仍在住)", key=f"clear_end_hist_{selected_history_id}")
                                    
                                    edit_bed_number = ehc3.text_input("床位編號", value=history_details.get('bed_number') or "")
                                    edit_notes = st.text_area("備註", value=history_details.get('notes', ''))

                                    if st.form_submit_button("儲存歷史紀錄變更"):
                                        if not edit_room_id:
                                             st.error("必須選擇一個房間！")
                                        else:
                                             final_end_date = None if clear_end_date_history else (str(edit_end_date) if edit_end_date else None)
                                            
                                             update_data = {
                                                 "room_id": edit_room_id,
                                                 "start_date": str(edit_start_date) if edit_start_date else None,
                                                 "end_date": final_end_date, 
                                                 "bed_number": edit_bed_number,
                                                 "notes": edit_notes
                                             }
                                             
                                             success, message = worker_model.update_accommodation_history(selected_history_id, update_data)
                                             if success: st.success(message); st.cache_data.clear(); st.rerun()
                                             else: st.error(message)

                                st.markdown("##### 危險操作區")
                                confirm_delete_history = st.checkbox("我了解並確認要刪除此筆住宿歷史", key=f"delete_accom_{selected_history_id}")
                                if st.button("🗑️ 刪除此筆歷史", type="primary", disabled=not confirm_delete_history):
                                    success, message = worker_model.delete_accommodation_history(selected_history_id)
                                    if success: st.success(message); st.cache_data.clear(); st.rerun()
                                    else: st.error(message)
                
                elif selected_tab == "🕒 狀態歷史管理":
                    st.markdown("##### 新增一筆狀態紀錄")
                    with st.form("new_status_form", clear_on_submit=True):
                        s_c1, s_c2 = st.columns(2)
                        status_options = ["", "掛宿外住(不收費)", "掛宿外住(收費)", "費用不同", "其他"]
                        new_status = s_c1.selectbox("選擇新狀態 (若要改回正常在住，請留空)", status_options, key="new_status_selector")
                        start_date = s_c2.date_input("此狀態起始日", value=date.today())
                        status_notes = st.text_area("狀態備註 (選填)")
                        if st.form_submit_button("新增狀態"):
                            status_to_db = new_status if new_status else '在住'
                            status_details = { "worker_unique_id": selected_worker_id, "status": status_to_db, "start_date": str(start_date), "notes": status_notes }
                            success, message = worker_model.add_new_worker_status(status_details)
                            if success: st.success(message); st.cache_data.clear(); st.rerun()
                            else: st.error(message)

                    st.markdown("##### 狀態歷史紀錄")
                    history_df = worker_model.get_worker_status_history(selected_worker_id)
                    st.dataframe(history_df, width="stretch", hide_index=True, column_config={"id": None})
                    st.markdown("---")
                    st.subheader("編輯或刪除狀態")

                    if history_df.empty: st.info("此員工尚無任何歷史狀態紀錄。")
                    else:
                        status_options_dict = {row['id']: f"{row['起始日']} | {row['狀態']}" for _, row in history_df.iterrows()}
                        selected_status_id = st.selectbox("選擇要編輯或刪除的狀態紀錄：", [None] + list(status_options_dict.keys()), format_func=lambda x: "請選擇..." if x is None else status_options_dict.get(x), key=f"status_selector_{selected_worker_id}")
                        if selected_status_id:
                            status_details = worker_model.get_single_status_details(selected_status_id)
                            if status_details:
                                with st.form(f"edit_status_form_{selected_status_id}"):
                                    st.markdown(f"###### 正在編輯 ID: {status_details['id']} 的狀態")
                                    es_c1, es_c2, es_c3 = st.columns(3)
                                    status_options_edit = ["掛宿外住(不收費)", "掛宿外住(收費)", "費用不同", "其他"]
                                    current_status = status_details.get('status')
                                    try: index = status_options_edit.index(current_status)
                                    except ValueError: index = 0
                                    edit_status = es_c1.selectbox("狀態", status_options_edit, index=index)
                                    start_val, end_val = status_details.get('start_date'), status_details.get('end_date')
                                    edit_start_date = es_c2.date_input("起始日", value=start_val)
                                    
                                    with es_c3:
                                        edit_end_date = st.date_input("結束日 (若留空代表此為當前狀態)", value=end_val)
                                        clear_end_date_status = st.checkbox("清除結束日", key=f"clear_end_status_{selected_status_id}")
                                    
                                    edit_notes = st.text_area("狀態備註", value=status_details.get('notes', ''))

                                    if st.form_submit_button("儲存狀態變更"):
                                        final_end_date_status = None if clear_end_date_status else (str(edit_end_date) if edit_end_date else None)
                                        updated_details = {"status": edit_status, "start_date": str(edit_start_date) if edit_start_date else None, "end_date": final_end_date_status, "notes": edit_notes}
                                        
                                        success, message = worker_model.update_worker_status(selected_status_id, updated_details)
                                        if success: st.success(message); st.cache_data.clear(); st.rerun()
                                        else: st.error(message)

                                confirm_delete_status = st.checkbox("我了解並確認要刪除此筆狀態紀錄")
                                if st.button("🗑️ 刪除此狀態", type="primary", disabled=not confirm_delete_status):
                                    success, message = worker_model.delete_worker_status(selected_status_id)
                                    if success: st.success(message); st.cache_data.clear(); st.rerun()
                                    else: st.error(message)
                
                elif selected_tab == "💰 費用歷史":
                    st.markdown("##### 手動新增費用歷史")
                    with st.expander("點此展開以新增一筆費用歷史紀錄"):
                        with st.form("new_fee_history_form", clear_on_submit=True):
                            fee_type_options = ['房租', '水電費', '清潔費', '宿舍復歸費', '充電清潔費']
                            fc1, fc2, fc3 = st.columns(3)
                            new_fee_type = fc1.selectbox("費用類型", fee_type_options)
                            new_amount = fc2.number_input("金額", min_value=0, step=100)
                            new_effective_date = fc3.date_input("生效日期", value=date.today())

                            if st.form_submit_button("新增歷史紀錄"):
                                details = {"worker_unique_id": selected_worker_id, "fee_type": new_fee_type, "amount": new_amount, "effective_date": new_effective_date}
                                success, message = worker_model.add_fee_history(details)
                                if success: st.success(message); st.cache_data.clear(); st.rerun()
                                else: st.error(message)

                    st.markdown("---")
                    st.markdown("##### 費用變更歷史總覽")
                    fee_history_df = worker_model.get_fee_history_for_worker(selected_worker_id)
                    st.dataframe(fee_history_df, width="stretch", hide_index=True, column_config={"id": None})

                    st.markdown("---")
                    st.subheader("編輯或刪除單筆費用歷史")

                    if fee_history_df.empty: st.info("此員工尚無任何費用歷史可供編輯。")
                    else:
                        history_options = {row['id']: f"{row['生效日期']} | {row['費用類型']} | 金額: {row['金額']}" for _, row in fee_history_df.iterrows()}
                        selected_history_id = st.selectbox("請從上方列表選擇一筆紀錄進行操作：", [None] + list(history_options.keys()), format_func=lambda x: "請選擇..." if x is None else history_options.get(x), key=f"fee_history_selector_{selected_worker_id}")
                        if selected_history_id:
                            history_details = worker_model.get_single_fee_history_details(selected_history_id)
                            if history_details:
                                with st.form(f"edit_fee_history_form_{selected_history_id}"):
                                    st.markdown(f"###### 編輯 ID: {history_details['id']} 的紀錄")
                                    fee_type_options = ['房租', '水電費', '清潔費', '宿舍復歸費', '充電清潔費']
                                    try: default_index = fee_type_options.index(history_details.get('fee_type'))
                                    except ValueError: default_index = 0
                                    efc1, efc2, efc3 = st.columns(3)
                                    edit_fee_type = efc1.selectbox("費用類型", fee_type_options, index=default_index)
                                    edit_amount = efc2.number_input("金額", min_value=0, step=100, value=history_details.get('amount', 0))
                                    edit_effective_date = efc3.date_input("生效日期", value=history_details.get('effective_date'))

                                    if st.form_submit_button("儲存變更"):
                                        update_data = {"fee_type": edit_fee_type, "amount": edit_amount, "effective_date": edit_effective_date}
                                        success, message = worker_model.update_fee_history(selected_history_id, update_data)
                                        if success: st.success(message); st.cache_data.clear(); st.rerun()
                                        else: st.error(message)

                                st.markdown("##### 危險操作區")
                                confirm_delete_history = st.checkbox("我了解並確認要刪除此筆費用歷史", key=f"delete_fee_hist_{selected_history_id}")
                                if st.button("🗑️ 刪除此筆歷史", type="primary", disabled=not confirm_delete_history):
                                    success, message = worker_model.delete_fee_history(selected_history_id)
                                    if success: st.success(message); st.cache_data.clear(); st.rerun()
                                    else: st.error(message)