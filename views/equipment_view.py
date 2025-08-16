import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import equipment_model, dormitory_model

def render():
    """渲染「設備管理」頁面"""
    st.header("我司管理宿舍 - 設備管理")
    st.info("用於登錄與追蹤宿舍內的消防安全設備，例如滅火器、偵煙器等。")

    # --- 1. 宿舍選擇 ---
    @st.cache_data
    def get_my_dorms():
        return dormitory_model.get_my_company_dorms_for_selection()

    my_dorms = get_my_dorms()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍，無法進行設備管理。")
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

    # --- 2. 新增設備紀錄 ---
    with st.expander("➕ 新增一筆設備紀錄"):
        with st.form("new_equipment_form", clear_on_submit=True):
            
            c1, c2, c3 = st.columns(3)
            equipment_name = c1.text_input("設備名稱", placeholder="例如: 滅火器, 緊急照明燈")
            location = c2.text_input("放置位置", placeholder="例如: 2F走廊, 廚房")
            status = c3.selectbox("目前狀態", ["正常", "需更換", "已過期", "維修中"])

            c4, c5 = st.columns(2)
            last_replaced_date = c4.date_input("上次更換/檢查日期", value=None)
            next_check_date = c5.date_input("下次更換/檢查日期", value=None)
            
            submitted = st.form_submit_button("儲存設備紀錄")
            if submitted:
                if not equipment_name:
                    st.error("「設備名稱」為必填欄位！")
                else:
                    details = {
                        "dorm_id": selected_dorm_id,
                        "equipment_name": equipment_name,
                        "location": location,
                        "status": status,
                        "last_replaced_date": str(last_replaced_date) if last_replaced_date else None,
                        "next_check_date": str(next_check_date) if next_check_date else None,
                    }
                    success, message, _ = equipment_model.add_equipment_record(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear() # 清除快取以刷新列表
                    else:
                        st.error(message)

    st.markdown("---")
    
    # --- 3. 設備歷史紀錄 ---
    st.subheader(f"現有設備總覽: {dorm_options[selected_dorm_id]}")

    if st.button("🔄 重新整理設備列表"):
        st.cache_data.clear()

    @st.cache_data
    def get_equipment(dorm_id):
        return equipment_model.get_equipment_for_dorm_as_df(dorm_id)

    equipment_df = get_equipment(selected_dorm_id)

    if equipment_df.empty:
        st.info("此宿舍尚無任何設備紀錄。")
    else:
        st.dataframe(equipment_df, use_container_width=True, hide_index=True)
        
        # 增加刪除功能
        delete_c1, delete_c2 = st.columns([3,1])
        with delete_c1:
            equipment_to_delete = st.selectbox(
                "選擇要刪除的設備紀錄：",
                options=[""] + [f"ID:{row['id']} - {row['設備名稱']} ({row['位置']})" for index, row in equipment_df.iterrows()]
            )
        with delete_c2:
            st.write("") # 佔位
            st.write("") # 佔位
            if st.button("🗑️ 刪除選定紀錄", type="primary"):
                if not equipment_to_delete:
                    st.warning("請選擇一筆要刪除的紀錄。")
                else:
                    record_id = int(equipment_to_delete.split(" - ")[0].replace("ID:", ""))
                    success, message = equipment_model.delete_equipment_record(record_id)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun() # 重新執行以刷新頁面
                    else:
                        st.error(message)