import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import meter_model, dormitory_model

def render():
    """渲染「電水錶管理」頁面"""
    st.header("我司管理宿舍 - 各類用戶號管理")
    st.info("用於登錄與管理宿舍的電錶、水錶、天然氣、電信等各類用戶號碼。")

    # --- Session State 初始化 ---
    if 'selected_meter_id_for_edit' not in st.session_state:
        st.session_state.selected_meter_id_for_edit = None

    # 初始化重置計數器
    if 'meter_reset_counter' not in st.session_state:
        st.session_state.meter_reset_counter = 0

    # --- 1. 宿舍選擇 ---
    @st.cache_data
    def get_my_dorms():
        return dormitory_model.get_my_company_dorms_for_selection()

    my_dorms = get_my_dorms()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍，無法進行管理。")
        return

    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}

    selected_dorm_id = st.selectbox(
        "請選擇要管理的宿舍：",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options.get(x, "未知宿舍")
    )

    if not selected_dorm_id:
        return

    st.markdown("---")

    # --- 2. 新增紀錄 ---
    with st.expander("➕ 新增一筆用戶號紀錄"):
        with st.form("new_meter_form", clear_on_submit=True):

            c1, c2, c3 = st.columns(3)
            meter_type = c1.selectbox("類型*", ["電錶", "水錶", "天然氣", "電信", "其他"])
            meter_number = c2.text_input("用戶號/錶號*", placeholder="請輸入對應的號碼")
            area_covered = c3.text_input("對應區域/房號 (選填)", placeholder="例如: 1F, 1F-2F")
            # --- 新增備註欄位 ---
            notes = st.text_area("備註 (選填)", placeholder="例如: 電價調整日期 2025/10/01")

            submitted = st.form_submit_button("儲存紀錄")
            if submitted:
                if not meter_number or not meter_type:
                    st.error("「類型」和「用戶號/錶號」為必填欄位！")
                else:
                    details = {
                        "dorm_id": selected_dorm_id,
                        "meter_type": meter_type,
                        "meter_number": meter_number,
                        "area_covered": area_covered,
                        "notes": notes # --- 將備註加入 details ---
                    }
                    success, message, _ = meter_model.add_meter_record(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear() # 清除快取以刷新列表
                        st.rerun() # 重新執行以顯示最新列表
                    else:
                        st.error(message)

    st.markdown("---")

    # --- 3. 現有總覽 ---
    st.subheader(f"現有用戶號總覽: {dorm_options[selected_dorm_id]}")

    if st.button("🔄 重新整理列表"):
        st.cache_data.clear()

    @st.cache_data
    def get_meters(dorm_id):
        return meter_model.get_meters_for_dorm_as_df(dorm_id)

    meters_df = get_meters(selected_dorm_id)

    if meters_df.empty:
        st.info("此宿舍尚無任何用戶號紀錄。")
    else:
        # --- 在 DataFrame 中顯示備註 ---
        st.dataframe(meters_df, width="stretch", hide_index=True, column_config={"id": None}) # 隱藏ID欄位

        st.markdown("---")
        st.subheader("✏️ 編輯 / 🗑️ 刪除單筆紀錄")

        options_dict = {
            row['id']: f"ID:{row['id']} - {row['類型']} ({row['錶號']})"
            for _, row in meters_df.iterrows()
        }

        # 使用 session state 來儲存選擇的 ID
        # 使用動態 key 來支援重置功能
        dynamic_key = f"meter_select_{st.session_state.meter_reset_counter}"
        
        selected_meter_id_edit = st.selectbox(
            "選擇要編輯或刪除的紀錄：",
            options=[None] + list(options_dict.keys()),
            format_func=lambda x: "請選擇..." if x is None else options_dict.get(x),
            key=dynamic_key # 使用動態 key
        )
        
        # 為了保持向後相容或方便存取，我們可以手動同步到舊的 key (選填，視後續邏輯而定，這裡直接用 selected_meter_id_edit 變數即可)
        st.session_state.selected_meter_id_for_edit = selected_meter_id_edit

        if selected_meter_id_edit:
            meter_details = meter_model.get_single_meter_details(st.session_state.selected_meter_id_for_edit)
            if meter_details:
                with st.form(f"edit_meter_form_{st.session_state.selected_meter_id_for_edit}"):
                    st.markdown(f"###### 正在編輯 ID: {meter_details['id']}")
                    ec1, ec2, ec3 = st.columns(3)
                    e_meter_type = ec1.selectbox("類型*", ["電錶", "水錶", "天然氣", "電信", "其他"], index=["電錶", "水錶", "天然氣", "電信", "其他"].index(meter_details.get('meter_type', '其他')))
                    e_meter_number = ec2.text_input("用戶號/錶號*", value=meter_details.get('meter_number', ''))
                    e_area_covered = ec3.text_input("對應區域/房號", value=meter_details.get('area_covered', ''))
                    # --- 新增備註編輯欄位 ---
                    e_notes = st.text_area("備註", value=meter_details.get('notes', ''))

                    edit_submitted = st.form_submit_button("儲存變更")
                    if edit_submitted:
                        if not e_meter_number or not e_meter_type:
                             st.error("「類型」和「用戶號/錶號」為必填欄位！")
                        else:
                            updated_details = {
                                "meter_type": e_meter_type,
                                "meter_number": e_meter_number,
                                "area_covered": e_area_covered,
                                "notes": e_notes # --- 將備註加入更新資料 ---
                            }
                            success, message = meter_model.update_meter_record(st.session_state.selected_meter_id_for_edit, updated_details)
                            if success:
                                st.success(message)
                                st.cache_data.clear()
                                # 增加計數器，強制下次渲染時重建 selectbox (即重置)
                                st.session_state.meter_reset_counter += 1 
                                st.rerun()
                            else:
                                st.error(message)

                # 刪除按鈕放在編輯表單外面
                confirm_delete = st.checkbox("我確認要刪除此紀錄", key=f"delete_confirm_{st.session_state.selected_meter_id_for_edit}")
                if st.button("🗑️ 刪除選定紀錄", type="primary", disabled=not confirm_delete, key=f"delete_btn_{st.session_state.selected_meter_id_for_edit}"):
                    success, message = meter_model.delete_meter_record(st.session_state.selected_meter_id_for_edit)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        # 增加計數器，強制下次渲染時重建 selectbox (即重置)
                        st.session_state.meter_reset_counter += 1 
                        st.rerun()
                    else:
                        st.error(message)
            else:
                 st.error("找不到選定的紀錄資料。")
                 st.session_state.meter_reset_counter += 1
                 st.rerun()