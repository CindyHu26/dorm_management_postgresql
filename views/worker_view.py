import streamlit as st
import pandas as pd
from datetime import datetime, date
from data_models import worker_model, dormitory_model

def render():
    """【v2.0 修改版】渲染「人員管理」頁面"""
    st.header("移工住宿人員管理")
    
    # --- 1. 新增手動管理人員 (此區塊邏輯不變) ---
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
            
            selected_dorm_id_new = st.selectbox("宿舍地址", [None] + list(dorm_options.keys()), format_func=lambda x: "未分配" if x is None else dorm_options.get(x), key="new_dorm_select")
            
            rooms = dormitory_model.get_rooms_for_selection(selected_dorm_id_new) or []
            room_options = {r['id']: r['room_number'] for r in rooms}
            selected_room_id_new = st.selectbox("房間號碼", [None] + list(room_options.keys()), format_func=lambda x: "未分配" if x is None else room_options.get(x), key="new_room_select")
            
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
                        'unique_id': unique_id, 'employer_name': emp_clean, 'worker_name': name_clean,
                        'passport_number': pass_clean if pass_clean else None,
                        'gender': gender, 'nationality': nationality, 'arc_number': arc_number,
                        'room_id': selected_room_id_new, 'monthly_fee': monthly_fee, 
                        'utilities_fee': utilities_fee, 'cleaning_fee': cleaning_fee,
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

    # --- 2. 編輯與檢視區塊 (核心修改處) ---
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
                
                # --- 核心修改：重新設計 Tab 結構 ---
                tab1, tab2, tab3, tab4 = st.tabs(["🏠 住宿歷史管理", "✏️ 編輯核心資料", "🕒 狀態歷史管理", "💰 費用歷史"])
            
                # --- 新增：住宿歷史分頁 ---
                with tab1:
                    st.markdown("##### 新增一筆住宿紀錄 (換宿)")
                    with st.form("new_accommodation_form"):
                        st.info("當工人更換房間或宿舍時，請在此處新增一筆紀錄。系統將自動結束前一筆紀錄。")
                        
                        ac1, ac2, ac3 = st.columns(3)
                        
                        all_dorms = dormitory_model.get_dorms_for_selection() or []
                        all_dorm_options = {d['id']: d['original_address'] for d in all_dorms}
                        selected_dorm_id_ac = ac1.selectbox("新宿舍地址", options=all_dorm_options.keys(), format_func=lambda x: all_dorm_options.get(x), key="ac_dorm")
                        
                        rooms_ac = dormitory_model.get_rooms_for_selection(selected_dorm_id_ac) or []
                        room_options_ac = {r['id']: r['room_number'] for r in rooms_ac}
                        selected_room_id_ac = ac2.selectbox("新房間號碼", options=room_options_ac.keys(), format_func=lambda x: room_options_ac.get(x), key="ac_room")
                        
                        change_date = ac3.date_input("換宿生效日期", value=date.today())
                        
                        ac_submitted = st.form_submit_button("🚀 執行換宿")
                        if ac_submitted:
                            if not selected_room_id_ac:
                                st.error("必須選擇一個新的房間！")
                            else:
                                success, message = worker_model.change_worker_accommodation(selected_worker_id, selected_room_id_ac, change_date)
                                if success:
                                    st.success(message)
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(message)

                    st.markdown("---")
                    st.markdown("##### 歷史住宿紀錄")
                    accommodation_history_df = worker_model.get_accommodation_history_for_worker(selected_worker_id)
                    st.dataframe(accommodation_history_df, use_container_width=True, hide_index=True, column_config={"id": None})

                    # --- 編輯與刪除歷史紀錄的介面 ---
                    st.markdown("---")
                    st.subheader("編輯或刪除單筆住宿歷史")

                    if accommodation_history_df.empty:
                        st.info("此員工尚無任何住宿歷史紀錄可供編輯。")
                    else:
                        history_options = {row['id']: f"{row['起始日']} ~ {row.get('結束日', '至今')} | {row['宿舍地址']} {row['房號']}" for _, row in accommodation_history_df.iterrows()}
                        selected_history_id = st.selectbox(
                            "請從上方列表選擇一筆紀錄進行操作：",
                            options=[None] + list(history_options.keys()),
                            format_func=lambda x: "請選擇..." if x is None else history_options.get(x)
                        )

                        if selected_history_id:
                            history_details = worker_model.get_single_accommodation_details(selected_history_id)
                            if history_details:
                                with st.form(f"edit_history_form_{selected_history_id}"):
                                    st.markdown(f"###### 正在編輯 ID: {history_details['id']} 的紀錄")
                                    
                                    # 房間資訊僅供顯示，不允許修改，避免破壞資料關聯性
                                    current_room_id = history_details.get('room_id')
                                    dorm_id = dormitory_model.get_dorm_id_from_room_id(current_room_id)
                                    dorm_name = dormitory_model.get_dorm_details_by_id(dorm_id).get('original_address', '未知宿舍')
                                    room_name = dormitory_model.get_single_room_details(current_room_id).get('room_number', '未知房間')
                                    st.text_input("住宿位置", value=f"{dorm_name} {room_name}", disabled=True, help="如需變更房間，請使用上方的「新增住宿紀錄」功能。")

                                    ehc1, ehc2 = st.columns(2)
                                    edit_start_date = ehc1.date_input("起始日", value=history_details.get('start_date'))
                                    edit_end_date = ehc2.date_input("結束日 (留空表示仍在住)", value=history_details.get('end_date'))
                                    edit_notes = st.text_area("備註", value=history_details.get('notes', ''))

                                    edit_submitted = st.form_submit_button("儲存歷史紀錄變更")
                                    if edit_submitted:
                                        update_data = {
                                            "start_date": edit_start_date,
                                            "end_date": edit_end_date,
                                            "notes": edit_notes
                                        }
                                        success, message = worker_model.update_accommodation_history(selected_history_id, update_data)
                                        if success:
                                            st.success(message)
                                            st.cache_data.clear()
                                            st.rerun()
                                        else:
                                            st.error(message)
                                
                                st.markdown("##### 危險操作區")
                                confirm_delete_history = st.checkbox("我了解並確認要刪除此筆住宿歷史", key=f"delete_accom_{selected_history_id}")
                                if st.button("🗑️ 刪除此筆歷史", type="primary", disabled=not confirm_delete_history):
                                    success, message = worker_model.delete_accommodation_history(selected_history_id)
                                    if success:
                                        st.success(message)
                                        st.cache_data.clear()
                                        st.rerun()
                                    else:
                                        st.error(message)

                with tab2:
                    with st.form("edit_worker_form"):
                        st.info(f"資料來源: **{worker_details.get('data_source')}**")

                        st.markdown("##### 基本資料 (多由系統同步)")
                        ec1, ec2, ec3 = st.columns(3)
                        ec1.text_input("性別", value=worker_details.get('gender'), disabled=True)
                        ec2.text_input("國籍", value=worker_details.get('nationality'), disabled=True)
                        ec3.text_input("護照號碼", value=worker_details.get('passport_number'), disabled=True)
                        
                        # 住宿分配介面已移至新 Tab，此處不再提供修改
                        # st.markdown("##### 住宿分配")
                        # st.info("工人的住宿地點管理已移至「🏠 住宿歷史管理」分頁。")

                        st.markdown("##### 費用與狀態 (可手動修改)")
                        fc1, fc2, fc3 = st.columns(3)
                        monthly_fee = fc1.number_input("月費(房租)", value=int(worker_details.get('monthly_fee') or 0))
                        utilities_fee = fc2.number_input("水電費", value=int(worker_details.get('utilities_fee') or 0))
                        cleaning_fee = fc3.number_input("清潔費", value=int(worker_details.get('cleaning_fee') or 0))

                        fcc1, fcc2 = st.columns(2)
                        payment_method_options = ["", "員工自付", "雇主支付"]
                        payment_method = fcc1.selectbox("付款方", payment_method_options, index=payment_method_options.index(worker_details.get('payment_method')) if worker_details.get('payment_method') in payment_method_options else 0)
                        
                        end_date_value = worker_details.get('accommodation_end_date')
                        accommodation_end_date = fcc2.date_input("最終離住日期 (若留空表示在住)", value=end_date_value)
                        
                        worker_notes = st.text_area("個人備註", value=worker_details.get('worker_notes') or "")
                        
                        submitted = st.form_submit_button("儲存核心資料變更")
                        if submitted:
                            update_data = {
                                'monthly_fee': monthly_fee, 'utilities_fee': utilities_fee, 'cleaning_fee': cleaning_fee,
                                'payment_method': payment_method,
                                'accommodation_end_date': str(accommodation_end_date) if accommodation_end_date else None,
                                'worker_notes': worker_notes
                            }
                            # 注意：這裡呼叫的函式不再包含 room_id
                            success, message = worker_model.update_worker_details(selected_worker_id, update_data)
                            if success:
                                st.success(message)
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(message)
                    
                    st.markdown("---")
                    st.markdown("##### 危險操作區")
                    
                    # --- 新增：解除鎖定功能 ---
                    if worker_details.get('data_source') == '手動調整':
                        st.warning("此工人的住宿位置目前為手動鎖定狀態，不受每日自動同步影響。")
                        if st.button("🔓 解除鎖定，恢復自動同步"):
                            # success, message = worker_model.reset_worker_data_source(selected_worker_id)
                            # if success:
                            #     st.success(message)
                            #     st.cache_data.clear()
                            #     st.rerun()
                            # else:
                            #     st.error(message)
                            st.info("解鎖功能待後端新增對應函式後實作。")


                    confirm_delete = st.checkbox("我了解並確認要刪除此移工的資料")
                    if st.button("🗑️ 刪除此移工", type="primary", disabled=not confirm_delete):
                        success, message = worker_model.delete_worker_by_id(selected_worker_id)
                        if success:
                            st.success(message)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(message)

                with tab3: # 狀態歷史管理
                    st.markdown("##### 新增一筆狀態紀錄")
                    # ... (此處程式碼維持不變)
                    with st.form("new_status_form", clear_on_submit=True):
                        s_c1, s_c2 = st.columns(2)
                        status_options = ["在住", "掛宿外住(不收費)", "掛宿外住(收費)", "費用不同", "其他"]
                        new_status = s_c1.selectbox("選擇新狀態", status_options)
                        start_date = s_c2.date_input("此狀態起始日", value=date.today())
                        status_notes = st.text_area("狀態備註 (選填)")

                        status_submitted = st.form_submit_button("新增狀態")
                        if status_submitted:
                            status_details = { "worker_unique_id": selected_worker_id, "status": new_status, "start_date": str(start_date), "notes": status_notes }
                            success, message = worker_model.add_new_worker_status(status_details)
                            if success:
                                st.success(message)
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(message)
                    
                    st.markdown("##### 狀態歷史紀錄")
                    # ... (此處程式碼維持不變)
                    history_df = worker_model.get_worker_status_history(selected_worker_id)
                    st.dataframe(history_df, use_container_width=True, hide_index=True, column_config={"id": None})
                
                with tab4: # 費用歷史
                    st.markdown("##### 費用變更歷史紀錄")
                    fee_history_df = worker_model.get_fee_history_for_worker(selected_worker_id)
                    st.dataframe(fee_history_df, use_container_width=True, hide_index=True)


    st.markdown("---")
    
    # --- 3. 移工總覽 (此區塊邏輯不變) ---
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