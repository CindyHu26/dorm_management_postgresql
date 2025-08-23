import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import dormitory_model 
from data_processor import normalize_taiwan_address

def render():
    """渲染「地址管理」頁面的所有 Streamlit UI 元件。"""
    st.header("宿舍地址管理")

    if 'selected_dorm_id' not in st.session_state:
        st.session_state.selected_dorm_id = None

    # --- 1. 新增宿舍區塊 ---
    with st.expander("➕ 新增宿舍地址", expanded=False):
        with st.form("new_dorm_form", clear_on_submit=True):
            st.subheader("宿舍基本資料")
            c1, c2 = st.columns(2)
            legacy_code = c1.text_input("舊系統編號 (選填)")
            original_address = c1.text_input("原始地址 (必填)")
            dorm_name = c2.text_input("宿舍自訂名稱 (例如: 中山A棟)")
            
            st.subheader("責任歸屬")
            rc1, rc2, rc3 = st.columns(3)
            primary_manager = rc1.selectbox("主要管理人", ["我司", "雇主"], key="new_pm")
            rent_payer = rc2.selectbox("租金支付方", ["我司", "雇主", "工人"], key="new_rp")
            utilities_payer = rc3.selectbox("水電支付方", ["我司", "雇主", "工人"], key="new_up")
            management_notes = st.text_area("管理模式備註 (可記錄特殊約定)")
            
            norm_addr_preview = normalize_taiwan_address(original_address)['full'] if original_address else ""
            if norm_addr_preview: st.info(f"正規化地址預覽: {norm_addr_preview}")

            submitted = st.form_submit_button("儲存新宿舍")
            if submitted:
                if not original_address:
                    st.error("「原始地址」為必填欄位！")
                else:
                    dorm_details = {
                        'legacy_dorm_code': legacy_code, 'original_address': original_address,
                        'normalized_address': norm_addr_preview, 'dorm_name': dorm_name,
                        'primary_manager': primary_manager, # 將新欄位加入儲存
                        'rent_payer': rent_payer, 'utilities_payer': utilities_payer,
                        'management_notes': management_notes
                    }
                    success, message = dormitory_model.add_new_dormitory(dorm_details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                    else:
                        st.error(message)

    st.markdown("---")

    # --- 2. 宿舍總覽與篩選 ---
    st.subheader("現有宿舍總覽")
    
    search_term = st.text_input("搜尋宿舍 (可輸入舊編號、名稱、原始或正規化地址)")
    
    @st.cache_data
    def get_dorms_df(search=None):
        # 將搜尋條件傳遞給後端
        return dormitory_model.get_all_dorms_for_view(search_term=search)

    # 執行搜尋
    dorms_df = get_dorms_df(search_term)
    
    selection = st.dataframe(dorms_df, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")

    if selection.selection['rows']:
        st.session_state.selected_dorm_id = int(dorms_df.iloc[selection.selection['rows'][0]]['id'])
    
    st.markdown("---")
    
    # --- 3. 單一宿舍詳情與管理 ---
    if st.session_state.selected_dorm_id:
        dorm_id = st.session_state.selected_dorm_id
        dorm_details = dormitory_model.get_dorm_details_by_id(dorm_id)
        
        if not dorm_details:
            st.error("找不到選定的宿舍資料，可能已被刪除。請重新整理。")
            st.session_state.selected_dorm_id = None
        else:
            st.subheader(f"詳細資料: {dorm_details.get('original_address', '')}")
            
            tab1, tab2 = st.tabs(["基本資料與編輯", "房間管理"])

            with tab1:
                with st.form("edit_dorm_form"):
                    st.markdown("##### 基本資料")
                    edit_c1, edit_c2 = st.columns(2)
                    legacy_code = edit_c1.text_input("舊系統編號", value=dorm_details.get('legacy_dorm_code', ''))
                    original_address = edit_c1.text_input("原始地址", value=dorm_details.get('original_address', ''))
                    dorm_name = edit_c2.text_input("宿舍自訂名稱", value=dorm_details.get('dorm_name', ''))
                    
                    st.markdown("##### 責任歸屬")
                    edit_rc1, edit_rc2, edit_rc3 = st.columns(3)
                    manager_options = ["我司", "雇主", "工人"]
                    primary_manager = edit_rc1.selectbox("主要管理人", manager_options, index=manager_options.index(dorm_details.get('primary_manager')) if dorm_details.get('primary_manager') in manager_options else 0)
                    rent_payer = edit_rc2.selectbox("租金支付方", manager_options, index=manager_options.index(dorm_details.get('rent_payer')) if dorm_details.get('rent_payer') in manager_options else 0)
                    utilities_payer = edit_rc3.selectbox("水電支付方", manager_options, index=manager_options.index(dorm_details.get('utilities_payer')) if dorm_details.get('utilities_payer') in manager_options else 0)
                    
                    management_notes = st.text_area("管理模式備註", value=dorm_details.get('management_notes', ''))
                    
                    edit_submitted = st.form_submit_button("儲存變更")
                    if edit_submitted:
                        updated_details = {
                            'legacy_dorm_code': legacy_code, 'original_address': original_address,
                            'dorm_name': dorm_name, 'primary_manager': primary_manager,
                            'rent_payer': rent_payer, 'utilities_payer': utilities_payer,
                            'management_notes': management_notes
                        }
                        success, message = dormitory_model.update_dormitory_details(dorm_id, updated_details)
                        if success:
                            st.success(message)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(message)

                st.markdown("---")
                st.markdown("##### 危險操作區")
                confirm_delete = st.checkbox("我了解並確認要刪除此宿舍")
                if st.button("🗑️ 刪除此宿舍", type="primary", disabled=not confirm_delete):
                    success, message = dormitory_model.delete_dormitory_by_id(dorm_id)
                    if success:
                        st.success(message)
                        st.session_state.selected_dorm_id = None
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

            with tab2:
                st.markdown("##### 房間列表")
                rooms_df = dormitory_model.get_rooms_for_dorm_as_df(dorm_id)
                st.dataframe(rooms_df, use_container_width=True, hide_index=True)

                st.markdown("---")
                st.subheader("新增、編輯或刪除房間")

                room_options = {row['id']: f"{row['房號']} (容量: {row.get('容量', 'N/A')})" for _, row in rooms_df.iterrows()}
                selected_room_id = st.selectbox(
                    "選擇要編輯或刪除的房間：",
                    options=[None] + list(room_options.keys()),
                    format_func=lambda x: "請選擇..." if x is None else room_options.get(x)
                )

                if selected_room_id:
                    room_details = dormitory_model.get_single_room_details(selected_room_id)
                    if room_details:
                        with st.form("edit_room_form"):
                            st.markdown(f"###### 正在編輯房號: {room_details.get('room_number')}")
                            ec1, ec2, ec3 = st.columns(3)
                            e_capacity = ec1.number_input("房間容量", min_value=0, step=1, value=int(room_details.get('capacity') or 0))
                            e_gender_policy = ec2.selectbox("性別限制", ["可混住", "僅限男性", "僅限女性"], index=["可混住", "僅限男性", "僅限女性"].index(room_details.get('gender_policy')) if room_details.get('gender_policy') in ["可混住", "僅限男性", "僅限女性"] else 0)
                            e_nationality_policy = ec3.selectbox("國籍限制", ["不限", "單一國籍"], index=0 if room_details.get('nationality_policy') != '單一國籍' else 1)
                            e_room_notes = st.text_area("房間備註", value=room_details.get('room_notes', ''))

                            edit_submitted = st.form_submit_button("儲存房間變更")
                            if edit_submitted:
                                updated_details = {
                                    "capacity": e_capacity,
                                    "gender_policy": e_gender_policy,
                                    "nationality_policy": e_nationality_policy,
                                    "room_notes": e_room_notes
                                }
                                success, message = dormitory_model.update_room_details(selected_room_id, updated_details)
                                if success:
                                    st.success(message)
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(message)

                        confirm_delete = st.checkbox("我了解並確認要刪除此房間")
                        if st.button("🗑️ 刪除此房間", type="primary", disabled=not confirm_delete):
                            success, message = dormitory_model.delete_room_by_id(selected_room_id)
                            if success:
                                st.success(message)
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(message)
                
                with st.form("new_room_form", clear_on_submit=True):
                    st.markdown("###### 或新增一個房間至此宿舍")
                    nc1, nc2, nc3 = st.columns(3)
                    room_number = nc1.text_input("新房號 (例如: A01)")
                    capacity = nc2.number_input("房間容量", min_value=1, step=1, value=4)
                    gender_policy = nc3.selectbox("性別限制 ", ["可混住", "僅限男性", "僅限女性"])
                    
                    # --- 【核心修改】在此處新增欄位 ---
                    nc_c1, nc_c2 = st.columns(2)
                    nationality_policy = nc_c1.selectbox("國籍限制 ", ["不限", "單一國籍"])
                    room_notes = nc_c2.text_area("房間備註 ")
                    # --- 修改結束 ---
                    
                    room_submitted = st.form_submit_button("新增房間")
                    if room_submitted:
                        if not room_number:
                            st.error("房號為必填欄位！")
                        else:
                            room_details = {
                                'dorm_id': dorm_id, 'room_number': room_number,
                                'capacity': capacity, 'gender_policy': gender_policy,
                                'nationality_policy': nationality_policy, # 新增
                                'room_notes': room_notes # 新增
                            }
                            success, msg, _ = dormitory_model.add_new_room_to_dorm(room_details)
                            if success:
                                st.success(msg)
                                st.cache_data.clear()
                                st.rerun()
                            else:
                                st.error(msg)