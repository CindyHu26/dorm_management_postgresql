# views/meter_view.py
# (v3.0 - 支援多宿舍總覽與篩選)

import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import meter_model, dormitory_model

def render():
    """渲染「電水錶管理」頁面"""
    st.info("用於登錄與管理宿舍的電錶、水錶、天然氣、電信等各類用戶號碼。")

    # --- Session State 初始化 ---
    if 'selected_meter_id_for_edit' not in st.session_state:
        st.session_state.selected_meter_id_for_edit = None

    if 'meter_reset_counter' not in st.session_state:
        st.session_state.meter_reset_counter = 0

    # ==========================================
    # 0. 全域搜尋 (保留)
    # ==========================================
    with st.expander("🔍 全域錶號搜尋 (不知宿舍時請用此處查詢)", expanded=False):
        global_search_term = st.text_input("輸入關鍵字搜尋 (地址、錶號、類型...)", placeholder="例如：中山路 或 98-7654-32", key="global_meter_search")
        
        if global_search_term:
            global_results = meter_model.get_all_meters_with_details_as_df(global_search_term)
            if global_results.empty:
                st.warning("找不到符合條件的錶號。")
            else:
                st.dataframe(global_results, width="stretch", hide_index=True, column_config={"id": None})
                st.success(f"找到 {len(global_results)} 筆紀錄。")
        else:
            st.caption("請輸入關鍵字開始搜尋。")

    st.markdown("---")

    # ==========================================
    # 1. 宿舍篩選器 (改為多選，預設全選)
    # ==========================================
    @st.cache_data
    def get_my_dorms():
        return dormitory_model.get_my_company_dorms_for_selection()

    my_dorms = get_my_dorms()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍，無法進行管理。")
        return

    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}
    all_dorm_ids = list(dorm_options.keys())

    # 【修改】改用 multiselect，並預設全選
    selected_dorm_ids = st.multiselect(
        "篩選宿舍 (預設全選，點擊 X 可移除)：",
        options=all_dorm_ids,
        format_func=lambda x: dorm_options.get(x, "未知宿舍"),
        default=all_dorm_ids # 預設全選
    )

    if not selected_dorm_ids:
        st.info("請至少選擇一間宿舍以檢視錶號。")
        # 即使沒選宿舍，我們還是顯示新增區塊，方便使用者新增
    
    st.markdown("---")

    # ==========================================
    # 2. 新增紀錄 (獨立選擇宿舍)
    # ==========================================
    with st.expander("➕ 新增一筆用戶號紀錄", expanded=False):
        with st.form("new_meter_form", clear_on_submit=True):
            st.write("請填寫新錶號資訊：")
            
            # 【修改】因為上方是多選，這裡必須讓使用者明確指定是哪一間宿舍
            # 我們可以嘗試設預設值：如果上方只選了一間，就預設那間；否則不選
            default_add_index = 0
            if len(selected_dorm_ids) == 1:
                try:
                    default_add_index = all_dorm_ids.index(selected_dorm_ids[0]) + 1 # +1 因為有 None 選項
                except: pass

            c0, c_dummy = st.columns([1, 1])
            add_dorm_id = c0.selectbox(
                "所屬宿舍*", 
                options=[None] + all_dorm_ids, 
                format_func=lambda x: "請選擇..." if x is None else dorm_options.get(x),
                index=default_add_index
            )

            c1, c2, c3 = st.columns(3)
            meter_type = c1.selectbox("類型*", ["電錶", "水錶", "天然氣", "電信", "其他"])
            meter_number = c2.text_input("用戶號/錶號*", placeholder="請輸入對應的號碼")
            area_covered = c3.text_input("對應區域/房號 (選填)", placeholder="例如: 1F, 1F-2F")
            
            notes = st.text_area("備註 (選填)", placeholder="例如: 電價調整日期 2025/10/01")

            submitted = st.form_submit_button("儲存紀錄")
            if submitted:
                if not add_dorm_id:
                    st.error("請選擇「所屬宿舍」！")
                elif not meter_number or not meter_type:
                    st.error("「類型」和「用戶號/錶號」為必填欄位！")
                else:
                    details = {
                        "dorm_id": add_dorm_id,
                        "meter_type": meter_type,
                        "meter_number": meter_number,
                        "area_covered": area_covered,
                        "notes": notes 
                    }
                    success, message, _ = meter_model.add_meter_record(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

    st.markdown("---")

    # ==========================================
    # 3. 現有總覽 (顯示所選的多個宿舍)
    # ==========================================
    st.subheader(f"現有用戶號總覽 ({len(selected_dorm_ids)} 間宿舍)")

    if st.button("🔄 重新整理列表"):
        st.cache_data.clear()

    @st.cache_data
    def get_meters_multi(dorm_ids):
        # 呼叫新的後端函式
        return meter_model.get_meters_for_dorms_as_df(dorm_ids)

    if selected_dorm_ids:
        meters_df = get_meters_multi(selected_dorm_ids)

        if meters_df.empty:
            st.info("所選宿舍目前尚無任何用戶號紀錄。")
        else:
            # 顯示表格 (包含宿舍地址)
            st.dataframe(meters_df, width="stretch", hide_index=True, column_config={"id": None}) 

            st.markdown("---")
            
            # ==========================================
            # 4. 編輯 / 刪除
            # ==========================================
            st.subheader("✏️ 編輯 / 🗑️ 刪除單筆紀錄")

            # 選單顯示： [宿舍地址] 類型 (錶號)
            options_dict = {
                row['id']: f"[{row['宿舍地址']}] {row['類型']} ({row['錶號']})"
                for _, row in meters_df.iterrows()
            }

            dynamic_key = f"meter_select_{st.session_state.meter_reset_counter}"
            
            selected_meter_id_edit = st.selectbox(
                "選擇要編輯或刪除的紀錄：",
                options=[None] + list(options_dict.keys()),
                format_func=lambda x: "請選擇..." if x is None else options_dict.get(x),
                key=dynamic_key 
            )
            
            st.session_state.selected_meter_id_for_edit = selected_meter_id_edit

            if selected_meter_id_edit:
                meter_details = meter_model.get_single_meter_details(st.session_state.selected_meter_id_for_edit)
                if meter_details:
                    with st.form(f"edit_meter_form_{st.session_state.selected_meter_id_for_edit}"):
                        st.markdown(f"###### 正在編輯 ID: {meter_details['id']}")
                        
                        # 允許修改宿舍
                        current_dorm_id = meter_details.get('dorm_id')
                        try:
                            d_index = all_dorm_ids.index(current_dorm_id)
                        except:
                            d_index = 0
                            
                        e_dorm_id = st.selectbox("所屬宿舍", options=all_dorm_ids, format_func=lambda x: dorm_options.get(x), index=d_index)

                        ec1, ec2, ec3 = st.columns(3)
                        e_meter_type = ec1.selectbox("類型*", ["電錶", "水錶", "天然氣", "電信", "其他"], index=["電錶", "水錶", "天然氣", "電信", "其他"].index(meter_details.get('meter_type', '其他')))
                        e_meter_number = ec2.text_input("用戶號/錶號*", value=meter_details.get('meter_number', ''))
                        e_area_covered = ec3.text_input("對應區域/房號", value=meter_details.get('area_covered', ''))
                        e_notes = st.text_area("備註", value=meter_details.get('notes', ''))

                        edit_submitted = st.form_submit_button("儲存變更")
                        if edit_submitted:
                            if not e_meter_number or not e_meter_type:
                                 st.error("「類型」和「用戶號/錶號」為必填欄位！")
                            else:
                                updated_details = {
                                    "dorm_id": e_dorm_id, # 允許改宿舍
                                    "meter_type": e_meter_type,
                                    "meter_number": e_meter_number,
                                    "area_covered": e_area_covered,
                                    "notes": e_notes 
                                }
                                success, message = meter_model.update_meter_record(st.session_state.selected_meter_id_for_edit, updated_details)
                                if success:
                                    st.success(message)
                                    st.cache_data.clear()
                                    st.session_state.meter_reset_counter += 1 
                                    st.rerun()
                                else:
                                    st.error(message)

                    confirm_delete = st.checkbox("我確認要刪除此紀錄", key=f"delete_confirm_{st.session_state.selected_meter_id_for_edit}")
                    if st.button("🗑️ 刪除選定紀錄", type="primary", disabled=not confirm_delete, key=f"delete_btn_{st.session_state.selected_meter_id_for_edit}"):
                        success, message = meter_model.delete_meter_record(st.session_state.selected_meter_id_for_edit)
                        if success:
                            st.success(message)
                            st.cache_data.clear()
                            st.session_state.meter_reset_counter += 1 
                            st.rerun()
                        else:
                            st.error(message)
                else:
                     st.error("找不到選定的紀錄資料。")
                     st.session_state.meter_reset_counter += 1
                     st.rerun()