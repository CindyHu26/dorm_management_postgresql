import streamlit as st
import pandas as pd
from datetime import datetime, date
from data_models import worker_model, dormitory_model

def render():
    """渲染「人員管理」頁面"""
    st.header("移工住宿人員管理")
    
    # --- 1. 新增手動管理人員 ---
    with st.expander("➕ 新增手動管理人員 (他仲等)"):
        with st.form("new_manual_worker_form", clear_on_submit=True):
            st.subheader("新人員基本資料")
            c1, c2, c3 = st.columns(3)
            employer_name = c1.text_input("雇主名稱 (必填)")
            worker_name = c2.text_input("移工姓名 (必填)")
            passport_number = c3.text_input("護照號碼 (同名時必填)")
            
            gender = c1.selectbox("性別", ["", "男", "女"])
            nationality = c2.text_input("國籍")
            arc_number = c3.text_input("居留證號")

            st.subheader("住宿與費用")
            dorms = dormitory_model.get_dorms_for_selection() or []
            dorm_options = {d['id']: d['original_address'] for d in dorms}
            
            selected_dorm_id_new = st.selectbox("宿舍地址", [None] + list(dorm_options.keys()), format_func=lambda x: "未分配" if x is None else dorm_options.get(x))
            
            rooms = dormitory_model.get_rooms_for_selection(selected_dorm_id_new) or []
            room_options = {r['id']: r['room_number'] for r in rooms}
            selected_room_id_new = st.selectbox("房間號碼", [None] + list(room_options.keys()), format_func=lambda x: "未分配" if x is None else room_options.get(x))
            
            # 【核心修改】增加水電費和清潔費欄位
            f1, f2, f3 = st.columns(3)
            monthly_fee = f1.number_input("月費(房租)", min_value=0, step=100)
            utilities_fee = f2.number_input("水電費", min_value=0, step=100)
            cleaning_fee = f3.number_input("清潔費", min_value=0, step=100)

            ff1, ff2 = st.columns(2)
            payment_method = ff1.selectbox("付款方", ["", "員工自付", "雇主支付"])
            accommodation_start_date = ff2.date_input("起住日期", value=date.today())

            worker_notes = st.text_area("個人備註")
            
            st.subheader("初始狀態")
            s1, s2 = st.columns(2)
            initial_status_options = ["在住", "掛宿外住(不收費)", "掛宿外住(收費)", "費用不同", "其他"]
            initial_status = s1.selectbox("初始狀態", initial_status_options)
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
                    if pass_clean:
                        unique_id += f"_{pass_clean}"

                    details = {
                        'unique_id': unique_id,
                        'employer_name': emp_clean, 'worker_name': name_clean,
                        'passport_number': pass_clean if pass_clean else None,
                        'gender': gender, 'nationality': nationality, 'arc_number': arc_number,
                        'room_id': selected_room_id_new, 
                        'monthly_fee': monthly_fee, 
                        'utilities_fee': utilities_fee, # 新增
                        'cleaning_fee': cleaning_fee,   # 新增
                        'payment_method': payment_method,
                        'accommodation_start_date': str(accommodation_start_date) if accommodation_start_date else None,
                        'worker_notes': worker_notes
                    }
                    
                    status_details = {
                        'status': initial_status,
                        'start_date': str(accommodation_start_date) if accommodation_start_date else str(date.today()),
                        'notes': status_notes
                    }

                    success, message, _ = worker_model.add_manual_worker(details, status_details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

    st.markdown("---")

    # --- 2. 編輯與檢視區塊 ---
    st.subheader("編輯/檢視單一移工資料")
    
    @st.cache_data
    def get_editable_workers_list():
        return worker_model.get_my_company_workers_for_selection()

    editable_workers = get_editable_workers_list()
    
    if not editable_workers:
        st.info("目前沒有『我司』管理的宿舍中有在住人員可供編輯。")
    else:
        worker_options = {w['unique_id']: f"{w['employer_name']} / {w['worker_name']} (宿舍: {w['original_address']})" for w in editable_workers}
        
        selected_worker_id = st.selectbox(
            "請選擇要編輯或檢視的移工：",
            options=[None] + list(worker_options.keys()),
            format_func=lambda x: "請選擇..." if x is None else worker_options.get(x)
        )

        if selected_worker_id:
            worker_details = worker_model.get_single_worker_details(selected_worker_id)
            if not worker_details:
                st.error("找不到選定的移工資料，可能已被刪除。")
            else:
                st.markdown(f"#### 管理移工: {worker_details.get('worker_name')} ({worker_details.get('employer_name')})")
                
                # 【核心修改】新增「費用歷史」分頁
                tab1, tab2, tab3 = st.tabs(["✏️ 編輯核心資料", "🕒 狀態歷史管理", "💰 費用歷史"])
            
                with tab1:
                    with st.form("edit_worker_form"):
                        st.info(f"資料來源: **{worker_details.get('data_source')}**")

                        st.markdown("##### 基本資料 (多由系統同步)")
                        ec1, ec2, ec3 = st.columns(3)
                        ec1.text_input("性別", value=worker_details.get('gender'), disabled=True)
                        ec2.text_input("國籍", value=worker_details.get('nationality'), disabled=True)
                        ec3.text_input("護照號碼", value=worker_details.get('passport_number'), disabled=True)
                        
                        st.markdown("##### 住宿分配 (可手動修改)")
                        all_dorms = dormitory_model.get_dorms_for_selection() or []
                        all_dorm_options = {d['id']: d['original_address'] for d in all_dorms}
                        
                        current_room_id = worker_details.get('room_id')
                        current_dorm_id = dormitory_model.get_dorm_id_from_room_id(current_room_id)
                        dorm_ids = list(all_dorm_options.keys())
                        
                        try:
                            current_dorm_index = dorm_ids.index(current_dorm_id) + 1 if current_dorm_id in dorm_ids else 0
                        except (ValueError, TypeError):
                            current_dorm_index = 0
                        
                        selected_dorm_id_edit = st.selectbox("宿舍地址", options=[None] + dorm_ids, 
                                                            format_func=lambda x: "未分配" if x is None else all_dorm_options.get(x), 
                                                            index=current_dorm_index)
                        
                        rooms = dormitory_model.get_rooms_for_selection(selected_dorm_id_edit) or []
                        room_options = {r['id']: r['room_number'] for r in rooms}
                        room_ids = list(room_options.keys())

                        try:
                            current_room_index = room_ids.index(current_room_id) + 1 if current_room_id in room_ids else 0
                        except (ValueError, TypeError):
                            current_room_index = 0
                        
                        selected_room_id = st.selectbox("房間號碼", options=[None] + room_ids, 
                                                        format_func=lambda x: "未分配" if x is None else room_options.get(x), 
                                                        index=current_room_index)

                        st.markdown("##### 費用與狀態 (可手動修改)")
                        # 【核心修改】增加水電費和清潔費的輸入框
                        fc1, fc2, fc3 = st.columns(3)
                        monthly_fee = fc1.number_input("月費(房租)", value=int(worker_details.get('monthly_fee') or 0))
                        utilities_fee = fc2.number_input("水電費", value=int(worker_details.get('utilities_fee') or 0))
                        cleaning_fee = fc3.number_input("清潔費", value=int(worker_details.get('cleaning_fee') or 0))

                        fcc1, fcc2 = st.columns(2)
                        payment_method_options = ["", "員工自付", "雇主支付"]
                        payment_method = fcc1.selectbox("付款方", payment_method_options, index=payment_method_options.index(worker_details.get('payment_method')) if worker_details.get('payment_method') in payment_method_options else 0)
                        
                        end_date_value = worker_details.get('accommodation_end_date')
                        accommodation_end_date = fcc2.date_input("離住日期 (若留空表示在住)", value=end_date_value)
                        
                        worker_notes = st.text_area("個人備註", value=worker_details.get('worker_notes') or "")
                        
                        submitted = st.form_submit_button("儲存核心資料變更")
                        if submitted:
                            update_data = {
                                'room_id': selected_room_id, 
                                'monthly_fee': monthly_fee,
                                'utilities_fee': utilities_fee, # 新增
                                'cleaning_fee': cleaning_fee,   # 新增
                                'payment_method': payment_method,
                                'accommodation_end_date': str(accommodation_end_date) if accommodation_end_date else None,
                                'worker_notes': worker_notes
                            }
                            success, message = worker_model.update_worker_details(selected_worker_id, update_data)
                            if success:
                                st.success(message)
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(message)

                    st.markdown("---")
                    st.markdown("##### 危險操作區")
                    confirm_delete = st.checkbox("我了解並確認要刪除此移工的資料")
                    if st.button("🗑️ 刪除此移工", type="primary", disabled=not confirm_delete):
                        success, message = worker_model.delete_worker_by_id(selected_worker_id)
                        if success:
                            st.success(message)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(message)

                with tab2:
                    st.markdown("##### 新增一筆狀態紀錄")
                    with st.form("new_status_form", clear_on_submit=True):
                        s_c1, s_c2 = st.columns(2)
                        status_options = ["在住", "掛宿外住(不收費)", "掛宿外住(收費)", "費用不同", "其他"]
                        new_status = s_c1.selectbox("選擇新狀態", status_options)
                        start_date = s_c2.date_input("此狀態起始日", value=date.today())
                        status_notes = st.text_area("狀態備註 (選填)")

                        status_submitted = st.form_submit_button("新增狀態")
                        if status_submitted:
                            status_details = {
                                "worker_unique_id": selected_worker_id,
                                "status": new_status,
                                "start_date": str(start_date),
                                "notes": status_notes
                            }
                            success, message = worker_model.add_new_worker_status(status_details)
                            if success:
                                st.success(message)
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(message)
                    
                    st.markdown("##### 狀態歷史紀錄")
                    history_df = worker_model.get_worker_status_history(selected_worker_id)
                    st.dataframe(history_df, use_container_width=True, hide_index=True, column_config={"id": None})

                    st.markdown("---")
                    st.subheader("編輯或刪除狀態")

                    # 狀態選取下拉選單
                    if history_df.empty:
                        st.info("此員工尚無任何歷史狀態紀錄。")
                        selected_status_id = None
                    else:
                        status_options = {row['id']: f"{row['起始日']} | {row['狀態']}" for _, row in history_df.iterrows()}
                        selected_status_id = st.selectbox(
                            "選擇要編輯或刪除的狀態紀錄：",
                            options=[None] + list(status_options.keys()),
                            format_func=lambda x: "請選擇..." if x is None else status_options.get(x)
                        )

                    # --- 編輯區塊 ---
                    if selected_status_id:
                        status_details = worker_model.get_single_status_details(selected_status_id)
                        if status_details:
                            with st.form("edit_status_form"):
                                st.markdown(f"###### 正在編輯 ID: {status_details['id']} 的狀態")
                                es_c1, es_c2, es_c3 = st.columns(3)
                                
                                status_options_edit = ["在住", "掛宿外住(不收費)", "掛宿外住(收費)", "費用不同", "其他"]
                                current_status = status_details.get('status')
                                edit_status = es_c1.selectbox("狀態", status_options_edit, index=status_options_edit.index(current_status) if current_status in status_options_edit else 0)
                                
                                start_val = status_details.get('start_date')
                                end_val = status_details.get('end_date')
                                    
                                edit_start_date = es_c2.date_input("起始日", value=start_val)
                                edit_end_date = es_c3.date_input("結束日 (若留空代表此為當前狀態)", value=end_val)
                                  
                                edit_notes = st.text_area("狀態備註", value=status_details.get('notes', ''))

                                edit_submitted = st.form_submit_button("儲存狀態變更")
                                if edit_submitted:
                                    updated_details = {
                                        "status": edit_status,
                                        "start_date": str(edit_start_date) if edit_start_date else None,
                                        "end_date": str(edit_end_date) if edit_end_date else None,
                                        "notes": edit_notes
                                    }
                                    success, message = worker_model.update_worker_status(selected_status_id, updated_details)
                                    if success:
                                        st.success(message)
                                        st.cache_data.clear()
                                        st.rerun()
                                    else:
                                        st.error(message)

                            confirm_delete = st.checkbox("我了解並確認要刪除此筆狀態紀錄")
                            if st.button("🗑️ 刪除此狀態", type="primary", disabled=not confirm_delete):
                                success, message = worker_model.delete_worker_status(selected_status_id)
                                if success:
                                    st.success(message)
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(message)

                       
    st.markdown("---")
    
    # --- 3. 移工總覽 (僅供檢視) ---
    st.subheader("移工總覽 (所有宿舍)")
    
    @st.cache_data
    def get_dorms_list():
        return dormitory_model.get_dorms_for_selection()

    dorms = get_dorms_list() or []
    dorm_options = {d['id']: d['original_address'] for d in dorms}
    
    f_c1_view, f_c2_view, f_c3_view = st.columns(3)
    name_search = f_c1_view.text_input("搜尋姓名、雇主或地址 ")
    dorm_id_filter = f_c2_view.selectbox("篩選宿舍 ", options=[None] + list(dorm_options.keys()), format_func=lambda x: "全部宿舍" if x is None else dorm_options.get(x))
    status_filter = f_c3_view.selectbox("篩選在住狀態 ", ["全部", "在住", "已離住"])

    filters = {'name_search': name_search, 'dorm_id': dorm_id_filter, 'status': status_filter}
    
    workers_df = worker_model.get_workers_for_view(filters)
    
    st.dataframe(workers_df, use_container_width=True, hide_index=True)