import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import worker_model, dormitory_model

def render():
    """渲染「人員管理」頁面"""
    st.header("移工住宿人員管理")

    if 'selected_worker_id' not in st.session_state:
        st.session_state.selected_worker_id = None

    # --- 1. 新增手動管理人員 (完整版) ---
    with st.expander("➕ 新增手動管理人員 (他仲等)"):
        with st.form("new_manual_worker_form", clear_on_submit=True):
            st.subheader("新人員基本資料")
            c1, c2, c3 = st.columns(3)
            employer_name = c1.text_input("雇主名稱 (必填)")
            worker_name = c2.text_input("移工姓名 (必填)")
            gender = c3.selectbox("性別", ["", "男", "女"])
            nationality = c1.text_input("國籍")
            passport_number = c2.text_input("護照號碼")
            arc_number = c3.text_input("居留證號")

            st.subheader("住宿與費用")
            dorms = dormitory_model.get_dorms_for_selection()
            dorm_options = {d['id']: d['original_address'] for d in dorms} if dorms else {}
            
            selected_dorm_id_new = st.selectbox("宿舍地址", options=[None] + list(dorm_options.keys()), format_func=lambda x: "未分配" if x is None else dorm_options[x], key="new_dorm_select")
            
            rooms = dormitory_model.get_rooms_for_selection(selected_dorm_id_new)
            room_options = {r['id']: r['room_number'] for r in rooms} if rooms else {}
            selected_room_id_new = st.selectbox("房間號碼", options=[None] + list(room_options.keys()), format_func=lambda x: "未分配" if x is None else room_options[x], key="new_room_select")
            
            f1, f2, f3 = st.columns(3)
            monthly_fee = f1.number_input("月費", min_value=0, step=100, key="new_fee")
            payment_method = f2.selectbox("付款方", ["員工自付", "雇主支付"], key="new_payment")
            accommodation_start_date = f3.date_input("起住日期", value=datetime.now())

            worker_notes = st.text_area("個人備註", key="new_notes")
            special_status = st.text_input("特殊狀況", key="new_status")

            submitted = st.form_submit_button("儲存新人員")
            if submitted:
                if not employer_name or not worker_name:
                    st.error("雇主和移工姓名為必填欄位！")
                else:
                    details = {
                        'unique_id': f"{employer_name}_{worker_name}",
                        'employer_name': employer_name, 'worker_name': worker_name,
                        'gender': gender, 'nationality': nationality,
                        'passport_number': passport_number, 'arc_number': arc_number,
                        'room_id': selected_room_id_new,
                        'monthly_fee': monthly_fee, 'payment_method': payment_method,
                        'accommodation_start_date': str(accommodation_start_date) if accommodation_start_date else None,
                        'worker_notes': worker_notes, 'special_status': special_status
                    }
                    success, message, _ = worker_model.add_manual_worker(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                    else:
                        st.error(message)

    st.markdown("---")

    # --- 2. 篩選與總覽 ---
    st.subheader("移工總覽")
    
    @st.cache_data
    def get_dorms_list():
        return dormitory_model.get_dorms_for_selection()

    dorms = get_dorms_list()
    
    # 新增保護機制，防止 dorms 為 None
    if dorms is None:
        dorms = [] # 如果查詢失敗，則給予一個空列表，避免程式崩潰
        st.error("讀取宿舍列表失敗，請檢查資料庫連線。")

    dorm_options = {d['id']: d['original_address'] for d in dorms}
    
    f_c1, f_c2, f_c3 = st.columns(3)
    name_search = f_c1.text_input("搜尋姓名或雇主")
    dorm_id_filter = f_c2.selectbox("篩選宿舍", options=[None] + list(dorm_options.keys()), format_func=lambda x: "全部宿舍" if x is None else dorm_options[x])
    status_filter = f_c3.selectbox("篩選在住狀態", ["全部", "在住", "已離住"])

    filters = {'name_search': name_search, 'dorm_id': dorm_id_filter, 'status': status_filter}
    
    workers_df = worker_model.get_workers_for_view(filters)
    
    selection = st.dataframe(workers_df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
    
    if selection.selection['rows']:
        st.session_state.selected_worker_id = workers_df.iloc[selection.selection['rows'][0]]['unique_id']
    
    # --- 3. 單一移工詳情與編輯 ---
    if st.session_state.selected_worker_id:
        worker_id = st.session_state.selected_worker_id
        worker_details = worker_model.get_single_worker_details(worker_id)
        
        if worker_details: # 增加檢查，確保成功獲取到資料
            st.subheader(f"編輯移工資料: {worker_details.get('worker_name')} ({worker_details.get('employer_name')})")

            with st.form("edit_worker_form"):
                
                # --- 住宿分配邏輯 ---
                st.markdown("##### 住宿分配")
                # 找到當前房間所屬的宿舍ID
                current_room_id = worker_details.get('room_id')
                current_dorm_id = None
                if current_room_id:
                    # 這邊可以再擴充 dormitory_model 來反查
                    # 為了簡化，我們先在UI層處理
                    for d in dorms:
                        rooms_in_dorm = dormitory_model.get_rooms_for_selection(d['id'])
                        if rooms_in_dorm and any(r['id'] == current_room_id for r in rooms_in_dorm):
                            current_dorm_id = d['id']
                            break
                
                # 建立宿舍下拉選單
                dorm_ids = list(dorm_options.keys())
                try:
                    current_dorm_index = dorm_ids.index(current_dorm_id) + 1 if current_dorm_id in dorm_ids else 0
                except (ValueError, TypeError):
                    current_dorm_index = 0

                selected_dorm_id = st.selectbox("宿舍地址", options=[None] + dorm_ids, 
                                                format_func=lambda x: "未分配" if x is None else dorm_options[x], 
                                                index=current_dorm_index, key="dorm_select_edit")
                
                # 根據選擇的宿舍，動態產生房間下拉選單
                rooms_in_selected_dorm = dormitory_model.get_rooms_for_selection(selected_dorm_id)
                if rooms_in_selected_dorm is None: rooms_in_selected_dorm = [] # 保護
                
                room_options = {r['id']: r['room_number'] for r in rooms_in_selected_dorm}
                room_ids = list(room_options.keys())

                try:
                    current_room_index = room_ids.index(current_room_id) + 1 if current_room_id in room_ids else 0
                except (ValueError, TypeError):
                    current_room_index = 0
                
                selected_room_id = st.selectbox("房間號碼", options=[None] + room_ids, 
                                                format_func=lambda x: "未分配" if x is None else room_options[x], 
                                                index=current_room_index)

                # --- 其他欄位編輯 ---
                st.markdown("##### 費用與狀態")
                m_c1, m_c2, m_c3 = st.columns(3)
                monthly_fee = m_c1.number_input("月費", value=worker_details.get('monthly_fee') or 0)
                payment_method_options = ["員工自付", "雇主支付"]
                payment_method = m_c2.selectbox("付款方", payment_method_options, index=payment_method_options.index(worker_details.get('payment_method')) if worker_details.get('payment_method') in payment_method_options else 0)
                
                end_date_value = None
                if worker_details.get('accommodation_end_date'):
                    try:
                        end_date_value = datetime.strptime(worker_details['accommodation_end_date'], '%Y-%m-%d').date()
                    except (ValueError, TypeError):
                        end_date_value = None
                accommodation_end_date = m_c3.date_input("離住日期 (若留空表示在住)", value=end_date_value)
                
                worker_notes = st.text_area("個人備註", value=worker_details.get('worker_notes') or "")

                submitted = st.form_submit_button("儲存變更")
                if submitted:
                    update_data = {
                        'room_id': selected_room_id,
                        'monthly_fee': monthly_fee,
                        'payment_method': payment_method,
                        'accommodation_end_date': str(accommodation_end_date) if accommodation_end_date else None,
                        'worker_notes': worker_notes
                    }
                    success, message = worker_model.update_worker_details(worker_id, update_data)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)