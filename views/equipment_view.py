import streamlit as st
import pandas as pd
from datetime import datetime, date
from data_models import equipment_model, dormitory_model

def render():
    """渲染「設備管理」頁面"""
    st.header("我司管理宿舍 - 設備管理")
    st.info("用於登錄與追蹤宿舍內的消防安全設備，例如滅火器、偵煙器等。")

    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍，無法進行設備管理。")
        return

    dorm_options = {d['id']: d['original_address'] for d in my_dorms}
    selected_dorm_id = st.selectbox(
        "請選擇要管理的宿舍：",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options.get(x, "未知宿舍")
    )

    if not selected_dorm_id:
        return

    st.markdown("---")

    with st.expander("➕ 新增一筆設備紀錄"):
        with st.form("new_equipment_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            equipment_options = ["滅火器", "緊急照明燈", "偵煙器", "建物申報單", "其他 (請手動輸入)"]
            selected_equipment_name = c1.selectbox("設備名稱", equipment_options)
            custom_equipment_name = c1.text_input("自訂設備名稱", help="若上方選擇「其他」，請在此處填寫")
            location = c2.text_input("放置位置", placeholder="例如: 2F走廊, 廚房")
            status = c3.selectbox("目前狀態", ["正常", "需更換", "已過期", "維修中"])

            c4, c5 = st.columns(2)
            last_replaced_date = c4.date_input("上次更換/檢查日期", value=None)
            next_check_date = c5.date_input("下次更換/檢查日期", value=None)
            
            report_path = st.text_input("文件路徑 (選填)", placeholder="例如: C:\\申報單\\公安申報.pdf")
            
            submitted = st.form_submit_button("儲存設備紀錄")
            if submitted:
                final_equipment_name = custom_equipment_name if selected_equipment_name == "其他 (請手動輸入)" and custom_equipment_name else selected_equipment_name
                if not final_equipment_name or final_equipment_name == "其他 (請手動輸入)":
                    st.error("「設備名稱」為必填欄位！")
                else:
                    details = {
                        "dorm_id": selected_dorm_id,
                        "equipment_name": final_equipment_name,
                        "location": location, "status": status,
                        "last_replaced_date": str(last_replaced_date) if last_replaced_date else None,
                        "next_check_date": str(next_check_date) if next_check_date else None,
                        "report_path": report_path
                    }
                    success, message, _ = equipment_model.add_equipment_record(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

    st.markdown("---")
    
    st.subheader(f"現有設備總覽: {dorm_options.get(selected_dorm_id)}")
    
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
        
        st.markdown("---")
        st.subheader("編輯或刪除單筆設備")
        
        options_dict = {row['id']: f"ID:{row['id']} - {row['設備名稱']} ({row.get('位置', '')})" for _, row in equipment_df.iterrows()}
        selected_id = st.selectbox("請選擇要操作的設備：", [None] + list(options_dict.keys()), format_func=lambda x: "請選擇..." if x is None else options_dict.get(x))

        if selected_id:
            details = equipment_model.get_single_equipment_details(selected_id)
            if details:
                with st.form(f"edit_equipment_form_{selected_id}"):
                    st.markdown(f"##### 正在編輯 ID: {details['id']} 的設備")
                    ec1, ec2, ec3 = st.columns(3)
                    equipment_options_edit = ["滅火器", "緊急照明燈", "偵煙器", "建物申報單", "其他 (請手動輸入)"]
                    current_name = details.get('equipment_name', '')
                    
                    default_index = equipment_options_edit.index(current_name) if current_name in equipment_options_edit else equipment_options_edit.index("其他 (請手動輸入)")
                    pre_fill_custom = "" if current_name in equipment_options_edit else current_name

                    selected_name = ec1.selectbox("設備名稱", equipment_options_edit, index=default_index)
                    custom_name = ec1.text_input("自訂設備名稱", value=pre_fill_custom, help="若上方選擇「其他」，請在此處填寫")
                    
                    e_location = ec2.text_input("放置位置", value=details.get('location', ''))
                    status_options = ["正常", "需更換", "已過期", "維修中"]
                    e_status = ec3.selectbox("目前狀態", status_options, index=status_options.index(details.get('status')) if details.get('status') in status_options else 0)

                    ec4, ec5 = st.columns(2)
                    # 【核心修改】直接使用 date 物件，不再需要 strptime
                    last_date = details.get('last_replaced_date')
                    next_date = details.get('next_check_date')

                    e_last_replaced_date = ec4.date_input("上次更換/檢查日期", value=last_date)
                    e_next_check_date = ec5.date_input("下次更換/檢查日期", value=next_date)
                
                    e_report_path = st.text_input("文件路徑", value=details.get('report_path', ''))

                    edit_submitted = st.form_submit_button("儲存變更")
                    if edit_submitted:
                        final_name_edit = custom_name if selected_name == "其他 (請手動輸入)" and custom_name else selected_name
                        
                        update_data = {
                            "equipment_name": final_name_edit, "location": e_location,
                            "status": e_status,
                            "last_replaced_date": str(e_last_replaced_date) if e_last_replaced_date else None,
                            "next_check_date": str(e_next_check_date) if e_next_check_date else None,
                            "report_path": e_report_path
                        }
                        success, message = equipment_model.update_equipment_record(selected_id, update_data)
                        if success:
                            st.success(message)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(message)

                st.markdown("---")
                st.markdown("##### 危險操作區")
                confirm_delete = st.checkbox("我了解並確認要刪除此筆設備紀錄", key=f"delete_confirm_{selected_id}")
                if st.button("🗑️ 刪除此紀錄", type="primary", disabled=not confirm_delete, key=f"delete_button_{selected_id}"):
                    success, message = equipment_model.delete_equipment_record(selected_id)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)