import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import meter_model, dormitory_model

def render():
    """渲染「電水錶管理」頁面"""
    st.header("我司管理宿舍 - 電水錶管理")
    st.info("用於登錄與管理一棟宿舍內有多個電錶或水錶的特殊情況。")

    # --- 1. 宿舍選擇 ---
    @st.cache_data
    def get_my_dorms():
        return dormitory_model.get_my_company_dorms_for_selection()

    my_dorms = get_my_dorms()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍，無法進行電水錶管理。")
        return

    dorm_options = {d['id']: d['original_address'] for d in my_dorms}
    
    selected_dorm_id = st.selectbox(
        "請選擇要管理的宿舍：",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options[x]
    )

    if not selected_dorm_id:
        return

    st.markdown("---")

    # --- 2. 新增電水錶紀錄 ---
    with st.expander("➕ 新增一筆電水錶紀錄"):
        with st.form("new_meter_form", clear_on_submit=True):
            
            c1, c2, c3 = st.columns(3)
            meter_type = c1.selectbox("電錶/水錶", ["電錶", "水錶"])
            meter_number = c2.text_input("錶號", placeholder="例如: 07-12-3333-44-5")
            area_covered = c3.text_input("對應區域/房號", placeholder="例如: 1F, 1F-1")
            
            submitted = st.form_submit_button("儲存紀錄")
            if submitted:
                if not meter_number:
                    st.error("「錶號」為必填欄位！")
                else:
                    details = {
                        "dorm_id": selected_dorm_id,
                        "meter_type": meter_type,
                        "meter_number": meter_number,
                        "area_covered": area_covered,
                    }
                    success, message, _ = meter_model.add_meter_record(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear() # 清除快取以刷新列表
                    else:
                        st.error(message)

    st.markdown("---")
    
    # --- 3. 現有電水錶總覽 ---
    st.subheader(f"現有電水錶總覽: {dorm_options[selected_dorm_id]}")

    if st.button("🔄 重新整理列表"):
        st.cache_data.clear()

    @st.cache_data
    def get_meters(dorm_id):
        return meter_model.get_meters_for_dorm_as_df(dorm_id)

    meters_df = get_meters(selected_dorm_id)

    if meters_df.empty:
        st.info("此宿舍尚無任何獨立的電水錶紀錄。")
    else:
        st.dataframe(meters_df, use_container_width=True, hide_index=True)
        
        # 增加刪除功能
        delete_c1, delete_c2 = st.columns([3,1])
        with delete_c1:
            meter_to_delete = st.selectbox(
                "選擇要刪除的紀錄：",
                options=[""] + [f"ID:{row['id']} - {row['類型']} ({row['錶號']})" for index, row in meters_df.iterrows()]
            )
        with delete_c2:
            st.write("") # 佔位
            st.write("") # 佔位
            if st.button("🗑️ 刪除選定紀錄", type="primary"):
                if not meter_to_delete:
                    st.warning("請選擇一筆要刪除的紀錄。")
                else:
                    record_id = int(meter_to_delete.split(" - ")[0].replace("ID:", ""))
                    success, message = meter_model.delete_meter_record(record_id)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun() # 重新執行以刷新頁面
                    else:
                        st.error(message)