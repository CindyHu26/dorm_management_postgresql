# views/dormitory_view.py

import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import dormitory_model, vendor_model # 匯入 vendor_model
from data_processor import normalize_taiwan_address

# --- 修改 1：匯入 cache_data ---
@st.cache_data
def get_dorms_df(search=None):
    return dormitory_model.get_all_dorms_for_view(search_term=search)

# --- 修改 2：建立一個函式來快取負責人選項 ---
@st.cache_data
def get_person_options():
    # 呼叫我們在
    return dormitory_model.get_distinct_person_in_charge()

def render():
    """渲染「地址管理」頁面的所有 Streamlit UI 元件。"""
    st.header("宿舍地址管理")

    # --- Session State 初始化 (維持不變) ---
    if 'selected_dorm_id' not in st.session_state:
        st.session_state.selected_dorm_id = None
    if 'selected_room_id' not in st.session_state:
        st.session_state.selected_room_id = None
    if 'room_action_completed' not in st.session_state:
        st.session_state.room_action_completed = False
    if 'dorm_active_tab' not in st.session_state:
        st.session_state.dorm_active_tab = "基本資料與編輯"
    if st.session_state.room_action_completed:
        st.session_state.selected_room_id = None
        st.session_state.room_action_completed = False
    if 'last_selected_dorm' not in st.session_state:
        st.session_state.last_selected_dorm = None
    if st.session_state.selected_dorm_id != st.session_state.last_selected_dorm:
        st.session_state.selected_room_id = None
        st.session_state.dorm_active_tab = "基本資料與編輯"
        st.session_state.last_selected_dorm = st.session_state.selected_dorm_id

    # --- 預載廠商資料 ---
    vendors = vendor_model.get_vendors_for_view()
    # 我們特別為房東建立一個篩選過的選項
    landlord_options = {v['id']: v['廠商名稱'] for _, v in vendors[vendors['服務項目'] == '房東'].iterrows()} if not vendors.empty else {}

    # --- 修改 3：在 render 函式開頭載入選項 ---
    person_options = get_person_options()
    # 建立一個包含「空白」選項的完整列表
    all_person_options = [""] + person_options

    # --- 新增宿舍區塊 ---
    with st.expander("➕ 新增宿舍地址", expanded=False):
        with st.form("new_dorm_form", clear_on_submit=True):
            st.subheader("宿舍基本資料")
            c1, c2, c3 = st.columns(3)
            legacy_code = c1.text_input("宿舍編號 (選填)")
            original_address = c1.text_input("原始地址 (必填)")
            dorm_name = c2.text_input("宿舍自訂名稱 (例如: 中山A棟)")
            person_in_charge = c3.selectbox("負責人", options=all_person_options, index=0)
            
            # --- 【核心修改 1】新增房東下拉選單 ---
            landlord_id = c2.selectbox("房東 (請先至廠商資料建立)", options=[None] + list(landlord_options.keys()), format_func=lambda x: "未指定" if x is None else landlord_options.get(x))

            invoice_info = c1.text_input("發票抬頭/統編")
            is_self_owned = st.checkbox("✅ 此為公司自購宿舍", key="new_self_owned")

            st.subheader("責任歸屬與備註")
            rc1, rc2, rc3 = st.columns(3)
            primary_manager = rc1.selectbox("主要管理人", ["我司", "雇主"], key="new_pm")
            rent_payer = rc2.selectbox("租金支付方", ["我司", "雇主", "工人"], key="new_rp")
            utilities_payer = rc3.selectbox("水電支付方", ["我司", "雇主", "工人"], key="new_up")
            
            dorm_notes = st.text_area("宿舍備註 (通用)")
            management_notes = st.text_area("管理模式備註 (可記錄特殊約定)")
            utility_bill_notes = st.text_area("變動費用備註 (將顯示在錶號費用管理頁面)")

            norm_addr_preview = normalize_taiwan_address(original_address)['full'] if original_address else ""
            if norm_addr_preview: st.info(f"正規化地址預覽: {norm_addr_preview}")
            submitted = st.form_submit_button("儲存新宿舍")
            if submitted:
                if not original_address:
                    st.error("「原始地址」為必填欄位！")
                else:
                    dorm_details = {
                        'legacy_dorm_code': legacy_code, 'original_address': original_address,
                        'dorm_name': dorm_name, 'person_in_charge': person_in_charge,
                        'landlord_id': landlord_id, # 【核心修改 2】將新欄位加入儲存的資料中
                        'invoice_info': invoice_info,
                        'primary_manager': primary_manager,
                        'rent_payer': rent_payer, 'utilities_payer': utilities_payer,
                        'dorm_notes': dorm_notes, 
                        'management_notes': management_notes,
                        'utility_bill_notes': utility_bill_notes,
                        'is_self_owned': is_self_owned
                    }
                    success, message = dormitory_model.add_new_dormitory(dorm_details)
                    if success:
                        st.success(message)
                        get_dorms_df.clear()
                        get_person_options.clear() # --- 修改 6：清除快取 ---
                        st.rerun()
                    else:
                        st.error(message)

    st.markdown("---")

    # --- 現有宿舍總覽與編輯 ---
    st.subheader("現有宿舍總覽")
    
    search_term = st.text_input("搜尋宿舍 (可輸入編號、房東、地址、負責人或發票資訊)")
    dorms_df = get_dorms_df(search_term)
    
    if dorms_df.empty:
        st.warning("目前資料庫中沒有宿舍資料，或是沒有符合搜尋條件的結果。")

    selection = st.dataframe(dorms_df, width='stretch', hide_index=True, on_select="rerun", selection_mode="single-row")

    if selection.selection['rows']:
        st.session_state.selected_dorm_id = int(dorms_df.iloc[selection.selection['rows'][0]]['id'])
    
    st.markdown("---")
    
    if st.session_state.selected_dorm_id:
        dorm_id = st.session_state.selected_dorm_id
        dorm_details = dormitory_model.get_dorm_details_by_id(dorm_id)
        
        if not dorm_details:
            st.error("找不到選定的宿舍資料，可能已被刪除。請重新整理。")
            st.session_state.selected_dorm_id = None
        else:
            st.subheader(f"詳細資料: {dorm_details.get('original_address', '')}")
            
            tab_options = ["基本資料與編輯", "房間管理"]
            active_tab = st.radio("管理選項:", options=tab_options, key='dorm_active_tab', horizontal=True, label_visibility="collapsed")

            if active_tab == "基本資料與編輯":
                with st.container():
                    with st.form("edit_dorm_form"):
                        st.markdown("##### 基本資料")
                        edit_c1, edit_c2 = st.columns(2)
                        legacy_code = edit_c1.text_input("宿舍編號", value=dorm_details.get('legacy_dorm_code', ''))
                        original_address = edit_c1.text_input("原始地址", value=dorm_details.get('original_address', ''))
                        dorm_name = edit_c2.text_input("宿舍自訂名稱", value=dorm_details.get('dorm_name', ''))
                        
                        # --- 【核心修改 3】在編輯表單中新增房東下拉選單 ---
                        edit_c3, edit_c4 = st.columns(2)
                        current_person = dorm_details.get('person_in_charge', '')
                        
                        # 準備一個包含目前值（即使它不在標準列表內）的選項列表
                        edit_person_options = all_person_options[:] # 複製列表
                        if current_person and current_person not in edit_person_options:
                            edit_person_options.append(current_person)
                            
                        try:
                            person_index = edit_person_options.index(current_person)
                        except ValueError:
                            person_index = 0 # 預設選空白
                            
                        person_in_charge = edit_c3.selectbox(
                            "負責人", 
                            options=edit_person_options, 
                            index=person_index
                        )

                        current_landlord_id = dorm_details.get('landlord_id')
                        landlord_keys = [None] + list(landlord_options.keys())
                        landlord_index = landlord_keys.index(current_landlord_id) if current_landlord_id in landlord_keys else 0
                        landlord_id_edit = edit_c4.selectbox("房東", options=landlord_keys, format_func=lambda x: "未指定" if x is None else landlord_options.get(x), index=landlord_index)

                        edit_c5, edit_c6 = st.columns(2)
                        city = edit_c5.text_input("縣市", value=dorm_details.get('city', ''))
                        district = edit_c6.text_input("區域", value=dorm_details.get('district', ''))
                        
                        invoice_info_edit = st.text_input("發票抬頭/統編", value=dorm_details.get('invoice_info', ''))
                        edit_is_self_owned = st.checkbox("✅ 此為公司自購宿舍", value=dorm_details.get('is_self_owned', False), key="edit_self_owned")

                        st.markdown("##### 責任歸屬與備註")
                        edit_rc1, edit_rc2, edit_rc3 = st.columns(3)
                        manager_options = ["我司", "雇主", "工人"]
                        primary_manager = edit_rc1.selectbox("主要管理人", manager_options, index=manager_options.index(dorm_details.get('primary_manager')) if dorm_details.get('primary_manager') in manager_options else 0)
                        rent_payer = edit_rc2.selectbox("租金支付方", manager_options, index=manager_options.index(dorm_details.get('rent_payer')) if dorm_details.get('rent_payer') in manager_options else 0)
                        utilities_payer = edit_rc3.selectbox("水電支付方", manager_options, index=manager_options.index(dorm_details.get('utilities_payer')) if dorm_details.get('utilities_payer') in manager_options else 0)
                        
                        dorm_notes_edit = st.text_area("宿舍備註 (通用)", value=dorm_details.get('dorm_notes', ''))
                        management_notes = st.text_area("管理模式備註", value=dorm_details.get('management_notes', ''))
                        utility_bill_notes_edit = st.text_area("變動費用備註", value=dorm_details.get('utility_bill_notes', ''))

                        edit_submitted = st.form_submit_button("儲存變更")
                        if edit_submitted:
                            updated_details = {
                                'legacy_dorm_code': legacy_code, 'original_address': original_address,
                                'dorm_name': dorm_name, 'city': city, 'district': district, 'person_in_charge': person_in_charge,
                                'landlord_id': landlord_id_edit, # 【核心修改 4】將新欄位加入更新的資料中
                                'invoice_info': invoice_info_edit,
                                'primary_manager': primary_manager, 'rent_payer': rent_payer, 'utilities_payer': utilities_payer,
                                'dorm_notes': dorm_notes_edit, 
                                'management_notes': management_notes,
                                'utility_bill_notes': utility_bill_notes_edit,
                                'is_self_owned': edit_is_self_owned
                            }
                            success, message = dormitory_model.update_dormitory_details(dorm_id, updated_details)
                            if success:
                                st.success(message)
                                get_dorms_df.clear()
                                get_person_options.clear() # --- 修改 9：清除快取 ---
                                st.rerun()
                            else:
                                st.error(message)

                    st.markdown("---")
                    st.markdown("##### 危險操作區")
                    confirm_delete = st.checkbox("我了解並確認要刪除此宿舍")
                    if st.button("🗑️ 刪除此宿舍", type="primary", disabled=not confirm_delete):
                        success, message = dormitory_model.delete_dormitory_by_id(dorm_id)
                        if success:
                            st.success(message); st.session_state.selected_dorm_id = None; get_dorms_df.clear(); st.rerun()
                        else:
                            st.error(message)

            elif active_tab == "房間管理":
                with st.container():
                    st.markdown("##### 房間列表")
                    rooms_df = dormitory_model.get_rooms_for_dorm_as_df(dorm_id)
                    st.dataframe(rooms_df, width='stretch', hide_index=True)
                    st.markdown("---")
                    st.subheader("新增、編輯或刪除房間")
                    room_options = {row['id']: f"{row['房號']} (容量: {row.get('容量', 'N/A')})" for _, row in rooms_df.iterrows()}
                    st.selectbox( "選擇要編輯或刪除的房間：", options=[None] + list(room_options.keys()), format_func=lambda x: "請選擇..." if x is None else room_options.get(x), key='selected_room_id' )
                    if st.session_state.selected_room_id:
                        room_details = dormitory_model.get_single_room_details(st.session_state.selected_room_id)
                        if room_details:
                            with st.form(f"edit_room_form_{st.session_state.selected_room_id}"):
                                # --- 【核心修改 1】加入房號輸入框 ---
                                e_room_number = st.text_input("房號", value=room_details.get('room_number', ''))
                                # --- 修改結束 ---

                                st.markdown(f"###### 正在編輯房號: {room_details.get('room_number')}") # 可以保留或移除此行
                                ec1, ec2, ec3 = st.columns(3)
                                e_capacity = ec1.number_input("房間容量", min_value=0, step=1, value=int(room_details.get('capacity') or 0))
                                gender_options = ["可混住", "僅限男性", "僅限女性"]
                                e_gender_policy = ec2.selectbox("性別限制", gender_options, index=gender_options.index(room_details.get('gender_policy')) if room_details.get('gender_policy') in gender_options else 0)
                                nationality_options = ["不限", "單一國籍"]
                                e_nationality_policy = ec3.selectbox("國籍限制", nationality_options, index=nationality_options.index(room_details.get('nationality_policy')) if room_details.get('nationality_policy') in nationality_options else 0)
                                e_room_notes = st.text_area("房間備註", value=room_details.get('room_notes', ''))
                                edit_submitted = st.form_submit_button("儲存房間變更")
                                if edit_submitted:
                                    if not e_room_number.strip(): # 檢查新房號是否為空
                                        st.error("房號不可為空！")
                                    else:
                                        # --- 【核心修改 2】將新房號加入 updated_details ---
                                        updated_details = {
                                            "room_number": e_room_number.strip(), # 加入新房號
                                            "capacity": e_capacity,
                                            "gender_policy": e_gender_policy,
                                            "nationality_policy": e_nationality_policy,
                                            "room_notes": e_room_notes
                                        }
                                        # --- 修改結束 ---
                                        success, message = dormitory_model.update_room_details(st.session_state.selected_room_id, updated_details)
                                        if success:
                                            st.success(message); st.session_state.room_action_completed = True; st.rerun()
                                        else:
                                            st.error(message)
                            confirm_delete_room = st.checkbox("我了解並確認要刪除此房間", key=f"delete_room_{st.session_state.selected_room_id}")
                            if st.button("🗑️ 刪除此房間", type="primary", disabled=not confirm_delete_room):
                                success, message = dormitory_model.delete_room_by_id(st.session_state.selected_room_id)
                                if success:
                                    st.success(message); st.session_state.room_action_completed = True; st.rerun()
                                else:
                                    st.error(message)
                    with st.form("new_room_form", clear_on_submit=True):
                        st.markdown("###### 或新增一個房間至此宿舍")
                        nc1, nc2, nc3 = st.columns(3)
                        room_number = nc1.text_input("新房號 (例如: A01)")
                        capacity = nc2.number_input("房間容量", min_value=1, step=1, value=4)
                        gender_policy = nc3.selectbox("性別限制 ", ["可混住", "僅限男性", "僅限女性"])
                        nc_c1, nc_c2 = st.columns(2)
                        nationality_policy = nc_c1.selectbox("國籍限制 ", ["不限", "單一國籍"])
                        room_notes = nc_c2.text_area("房間備註 ")
                        room_submitted = st.form_submit_button("新增房間")
                        if room_submitted:
                            if not room_number:
                                st.error("房號為必填欄位！")
                            else:
                                room_details = { 'dorm_id': dorm_id, 'room_number': room_number, 'capacity': capacity, 'gender_policy': gender_policy, 'nationality_policy': nationality_policy, 'room_notes': room_notes }
                                success, msg, _ = dormitory_model.add_new_room_to_dorm(room_details)
                                if success:
                                    st.success(msg); st.rerun()
                                else:
                                    st.error(msg)