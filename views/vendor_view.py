# views/vendor_view.py (新檔案)

import streamlit as st
import pandas as pd
from data_models import vendor_model # 引用我們剛剛建立的新模型

def render():
    """渲染「廠商資料管理」頁面"""
    st.info("用於建立與維護維修、清潔、消防等協力廠商的聯絡資訊。")

    # --- 新增區塊 ---
    with st.expander("➕ 新增廠商聯絡資料", expanded=False):
        with st.form("new_vendor_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            service_category = c1.text_input("服務項目 (例如: 水電維修)")
            vendor_name = c2.text_input("廠商名稱 (例如: ABC 水電行)")
            
            c3, c4, c5 = st.columns(3) # 改為 3 欄
            contact_person = c3.text_input("聯絡人")
            phone_number = c4.text_input("聯絡電話")
            tax_id = c5.text_input("統一編號") # <-- 新增
            
            remittance_info = st.text_area("匯款資訊") # <-- 新增
            notes = st.text_area("備註")
            
            submitted = st.form_submit_button("儲存新廠商")
            if submitted:
                if not service_category and not vendor_name:
                    st.error("「服務項目」和「廠商名稱」至少需填寫一項！")
                else:
                    details = {
                        'service_category': service_category, 'vendor_name': vendor_name,
                        'contact_person': contact_person, 'phone_number': phone_number,
                        'tax_id': tax_id, # <-- 新增
                        'remittance_info': remittance_info, # <-- 新增
                        'notes': notes
                    }
                    success, message = vendor_model.add_vendor(details)
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)

    st.markdown("---")

    # --- 總覽、搜尋與編輯 ---
    st.subheader("廠商聯絡人總覽")
    
    search_term = st.text_input("搜尋廠商 (可輸入服務項目、名稱、聯絡人或電話)")
    
    vendors_df = vendor_model.get_vendors_for_view(search_term)
    
    if vendors_df.empty:
        st.info("目前沒有任何廠商資料，或沒有符合搜尋條件的結果。")
    else:
        st.dataframe(vendors_df, width='stretch', hide_index=True, column_config={"id": None})

        st.markdown("---")
        st.subheader("編輯或刪除單筆資料")

        options_dict = {
            row['id']: f"ID:{row['id']} - {row['服務項目']} / {row['廠商名稱'] or 'N/A'} (聯絡人: {row['聯絡人'] or 'N/A'})"
            for _, row in vendors_df.iterrows()
        }
        selected_vendor_id = st.selectbox(
            "請從上方列表選擇一筆紀錄進行操作：",
            options=[None] + list(options_dict.keys()),
            format_func=lambda x: "請選擇..." if x is None else options_dict.get(x)
        )

        if selected_vendor_id:
            vendor_details = vendor_model.get_single_vendor_details(selected_vendor_id)
            if not vendor_details:
                st.error("找不到選定的廠商資料，可能已被刪除。")
            else:
                with st.form(f"edit_vendor_form_{selected_vendor_id}"):
                    st.markdown(f"###### 正在編輯 ID: {selected_vendor_id} 的資料")
                    ec1, ec2 = st.columns(2)
                    e_service_category = ec1.text_input("服務項目", value=vendor_details.get('service_category', ''))
                    e_vendor_name = ec2.text_input("廠商名稱", value=vendor_details.get('vendor_name', ''))
                    
                    ec3, ec4, ec5 = st.columns(3) # 改為 3 欄
                    e_contact_person = ec3.text_input("聯絡人", value=vendor_details.get('contact_person', ''))
                    e_phone_number = ec4.text_input("聯絡電話", value=vendor_details.get('phone_number', ''))
                    e_tax_id = ec5.text_input("統一編號", value=vendor_details.get('tax_id', '')) # <-- 新增
                    
                    e_remittance_info = st.text_area("匯款資訊", value=vendor_details.get('remittance_info', '')) # <-- 新增
                    e_notes = st.text_area("備註", value=vendor_details.get('notes', ''))
                    
                    edit_submitted = st.form_submit_button("儲存變更")
                    if edit_submitted:
                        updated_details = {
                            'service_category': e_service_category, 'vendor_name': e_vendor_name,
                            'contact_person': e_contact_person, 'phone_number': e_phone_number,
                            'tax_id': e_tax_id, # <-- 新增
                            'remittance_info': e_remittance_info, # <-- 新增
                            'notes': e_notes
                        }
                        success, message = vendor_model.update_vendor(selected_vendor_id, updated_details)
                        if success:
                            st.success(message)
                            st.rerun()
                        else:
                            st.error(message)
                            
                st.markdown("---")
                st.markdown("##### 危險操作區")
                confirm_delete = st.checkbox("我了解並確認要刪除此筆廠商資料", key=f"delete_confirm_{selected_vendor_id}")
                if st.button("🗑️ 刪除此筆資料", type="primary", disabled=not confirm_delete, key=f"delete_button_{selected_vendor_id}"):
                    success, message = vendor_model.delete_vendor(selected_vendor_id)
                    if success:
                        st.success(message)
                        st.rerun()
                    else:
                        st.error(message)