import streamlit as st
import pandas as pd
from datetime import datetime, date
from data_models import worker_model, dormitory_model
import utils # 記得匯入 utils
import os

# --- 輔助函式：確保 Session State 只被初始化一次 ---
def init_state_once(key, value):
    if key not in st.session_state:
        st.session_state[key] = value

def render():
    """渲染「人員管理」頁面"""
    st.header("移工住宿人員管理")
    
    # --- 1. 定義分頁名稱 (使用變數，避免字串打錯) ---
    TAB_CORE = "✏️ 編輯/檢視核心資料"
    TAB_ACCOM = "🏠 住宿歷史管理"
    TAB_STATUS = "🕒 狀態歷史管理"
    TAB_FEE = "💰 費用歷史"
    
    TAB_NAMES = [TAB_CORE, TAB_ACCOM, TAB_STATUS, TAB_FEE]

    # --- 2. Session State 初始化 ---
    if 'worker_active_tab' not in st.session_state:
        st.session_state.worker_active_tab = TAB_NAMES[0] # 預設選第一個
    
    # 初始化上傳元件的重置金鑰 (解決上傳後卡住的問題)
    if 'worker_upload_reset_key' not in st.session_state:
        st.session_state.worker_upload_reset_key = 0

    # 初始化篩選器 State
    init_state_once('w_filter_search', '')
    init_state_once('w_filter_status', '全部')
    init_state_once('w_filter_gender', '全部')
    init_state_once('w_filter_dorm', None)
    init_state_once('w_filter_room', None)
    init_state_once('w_filter_nationality', '全部')

    def on_dorm_change():
        st.session_state.w_filter_room = None

    # --- 新增手動管理人員區塊--
    with st.expander("➕ 新增手動管理人員 (他仲等)"):
        
        # 將宿舍與房間選擇移出 st.form，以支援動態連動
        st.markdown("##### 1. 選擇住宿位置")
        dorms = dormitory_model.get_dorms_for_selection() or []
        dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms}
        
        loc_c1, loc_c2 = st.columns(2)
        # 宿舍選單 (會觸發 Rerun)
        selected_dorm_id_new = loc_c1.selectbox(
            "宿舍地址", 
            [None] + list(dorm_options.keys()), 
            format_func=lambda x: "未分配" if x is None else dorm_options.get(x), 
            key="new_manual_worker_dorm_select"
        )
        
        # 根據宿舍動態載入房間
        rooms = dormitory_model.get_rooms_for_selection(selected_dorm_id_new) or []
        room_options = {r['id']: r['room_number'] for r in rooms}
        
        # 房間選單 (會觸發 Rerun)
        selected_room_id_new = loc_c2.selectbox(
            "房間號碼", 
            [None] + list(room_options.keys()), 
            format_func=lambda x: "未分配" if x is None else room_options.get(x), 
            key="new_manual_worker_room_select"
        )

        # --- 表單開始 ---
        with st.form("new_manual_worker_form", clear_on_submit=True):
            st.markdown("##### 2. 填寫人員資料")
            c1, c2, c3 = st.columns(3)
            employer_name = c1.text_input("雇主名稱 (必填)")
            worker_name = c2.text_input("移工姓名 (必填)")
            passport_number = c3.text_input("護照號碼 (同名時必填)")
            gender = c1.selectbox("性別", ["", "男", "女"])
            nationality_options = ["", "越南", "印尼", "泰國", "菲律賓", "其他 (請手動輸入)"]
            selected_nationality = c2.selectbox("國籍", options=nationality_options)
            custom_nationality = c2.text_input("手動輸入國籍", help="若上方選擇「其他」，請在此填寫")
            arc_number = c3.text_input("居留證號")
            
            st.markdown("##### 3. 費用與狀態")
            # 這裡不再放置宿舍選單，改放床位編號
            bed_number_new = st.text_input("床位編號")

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
                    
                    # 使用外部選擇的 selected_dorm_id_new 和 selected_room_id_new
                    details = {
                        'unique_id': unique_id, 'employer_name': emp_clean, 'worker_name': name_clean,
                        'passport_number': pass_clean if pass_clean else None,
                        'gender': gender, 'nationality': final_nationality, 'arc_number': arc_number,
                        'dorm_id': selected_dorm_id_new,  # 取用外部變數
                        'room_id': selected_room_id_new,  # 取用外部變數
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

    @st.cache_data
    def get_dorms_list():
        return dormitory_model.get_dorms_for_selection()
    
    @st.cache_data
    def get_nationality_list():
        return ["全部"] + worker_model.get_distinct_nationalities()

    dorms = get_dorms_list() or []
    # 建立 ID 到 顯示名稱 的對應
    dorm_options_map = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms}
    nationality_options = get_nationality_list()
    gender_options = ["全部", "男", "女"]
    
    # --- 篩選器排版 ---
    f_row1_c1, f_row1_c2, f_row1_c3 = st.columns(3)
    f_row2_c1, f_row2_c2, f_row2_c3 = st.columns(3)

    # Row 1
    f_row1_c1.text_input(
        "搜尋姓名、雇主、地址、護照或居留證", 
        key="w_filter_search"
    )
    f_row1_c2.selectbox(
        "篩選在住狀態", 
        ["全部", "在住", "已離住"], 
        key="w_filter_status"
    )
    f_row1_c3.selectbox(
        "篩選性別", 
        gender_options, 
        key="w_filter_gender"
    )
    
    # Row 2
    # 宿舍篩選 (Dorm) - 綁定 on_change
    f_row2_c1.selectbox(
        "篩選宿舍", 
        options=[None] + list(dorm_options_map.keys()), 
        format_func=lambda x: "全部宿舍" if x is None else dorm_options_map.get(x),
        key="w_filter_dorm",
        on_change=on_dorm_change # 當宿舍改變時，重設房號
    )

    # 房號篩選 (Room) - 依賴宿舍篩選
    rooms_for_filter = dormitory_model.get_rooms_for_selection(st.session_state.w_filter_dorm) or []
    room_filter_options = {r['id']: r['room_number'] for r in rooms_for_filter}
    
    f_row2_c2.selectbox(
        "篩選房號", 
        options=[None] + list(room_filter_options.keys()), 
        format_func=lambda x: "全部房號" if x is None else room_filter_options.get(x, "N/A"), 
        key="w_filter_room",
        disabled=not st.session_state.w_filter_dorm # 沒選宿舍就禁用
    )
    
    # 國籍篩選 (Nationality)
    f_row2_c3.selectbox(
        "篩選國籍", 
        nationality_options, 
        key="w_filter_nationality"
    )

    # 準備傳給 Model 的參數
    filters = {
        'name_search': st.session_state.w_filter_search,
        'dorm_id': st.session_state.w_filter_dorm,
        'status': st.session_state.w_filter_status,
        'room_id': st.session_state.w_filter_room,
        'nationality': st.session_state.w_filter_nationality,
        'gender': st.session_state.w_filter_gender
    }

    workers_df = worker_model.get_workers_for_view(filters)
    
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
                
                # --- 使用變數列表，避免字串打錯 ---
                selected_tab = st.radio("管理選項:", TAB_NAMES, key="worker_active_tab", horizontal=True, label_visibility="collapsed")

                # ==========================================
                # 分頁 1: 編輯/檢視核心資料
                # ==========================================
                if selected_tab == TAB_CORE: # 使用變數比較
                    with st.form("edit_worker_form"):
                        st.info(f"資料來源: **{worker_details.get('data_source')}**")
                        
                        # 照片檢視 (唯讀)
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
                        
                        # 基本資料
                        st.markdown("##### 基本資料 (可編輯)")
                        
                        # 準備國籍選項
                        nationality_options = ["", "越南", "印尼", "泰國", "菲律賓", "其他"]
                        current_nat = worker_details.get('nationality', '')
                        # 如果目前的國籍不在預設選項中，且不為空，則加入選項
                        if current_nat and current_nat not in nationality_options:
                            nationality_options.append(current_nat)
                        
                        ec1, ec2, ec3, ec4 = st.columns(4) # 改為 4 欄以容納居留證
                        
                        # 1. 性別
                        gender_opts = ["", "男", "女"]
                        curr_gender = worker_details.get('gender', '')
                        e_gender = ec1.selectbox("性別", gender_opts, index=gender_opts.index(curr_gender) if curr_gender in gender_opts else 0)
                        
                        # 2. 國籍
                        try:
                            nat_index = nationality_options.index(current_nat)
                        except ValueError:
                            nat_index = 0
                        e_nationality = ec2.selectbox("國籍", options=nationality_options, index=nat_index)
                        
                        # 3. 護照
                        e_passport = ec3.text_input("護照號碼", value=worker_details.get('passport_number', ''))
                        
                        # 4. 居留證 (新增)
                        e_arc = ec4.text_input("居留證號碼", value=worker_details.get('arc_number', ''))
                        
                        st.markdown("##### 住宿資訊")
                        sys_addr = worker_details.get('system_dorm_address'); sys_room = worker_details.get('system_room_number')
                        if sys_addr: st.info(f"🔗 **公司系統位址 (僅供參考)**：{sys_addr} / {sys_room}")
                        else: st.caption("此員工尚無公司系統位址紀錄。")
                        real_addr = worker_details.get('current_dorm_address') or '未分配'; real_room = worker_details.get('current_room_number') or ''
                        st.text_input("目前實際住宿 (請至「住宿歷史」分頁修改)", value=f"{real_addr} {real_room}", disabled=True)

                        # 費用明細 (唯讀)
                        st.markdown("##### 費用明細 (唯讀)")
                        
                        from datetime import timedelta
                        
                        today = date.today()
                        # 取得本月1號
                        this_month_first = today.replace(day=1)
                        # 減一天得到上個月最後一天 (例如 2025-12-01 -> 2025-11-30)
                        last_month_end = this_month_first - timedelta(days=1)
                        # 再取得上個月1號 (例如 2025-11-01)
                        last_month_start = last_month_end.replace(day=1)
                        
                        last_month_str = last_month_end.strftime('%Y-%m')
                        
                        st.info(f"此處顯示該員工於 **{last_month_str} 月份** 產生的費用帳款 (作為上月參考)。如需修改，請至「💰 費用歷史」頁籤。")
                        
                        fee_hist_df = worker_model.get_fee_history_for_worker(selected_worker_id)
                        
                        if fee_hist_df.empty:
                            st.caption("目前無任何費用紀錄。")
                        else:
                            fee_hist_df['eff_date'] = pd.to_datetime(fee_hist_df['生效日期']).dt.date
                            
                            # 【關鍵修正】：只篩選生效日在 [上月1號 ~ 上月月底] 之間的資料
                            valid_fees = fee_hist_df[
                                (fee_hist_df['eff_date'] >= last_month_start) & 
                                (fee_hist_df['eff_date'] <= last_month_end)
                            ]
                            
                            if valid_fees.empty:
                                st.caption(f"在 {last_month_str} 月份無任何費用紀錄。")
                            else:
                                # 針對同一費用類型，若當月有多筆(例如補扣)，將其金額加總顯示
                                grouped_fees = valid_fees.groupby('費用類型')['金額'].sum().reset_index()
                                
                                current_total = grouped_fees['金額'].sum()
                                
                                # 顯示標題
                                st.metric(f"上月應收總額參考 ({last_month_str})", f"NT$ {current_total:,}")
                                
                                fee_items = grouped_fees.to_dict('records')
                                # 排序：房租優先，其他依字首
                                fee_items.sort(key=lambda x: 0 if x['費用類型'] == '房租' else 1)
                                
                                cols = st.columns(3)
                                for i, item in enumerate(fee_items):
                                    with cols[i % 3]:
                                        # 注意：這裡 key 使用 index，因為 groupby 後沒有 id 了
                                        st.number_input(f"{item['費用類型']}", value=int(item['金額']), disabled=True, key=f"ro_fee_view_{i}")
                        
                        st.markdown("##### 狀態 (可手動修改)")
                        fcc1, fcc2 = st.columns(2)
                        pm_opts = ["", "員工自付", "雇主支付"]
                        payment_method = fcc1.selectbox("付款方", pm_opts, index=pm_opts.index(worker_details.get('payment_method')) if worker_details.get('payment_method') in pm_opts else 0)
                        with fcc2:
                            end_date_value = worker_details.get('accommodation_end_date')
                            accommodation_end_date = st.date_input("最終離住日期", value=end_date_value)
                            clear_end_date = st.checkbox("清除離住日期 (將狀態改回在住)")
                        worker_notes = st.text_area("個人備註", value=worker_details.get('worker_notes') or "")

                        if st.form_submit_button("儲存核心資料變更"):
                            final_end_date = None if clear_end_date else (str(accommodation_end_date) if accommodation_end_date else None)
                            update_data = {
                                # 【本次新增】將付款方與備註也加入空值轉換邏輯
                                'payment_method': payment_method if payment_method else None, 
                                'worker_notes': worker_notes if worker_notes else None,
                                
                                # 日期欄位保持原樣 (因為 final_end_date 本身就已經處理好 None 了)
                                'accommodation_end_date': final_end_date, 
                                
                                # 之前的修改
                                'gender': e_gender if e_gender else None,
                                'nationality': e_nationality if e_nationality else None,
                                'passport_number': e_passport if e_passport else None,
                                'arc_number': e_arc if e_arc else None
                            }
                            success, message = worker_model.update_worker_details(selected_worker_id, update_data)
                            if success: st.success(message); st.cache_data.clear(); st.rerun()
                            else: st.error(message)
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

                                    # --- 使用 Session State 初始化模式，避免與 index 衝突 ---
                                    current_room_id = history_details.get('room_id')
                                    current_dorm_id = dormitory_model.get_dorm_id_from_room_id(current_room_id)

                                    # 1. 準備宿舍選項
                                    all_dorms_edit = dormitory_model.get_dorms_for_selection() or []
                                    all_dorm_options_edit = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in all_dorms_edit}
                                    dorm_keys_edit = list(all_dorm_options_edit.keys())
                                    
                                    # 定義 Key
                                    dorm_select_key = f"edit_hist_dorm_{selected_history_id}"
                                    
                                    # 2. 初始化宿舍 Session State (如果沒有值，才設為資料庫中的原始值)
                                    if dorm_select_key not in st.session_state:
                                        if current_dorm_id in dorm_keys_edit:
                                            st.session_state[dorm_select_key] = current_dorm_id
                                        elif dorm_keys_edit:
                                            st.session_state[dorm_select_key] = dorm_keys_edit[0]
                                    
                                    # 3. 產生宿舍選單 (不使用 index 參數)
                                    edit_dorm_id = st.selectbox(
                                        "宿舍地址", 
                                        options=dorm_keys_edit, 
                                        format_func=lambda x: all_dorm_options_edit.get(x), 
                                        key=dorm_select_key
                                    )

                                    # 4. 準備房間選項 (根據目前選中的宿舍)
                                    rooms_edit = dormitory_model.get_rooms_for_selection(edit_dorm_id) or []
                                    room_options_edit = {r['id']: r['room_number'] for r in rooms_edit}
                                    room_keys_edit = list(room_options_edit.keys())
                                    
                                    # 定義 Key
                                    room_select_key = f"edit_hist_room_{selected_history_id}"

                                    # 5. 初始化或重設房間 Session State
                                    if room_select_key not in st.session_state:
                                        # 第一次載入，嘗試使用資料庫中的原始房間
                                        if current_room_id in room_keys_edit:
                                            st.session_state[room_select_key] = current_room_id
                                        else:
                                            st.session_state[room_select_key] = room_keys_edit[0] if room_keys_edit else None
                                    else:
                                        # 檢查：如果使用者切換了宿舍，原本選中的房間ID可能不屬於新宿舍
                                        # 此時必須強制重設為新宿舍的第一個房間
                                        current_selected_room = st.session_state[room_select_key]
                                        if current_selected_room not in room_keys_edit:
                                            st.session_state[room_select_key] = room_keys_edit[0] if room_keys_edit else None

                                    # 6. 產生房間選單 (不使用 index 參數)
                                    edit_room_id = st.selectbox(
                                        "房間號碼", 
                                        options=room_keys_edit, 
                                        format_func=lambda x: room_options_edit.get(x), 
                                        key=room_select_key
                                    )

                                    ehc1, ehc2, ehc3 = st.columns(3)
                                    edit_start_date = ehc1.date_input("起始日", value=history_details.get('start_date'))
                                    
                                    with ehc2:
                                        edit_end_date = st.date_input("結束日 (留空表示仍在住)", value=history_details.get('end_date'))
                                        clear_end_date_history = st.checkbox("清除結束日 (設為仍在住)", key=f"clear_end_hist_{selected_history_id}")
                                    
                                    edit_bed_number = ehc3.text_input("床位編號", value=history_details.get('bed_number') or "")
                                    edit_notes = st.text_area("備註", value=history_details.get('notes', ''))

                                    # === 入住/退宿照片 ===
                                    st.markdown("---")
                                    col_p1, col_p2 = st.columns(2)
                                    
                                    # 1. 入住照片
                                    with col_p1:
                                        st.markdown("###### 📥 入住時照片 (紀錄床位/房間原貌)")
                                        in_photos = history_details.get('checkin_photo_paths') or []
                                        if in_photos:
                                            st.image(in_photos, width=100)
                                            del_in = st.multiselect("刪除入住照片", in_photos, format_func=lambda x: os.path.basename(x), key=f"del_in_{selected_history_id}")
                                        else: del_in = []
                                        
                                        new_in = st.file_uploader("上傳入住照片", type=['jpg','png'], key=f"up_in_{selected_history_id}", accept_multiple_files=True)

                                    # 2. 退宿照片
                                    with col_p2:
                                        st.markdown("###### 📤 退宿時照片 (紀錄還原狀況)")
                                        out_photos = history_details.get('checkout_photo_paths') or []
                                        if out_photos:
                                            st.image(out_photos, width=100)
                                            del_out = st.multiselect("刪除退宿照片", out_photos, format_func=lambda x: os.path.basename(x), key=f"del_out_{selected_history_id}")
                                        else: del_out = []
                                        
                                        new_out = st.file_uploader("上傳退宿照片", type=['jpg','png'], key=f"up_out_{selected_history_id}", accept_multiple_files=True)

                                    if st.form_submit_button("儲存歷史紀錄變更"):
                                        # 處理入住照片
                                        final_in = [p for p in in_photos if p not in del_in]
                                        for p in del_in: utils.delete_file(p)
                                        if new_in:
                                            # 【修改】命名規則：雇主_姓名_入住_日期
                                            emp_name = worker_details.get('employer_name', 'Unknown')
                                            w_name = worker_details.get('worker_name', 'Unknown')
                                            prefix_in = f"{emp_name}_{w_name}_入住_{edit_start_date}"
                                            
                                            final_in.extend(utils.save_uploaded_files(new_in, "accommodation", prefix_in))

                                        # 處理退宿照片
                                        final_out = [p for p in out_photos if p not in del_out]
                                        for p in del_out: utils.delete_file(p)
                                        if new_out:
                                            # 【修改】命名規則：雇主_姓名_退宿_日期
                                            emp_name = worker_details.get('employer_name', 'Unknown')
                                            w_name = worker_details.get('worker_name', 'Unknown')
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
                        # 修改提示文字
                        new_status = s_c1.selectbox("選擇新狀態 (若要結束特殊狀態回歸正常，請留空)", status_options, key="new_status_selector")
                        start_date = s_c2.date_input("此狀態起始日 (或回歸正常日)", value=date.today())
                        status_notes = st.text_area("狀態備註 (選填)")
                        
                        if st.form_submit_button("執行變更"):
                            # 【核心修改】直接使用選單的值，不強制轉為 '在住'
                            # 如果 new_status 是空字串，後端就會知道是 "回歸正常"
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