import streamlit as st
import pandas as pd
import os
from datetime import date
from data_models import worker_model, dormitory_model
import utils

# --- 常數定義 ---
TAB_CORE = "核心資料"
TAB_ACCOM = "🏠 住宿歷史管理"
TAB_STATUS = "🕒 狀態歷史管理"
TAB_FEE = "💰 費用歷史"
TAB_NAMES = [TAB_CORE, TAB_ACCOM, TAB_STATUS, TAB_FEE]

def render_worker_view():
    """
    移工管理主視圖入口
    """
    st.title("👥 移工資料管理系統")

    # 定義主功能選單
    main_options = [
        "1. 移工總覽 (所有宿舍)、編輯/檢視單一移工資料", 
        "2. ➕ 新增手動管理人員 (他仲等)"
    ]
    
    # 使用 radio 讓使用者切換模式
    mode = st.radio("功能選擇", main_options, horizontal=True)

    if mode == main_options[0]:
        render_main_worker_list()
    elif mode == main_options[1]:
        render_add_manual_worker()

def render_main_worker_list():
    """
    渲染移工總覽列表與篩選器
    """
    st.markdown("---")
    
    # --- 1. 篩選區塊 ---
    with st.expander("🔍 篩選條件 (點擊展開)", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        
        # 取得篩選選項資料
        all_dorms = dormitory_model.get_dorms_for_selection()
        dorm_options = {d['id']: d['original_address'] for d in all_dorms}
        
        # 宿舍篩選
        selected_dorm_id = col1.selectbox(
            "宿舍", 
            options=[None] + list(dorm_options.keys()), 
            format_func=lambda x: "全部" if x is None else dorm_options[x]
        )
        
        # 關鍵字搜尋
        search_query = col2.text_input("搜尋 (姓名/房號/雇主)", placeholder="輸入關鍵字...")
        
        # 狀態篩選
        status_filter = col3.selectbox("在住狀態", ["全部", "在住", "已離住"], index=1)
        
        # 排序
        sort_by = col4.selectbox("排序方式", ["房號", "姓名", "入職日", "離住日"])

    # --- 2. 獲取資料 ---
    # 這裡假設 worker_model.get_all_workers 支援這些參數
    # 如果你的 model 參數不同，請自行調整
    workers_df = worker_model.get_all_workers(
        dorm_id=selected_dorm_id, 
        search=search_query, 
        status=status_filter,
        sort_by=sort_by
    )

    # --- 3. 顯示列表 ---
    st.markdown(f"**共找到 {len(workers_df)} 筆資料**")
    
    # 簡單顯示 DataFrame 供瀏覽
    display_cols = ['宿舍', '房號', '床位', '姓名', '雇主', '國籍', '性別', '在住狀態']
    # 過濾出存在的欄位以免報錯
    existing_cols = [c for c in display_cols if c in workers_df.columns]
    
    st.dataframe(
        workers_df[existing_cols], 
        use_container_width=True, 
        hide_index=True
    )

    st.markdown("---")
    
    # --- 4. 進入詳細編輯模式 ---
    render_worker_management_section(workers_df)

def render_worker_management_section(workers_df):
    """
    單一移工編輯/檢視區塊
    """
    st.subheader("編輯/檢視單一移工資料")

    if workers_df.empty:
        st.info("目前沒有符合篩選條件的工人資料可供編輯。")
        return

    # 建立選單選項：ID -> 顯示字串
    worker_options = {
        row['unique_id']: ( 
            f"{row.get('雇主', 'NA')} / "
            f"{row.get('姓名', 'N/A')} / "
            f"房號:{row.get('房號', 'N/A')} "
            f"({row.get('在住狀態', '')})"
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

            # --- 分頁導航 (使用 Radio 模擬 Tabs) ---
            selected_tab = st.radio("管理選項:", TAB_NAMES, key="worker_active_tab", horizontal=True, label_visibility="collapsed")
            st.write("---")

            # ==========================================
            # 分頁 1: 編輯/檢視核心資料
            # ==========================================
            if selected_tab == TAB_CORE:
                with st.form("edit_worker_form"):
                    st.info(f"資料來源: **{worker_details.get('data_source')}**")

                    # --- 照片區塊 ---
                    st.markdown("##### 📷 最新住宿照片 (唯讀)")
                    kp1, kp2 = st.columns(2)
                    with kp1:
                        st.markdown("**📥 入住時照片**")
                        latest_in_photos = worker_details.get('checkin_photo_paths') or []
                        valid_in = [p for p in latest_in_photos if os.path.exists(p)]
                        if valid_in: st.image(valid_in, width=150, caption=[os.path.basename(p) for p in valid_in])
                        else: st.caption("(無照片)")
                    with kp2:
                        st.markdown("**📤 退宿時照片**")
                        latest_out_photos = worker_details.get('checkout_photo_paths') or []
                        valid_out = [p for p in latest_out_photos if os.path.exists(p)]
                        if valid_out: st.image(valid_out, width=150, caption=[os.path.basename(p) for p in valid_out])
                        else: st.caption("(無照片)")
                    st.markdown("---")

                    # --- 基本資料區塊 ---
                    st.markdown("##### 基本資料 (唯讀對照)")
                    ec1, ec2, ec3 = st.columns(3)
                    ec1.text_input("性別 (原)", value=worker_details.get('gender'), disabled=True)
                    ec2.text_input("國籍 (原)", value=worker_details.get('nationality'), disabled=True)
                    ec3.text_input("護照 (原)", value=worker_details.get('passport_number'), disabled=True)

                    st.markdown("##### 基本資料 (可編輯修正)")
                    
                    # 準備國籍選項
                    nationality_options = ["", "越南", "印尼", "泰國", "菲律賓", "其他"]
                    current_nat = worker_details.get('nationality', '')
                    if current_nat and current_nat not in nationality_options:
                        nationality_options.append(current_nat)
                    
                    e1, e2, e3, e4 = st.columns(4)
                    
                    # 1. 性別
                    gender_opts = ["", "男", "女"]
                    curr_gender = worker_details.get('gender', '')
                    e_gender = e1.selectbox("性別", gender_opts, index=gender_opts.index(curr_gender) if curr_gender in gender_opts else 0)
                    
                    # 2. 國籍
                    try: nat_index = nationality_options.index(current_nat)
                    except ValueError: nat_index = 0
                    e_nationality = e2.selectbox("國籍", options=nationality_options, index=nat_index)
                    
                    # 3. 護照
                    e_passport = e3.text_input("護照號碼", value=worker_details.get('passport_number', ''))
                    
                    # 4. 居留證
                    e_arc = e4.text_input("居留證號碼", value=worker_details.get('arc_number', ''))

                    st.markdown("##### 其他資訊")
                    other1, other2 = st.columns(2)
                    
                    # 付款方
                    pymt = worker_details.get('payment_method')
                    pymt_opts = ["雇主", "仲介", "移工自付"]
                    payment_method = other1.selectbox("付款方", pymt_opts, index=pymt_opts.index(pymt) if pymt in pymt_opts else 0)
                    
                    # 離住日 (核心資料的離住日)
                    sys_end_date = worker_details.get('accommodation_end_date')
                    acc_end_date_val = pd.to_datetime(sys_end_date).date() if sys_end_date else None
                    accommodation_end_date = other2.date_input("離住日期 (若未離住請留空)", value=acc_end_date_val)
                    clear_end_date = other2.checkbox("清除離住日期 (設為在住)", value=(sys_end_date is None))

                    worker_notes = st.text_area("備註", value=worker_details.get('worker_notes', ''))

                    if st.form_submit_button("💾 儲存核心資料變更"):
                        final_end_date = None if clear_end_date else (str(accommodation_end_date) if accommodation_end_date else None)
                        
                        update_data = {
                            'payment_method': payment_method if payment_method else None, 
                            'worker_notes': worker_notes if worker_notes else None,
                            'accommodation_end_date': final_end_date, 
                            'gender': e_gender if e_gender else None,
                            'nationality': e_nationality if e_nationality else None,
                            'passport_number': e_passport if e_passport else None,
                            'arc_number': e_arc if e_arc else None
                        }
                        success, message = worker_model.update_worker_details(selected_worker_id, update_data)
                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)

                # --- 資料來源/鎖定區塊 ---
                st.markdown("---")
                st.markdown("##### 🔒 資料來源與鎖定管理 (危險操作)")
                current_data_source = worker_details.get('data_source')

                if current_data_source in ['手動調整', '手動管理(他仲)']:
                    if current_data_source == '手動調整': 
                        st.warning("此工人的「住宿位置」為手動鎖定，不受自動同步影響。")
                    else: 
                        st.error("此工人已被「完全鎖定」，系統不會自動更新任何資料。")

                    if st.button("🔓 解除鎖定，恢復系統自動同步"):
                        success, message = worker_model.reset_worker_data_source(selected_worker_id)
                        if success: st.success(message); st.rerun()
                        else: st.error(message)
                
                st.write("")
                lock_col1, lock_col2 = st.columns(2)
                with lock_col1:
                    if current_data_source == '系統自動更新':
                        if st.button("🔒 設為手動調整 (保護住宿位置)"):
                            success, message = worker_model.set_worker_as_manual_adjustment(selected_worker_id)
                            if success: st.success(message); st.rerun()
                with lock_col2:
                        if current_data_source != '手動管理(他仲)':
                        # 注意：這裡使用 primary type 提醒
                            if st.button("🔒 設為完全鎖定 (保護所有資料)", type="primary"):
                                success, message = worker_model.set_worker_as_fully_manual(selected_worker_id)
                                if success: st.success(message); st.rerun()

                # 刪除人員
                st.markdown("---")
                confirm_delete = st.checkbox("我了解並確認要刪除此移工的資料")
                if st.button("🗑️ 刪除此移工", type="primary", disabled=not confirm_delete):
                    success, message = worker_model.delete_worker_by_id(selected_worker_id)
                    if success: st.success(message); st.rerun()
                    else: st.error(message)

            # ==========================================
            # 分頁 2: 住宿歷史管理
            # ==========================================
            elif selected_tab == TAB_ACCOM:
                st.markdown("##### 🚀 新增一筆住宿紀錄 (換宿)")
                st.info("當工人更換房間或宿舍時，請在此處新增一筆紀錄。系統將自動結束前一筆紀錄。")

                ac1, ac2, ac3 = st.columns(3)
                # 獲取所有宿舍供選擇
                all_dorms = dormitory_model.get_dorms_for_selection() or []
                all_dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in all_dorms}
                
                selected_dorm_id_ac = ac1.selectbox("新宿舍地址", options=all_dorm_options.keys(), format_func=lambda x: all_dorm_options.get(x), key="ac_dorm_select")
                
                # 根據宿舍選擇房間
                rooms_ac = dormitory_model.get_rooms_for_selection(selected_dorm_id_ac) or []
                room_options_ac = {r['id']: r['room_number'] for r in rooms_ac}
                selected_room_id_ac = ac2.selectbox("新房間號碼", options=room_options_ac.keys(), format_func=lambda x: room_options_ac.get(x), key="ac_room_select")
                
                new_bed_number = ac3.text_input("新床位編號 (例如: A-01)")
                change_date = st.date_input("換宿生效日期", value=date.today(), key="ac_change_date")

                if st.button("確認換宿"):
                    if not selected_room_id_ac: st.error("必須選擇一個新的房間！")
                    else:
                        success, message = worker_model.change_worker_accommodation(selected_worker_id, selected_room_id_ac, change_date, bed_number=new_bed_number)
                        if success: st.success(message); st.rerun()
                        else: st.error(message)

                st.markdown("---")
                st.markdown("##### 📜 歷史住宿紀錄列表")
                accommodation_history_df = worker_model.get_accommodation_history_for_worker(selected_worker_id)
                st.dataframe(accommodation_history_df, use_container_width=True, hide_index=True, column_config={"id": None})

                st.markdown("---")
                st.subheader("✏️ 編輯或刪除單筆住宿歷史")

                if accommodation_history_df.empty:
                    st.info("此員工尚無任何住宿歷史紀錄可供編輯。")
                else:
                    # 製作下拉選單
                    history_options = {row['id']: f"{row['起始日']} ~ {row.get('結束日', '至今')} | {row['宿舍地址']} {row['房號']} (床位: {row.get('床位編號') or '未指定'})" for _, row in accommodation_history_df.iterrows()}
                    selected_history_id = st.selectbox("請從上方列表選擇一筆紀錄進行操作：", [None] + list(history_options.keys()), format_func=lambda x: "請選擇..." if x is None else history_options.get(x), key=f"history_selector_{selected_worker_id}")
                    
                    if selected_history_id:
                        history_details = worker_model.get_single_accommodation_details(selected_history_id)
                        if history_details:
                            with st.form(f"edit_history_form_{selected_history_id}"):
                                st.markdown(f"###### 正在編輯 ID: {history_details['id']} 的紀錄")

                                # --- 複雜的連動選單邏輯 (使用 Session State) ---
                                current_room_id = history_details.get('room_id')
                                current_dorm_id = dormitory_model.get_dorm_id_from_room_id(current_room_id)

                                # 1. 準備宿舍資料
                                all_dorms_edit = dormitory_model.get_dorms_for_selection() or []
                                all_dorm_options_edit = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in all_dorms_edit}
                                dorm_keys_edit = list(all_dorm_options_edit.keys())
                                
                                # 2. Session State key
                                dorm_select_key = f"edit_hist_dorm_{selected_history_id}"

                                # 3. 初始化宿舍 (若 key 不存在)
                                if dorm_select_key not in st.session_state:
                                    if current_dorm_id in dorm_keys_edit: st.session_state[dorm_select_key] = current_dorm_id
                                    elif dorm_keys_edit: st.session_state[dorm_select_key] = dorm_keys_edit[0]

                                # 4. 宿舍選單
                                edit_dorm_id = st.selectbox("宿舍地址", options=dorm_keys_edit, format_func=lambda x: all_dorm_options_edit.get(x), key=dorm_select_key)

                                # 5. 準備房間資料
                                rooms_edit = dormitory_model.get_rooms_for_selection(edit_dorm_id) or []
                                room_options_edit = {r['id']: r['room_number'] for r in rooms_edit}
                                room_keys_edit = list(room_options_edit.keys())
                                
                                room_select_key = f"edit_hist_room_{selected_history_id}"

                                # 6. 初始化或重設房間
                                if room_select_key not in st.session_state:
                                    if current_room_id in room_keys_edit: st.session_state[room_select_key] = current_room_id
                                    else: st.session_state[room_select_key] = room_keys_edit[0] if room_keys_edit else None
                                else:
                                    # 如果切換宿舍導致原本選的房間不在新清單中，重設
                                    if st.session_state[room_select_key] not in room_keys_edit:
                                            st.session_state[room_select_key] = room_keys_edit[0] if room_keys_edit else None

                                # 7. 房間選單
                                edit_room_id = st.selectbox("房間號碼", options=room_keys_edit, format_func=lambda x: room_options_edit.get(x), key=room_select_key)

                                # 日期與備註
                                ehc1, ehc2, ehc3 = st.columns(3)
                                edit_start_date = ehc1.date_input("起始日", value=history_details.get('start_date'))
                                with ehc2:
                                    edit_end_date = st.date_input("結束日 (留空表示仍在住)", value=history_details.get('end_date'))
                                    clear_end_date_history = st.checkbox("清除結束日 (設為仍在住)", key=f"clear_end_hist_{selected_history_id}")
                                
                                edit_bed_number = ehc3.text_input("床位編號", value=history_details.get('bed_number') or "")
                                edit_notes = st.text_area("備註", value=history_details.get('notes', ''))

                                # 照片處理區塊
                                st.markdown("---")
                                col_p1, col_p2 = st.columns(2)
                                
                                # 入住照片
                                with col_p1:
                                    st.markdown("###### 📥 入住時照片")
                                    in_photos = history_details.get('checkin_photo_paths') or []
                                    if in_photos:
                                        st.image(in_photos, width=100)
                                        del_in = st.multiselect("刪除入住照片", in_photos, format_func=lambda x: os.path.basename(x), key=f"del_in_{selected_history_id}")
                                    else: del_in = []
                                    new_in = st.file_uploader("上傳入住照片", type=['jpg','png'], key=f"up_in_{selected_history_id}", accept_multiple_files=True)

                                # 退宿照片
                                with col_p2:
                                    st.markdown("###### 📤 退宿時照片")
                                    out_photos = history_details.get('checkout_photo_paths') or []
                                    if out_photos:
                                        st.image(out_photos, width=100)
                                        del_out = st.multiselect("刪除退宿照片", out_photos, format_func=lambda x: os.path.basename(x), key=f"del_out_{selected_history_id}")
                                    else: del_out = []
                                    new_out = st.file_uploader("上傳退宿照片", type=['jpg','png'], key=f"up_out_{selected_history_id}", accept_multiple_files=True)

                                if st.form_submit_button("儲存歷史紀錄變更"):
                                    # 1. 處理刪除照片
                                    final_in = [p for p in in_photos if p not in del_in]
                                    for p in del_in: utils.delete_file(p)
                                    
                                    final_out = [p for p in out_photos if p not in del_out]
                                    for p in del_out: utils.delete_file(p)
                                    
                                    # 2. 處理新增照片
                                    emp_name = worker_details.get('employer_name', 'Unknown')
                                    w_name = worker_details.get('worker_name', 'Unknown')
                                    
                                    if new_in:
                                        prefix_in = f"{emp_name}_{w_name}_入住_{edit_start_date}"
                                        final_in.extend(utils.save_uploaded_files(new_in, "accommodation", prefix_in))
                                    
                                    if new_out:
                                        prefix_out = f"{emp_name}_{w_name}_退宿_{edit_end_date or date.today()}"
                                        final_out.extend(utils.save_uploaded_files(new_out, "accommodation", prefix_out))
                                        
                                    if not edit_room_id:
                                        st.error("必須選擇一個房間！")
                                    else:
                                        final_end_date = None if clear_end_date_history else (str(edit_end_date) if edit_end_date else None)
                                        update_data = {
                                            "room_id": edit_room_id,
                                            "start_date": str(edit_start_date) if edit_start_date else None,
                                            "end_date": final_end_date, 
                                            "bed_number": edit_bed_number,
                                            "notes": edit_notes,
                                            "checkin_photo_paths": final_in,
                                            "checkout_photo_paths": final_out
                                        }
                                        success, message = worker_model.update_accommodation_history(selected_history_id, update_data)
                                        if success: st.success(message); st.rerun()
                                        else: st.error(message)

                            st.markdown("##### 危險操作區")
                            confirm_delete_history = st.checkbox("我了解並確認要刪除此筆住宿歷史", key=f"delete_accom_{selected_history_id}")
                            if st.button("🗑️ 刪除此筆歷史", type="primary", disabled=not confirm_delete_history):
                                success, message = worker_model.delete_accommodation_history(selected_history_id)
                                if success: st.success(message); st.rerun()
                                else: st.error(message)

            # ==========================================
            # 分頁 3: 狀態歷史管理
            # ==========================================
            elif selected_tab == TAB_STATUS:
                st.markdown("##### ➕ 新增一筆狀態紀錄")
                with st.form("new_status_form", clear_on_submit=True):
                    s_c1, s_c2 = st.columns(2)
                    status_options = ["", "掛宿外住(不收費)", "掛宿外住(收費)", "費用不同", "其他"]
                    new_status = s_c1.selectbox("選擇新狀態 (若要結束特殊狀態回歸正常，請留空)", status_options)
                    start_date = s_c2.date_input("此狀態起始日", value=date.today())
                    status_notes = st.text_area("狀態備註")

                    if st.form_submit_button("執行變更"):
                        status_details = { 
                            "worker_unique_id": selected_worker_id, 
                            "status": new_status, 
                            "start_date": str(start_date), 
                            "notes": status_notes 
                        }
                        success, message = worker_model.add_new_worker_status(status_details)
                        if success: st.success(message); st.rerun()
                        else: st.error(message)

                st.markdown("---")
                st.markdown("##### 📜 狀態歷史紀錄")
                history_df = worker_model.get_worker_status_history(selected_worker_id)
                st.dataframe(history_df, use_container_width=True, hide_index=True, column_config={"id": None})
                
                st.subheader("✏️ 編輯或刪除狀態")
                if history_df.empty: st.info("無狀態紀錄。")
                else:
                    status_options_dict = {row['id']: f"{row['起始日']} | {row['狀態']}" for _, row in history_df.iterrows()}
                    selected_status_id = st.selectbox("選擇狀態紀錄：", [None] + list(status_options_dict.keys()), format_func=lambda x: "請選擇..." if x is None else status_options_dict.get(x), key=f"status_selector_{selected_worker_id}")
                    if selected_status_id:
                        status_details = worker_model.get_single_status_details(selected_status_id)
                        if status_details:
                            with st.form(f"edit_status_form_{selected_status_id}"):
                                es_c1, es_c2, es_c3 = st.columns(3)
                                status_options_edit = ["掛宿外住(不收費)", "掛宿外住(收費)", "費用不同", "其他"]
                                curr = status_details.get('status')
                                idx = status_options_edit.index(curr) if curr in status_options_edit else 0
                                edit_status = es_c1.selectbox("狀態", status_options_edit, index=idx)
                                edit_start_date = es_c2.date_input("起始日", value=status_details.get('start_date'))
                                
                                with es_c3:
                                    edit_end_date = st.date_input("結束日 (留空代表當前)", value=status_details.get('end_date'))
                                    clear_end_date_status = st.checkbox("清除結束日", key=f"clear_end_status_{selected_status_id}")
                                
                                edit_notes = st.text_area("備註", value=status_details.get('notes', ''))
                                
                                if st.form_submit_button("儲存"):
                                    final_end = None if clear_end_date_status else (str(edit_end_date) if edit_end_date else None)
                                    updated_details = {"status": edit_status, "start_date": str(edit_start_date), "end_date": final_end, "notes": edit_notes}
                                    success, message = worker_model.update_worker_status(selected_status_id, updated_details)
                                    if success: st.success(message); st.rerun()
                                    else: st.error(message)
                            
                            confirm_del_stat = st.checkbox("確認刪除此狀態")
                            if st.button("🗑️ 刪除", type="primary", disabled=not confirm_del_stat):
                                success, message = worker_model.delete_worker_status(selected_status_id)
                                if success: st.success(message); st.rerun()

            # ==========================================
            # 分頁 4: 費用歷史
            # ==========================================
            elif selected_tab == TAB_FEE:
                st.markdown("##### ➕ 手動新增費用歷史")
                with st.expander("點此展開以新增"):
                    with st.form("new_fee_history_form", clear_on_submit=True):
                        fee_type_options = ['房租', '水電費', '清潔費', '宿舍復歸費', '充電清潔費']
                        fc1, fc2, fc3 = st.columns(3)
                        new_fee_type = fc1.selectbox("費用類型", fee_type_options)
                        new_amount = fc2.number_input("金額", min_value=0, step=100)
                        new_effective_date = fc3.date_input("生效日期", value=date.today())

                        if st.form_submit_button("新增紀錄"):
                            details = {"worker_unique_id": selected_worker_id, "fee_type": new_fee_type, "amount": new_amount, "effective_date": new_effective_date}
                            success, message = worker_model.add_fee_history(details)
                            if success: st.success(message); st.rerun()
                            else: st.error(message)

                st.markdown("---")
                st.markdown("##### 💰 費用變更歷史總覽")
                fee_history_df = worker_model.get_fee_history_for_worker(selected_worker_id)
                
                # 表格呈現
                st.dataframe(
                    fee_history_df, 
                    use_container_width=True, 
                    hide_index=True, 
                    column_config={
                        "id": None, 
                        "生效日期": st.column_config.DateColumn("生效日期"),
                        "金額": st.column_config.NumberColumn("金額", format="$%d")
                    }
                )

                st.markdown("---")
                st.subheader("✏️ 編輯或刪除單筆費用歷史")
                if fee_history_df.empty: st.info("無費用歷史。")
                else:
                    hist_opts = {row['id']: f"{row['生效日期']} | {row['費用類型']} | ${row['金額']}" for _, row in fee_history_df.iterrows()}
                    sel_fee_id = st.selectbox("選擇紀錄：", [None] + list(hist_opts.keys()), format_func=lambda x: "請選擇..." if x is None else hist_opts.get(x), key=f"fee_sel_{selected_worker_id}")
                    
                    if sel_fee_id:
                        f_det = worker_model.get_single_fee_history_details(sel_fee_id)
                        if f_det:
                            with st.form(f"edit_fee_{sel_fee_id}"):
                                fee_types = ['房租', '水電費', '清潔費', '宿舍復歸費', '充電清潔費']
                                try: f_idx = fee_types.index(f_det.get('fee_type'))
                                except: f_idx = 0
                                
                                efc1, efc2, efc3 = st.columns(3)
                                edit_type = efc1.selectbox("類型", fee_types, index=f_idx)
                                edit_amt = efc2.number_input("金額", min_value=0, step=100, value=int(f_det.get('amount', 0)))
                                edit_date = efc3.date_input("生效日", value=f_det.get('effective_date'))
                                
                                if st.form_submit_button("儲存"):
                                    upd = {"fee_type": edit_type, "amount": edit_amt, "effective_date": edit_date}
                                    success, message = worker_model.update_fee_history(sel_fee_id, upd)
                                    if success: st.success(message); st.rerun()
                                    else: st.error(message)
                            
                            confirm_del_fee = st.checkbox("確認刪除此費用紀錄")
                            if st.button("🗑️ 刪除", type="primary", disabled=not confirm_del_fee):
                                success, message = worker_model.delete_fee_history(sel_fee_id)
                                if success: st.success(message); st.rerun()

def render_add_manual_worker():
    """
    新增手動管理人員的表單
    """
    st.subheader("➕ 新增手動管理人員 (他仲/特殊案例)")
    st.info("在此新增的人員將被標記為『手動管理(他仲)』，系統不會自動同步其資料。")
    
    with st.form("add_manual_worker_form"):
        col1, col2 = st.columns(2)
        name = col1.text_input("姓名 (必填)")
        employer = col2.text_input("雇主名稱")
        
        col3, col4 = st.columns(2)
        nationality = col3.selectbox("國籍", ["越南", "印尼", "泰國", "菲律賓", "其他"])
        gender = col4.selectbox("性別", ["男", "女"])
        
        notes = st.text_area("備註")
        
        if st.form_submit_button("建立人員"):
            if not name:
                st.error("姓名為必填欄位")
            else:
                worker_data = {
                    "worker_name": name,
                    "employer_name": employer,
                    "nationality": nationality,
                    "gender": gender,
                    "worker_notes": notes,
                    "data_source": "手動管理(他仲)"
                }
                success, message = worker_model.create_manual_worker(worker_data)
                if success:
                    st.success(message)
                else:
                    st.error(message)