# views/meter_expense_view.py

import streamlit as st
import pandas as pd
from datetime import date
from data_models import finance_model, dormitory_model, meter_model

def render():
    """渲染「錶號費用管理」頁面"""
    st.header("錶號費用管理")
    st.info("此頁面專為快速登錄與特定錶號相關的費用（如水電費）而設計。請先搜尋並選取一個錶號開始操作。")

    # --- 1. 搜尋與選取錶號 ---
    search_term = st.text_input("搜尋錶號、類型或地址以篩選列表：")
    
    @st.cache_data
    def get_all_meters(term):
        return meter_model.search_all_meters(term)

    all_meters = get_all_meters(search_term)
    
    if not all_meters:
        st.warning("找不到任何錶號。請先至「電水錶管理」頁面新增。")
        return

    meter_options = {m['id']: f"{m['original_address']} - {m['meter_type']} ({m['meter_number']})" for m in all_meters}
    
    selected_meter_id = st.selectbox(
        "請選擇要管理的錶號：",
        options=[None] + list(meter_options.keys()),
        format_func=lambda x: "請選擇..." if x is None else meter_options.get(x),
    )

    if not selected_meter_id:
        return

    # --- 2. 顯示關聯的宿舍資訊 ---
    @st.cache_data
    def get_context_details(meter_id):
        dorm_id = meter_model.get_dorm_id_from_meter_id(meter_id)
        if not dorm_id:
            return None, None
        dorm_details = dormitory_model.get_dorm_details_by_id(dorm_id)
        return dorm_id, dorm_details

    dorm_id, dorm_details = get_context_details(selected_meter_id)
    
    if not dorm_id or not dorm_details:
        st.error("發生錯誤：找不到此錶號關聯的宿舍。")
        return
        
    selected_meter_info = next((m for m in all_meters if m['id'] == selected_meter_id), None)

    st.markdown("---")
    with st.container(border=True):
        st.subheader(f"目前操作對象: {meter_options[selected_meter_id]}")
        col1, col2 = st.columns(2)
        col1.info(f"**舊編號:** {dorm_details.get('legacy_dorm_code') or '未設定'}")
        col2.info(f"**變動費用備註:** {dorm_details.get('utility_bill_notes') or '無'}")


    # --- 3. 新增帳單紀錄 ---
    with st.expander("📝 新增一筆費用帳單", expanded=True):
        meter_type_to_bill_type = {"電錶": "電費", "水錶": "水費", "天然氣": "天然氣", "電信": "網路費"}
        default_bill_type = meter_type_to_bill_type.get(selected_meter_info.get('meter_type'), "其他 (請手動輸入)")
        bill_type_options = ["電費", "水費", "天然氣", "瓦斯費", "網路費", "子母車", "其他 (請手動輸入)"]
        try:
            default_index = bill_type_options.index(default_bill_type)
        except ValueError:
            default_index = len(bill_type_options) - 1

        with st.form("new_bill_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            bill_type = c1.selectbox("費用類型", bill_type_options, index=default_index)
            custom_bill_type = c1.text_input("自訂費用類型")
            amount = c2.number_input("帳單總金額", min_value=0, step=100)
            usage_amount = c3.number_input("用量(度/噸) (選填)", value=None, min_value=0.0, format="%.2f")

            dc1, dc2, dc3 = st.columns(3)
            bill_start_date = dc1.date_input("帳單起始日", value=None)
            bill_end_date = dc2.date_input("帳單結束日", value=None)
            
            default_payer = dorm_details.get('utilities_payer', '我司')
            payer_options = ["我司", "雇主", "工人"]
            payer = dc3.selectbox("費用支付方", payer_options, index=payer_options.index(default_payer) if default_payer in payer_options else 0)
            
            is_invoiced = st.checkbox("已向雇主/員工請款?")
            is_pass_through = st.checkbox("此筆為「代收代付」帳款")
            notes = st.text_area("備註")
            
            if st.form_submit_button("儲存帳單紀錄", type="primary"):
                final_bill_type = custom_bill_type if bill_type == "其他 (請手動輸入)" else bill_type
                if not all([bill_start_date, bill_end_date, amount >= 0, final_bill_type]):
                    st.error("「費用類型」、「帳單起訖日」和「總金額」為必填欄位！")
                elif bill_start_date > bill_end_date:
                    st.error("帳單起始日不能晚於結束日！")
                else:
                    details = {"dorm_id": dorm_id, "meter_id": selected_meter_id, "bill_type": final_bill_type, "amount": amount, "usage_amount": usage_amount, "bill_start_date": str(bill_start_date), "bill_end_date": str(bill_end_date), "is_invoiced": is_invoiced, "notes": notes, "payer": payer, "is_pass_through": is_pass_through}
                    success, message, _ = finance_model.add_bill_record(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

    # --- 4. 顯示、編輯、刪除歷史帳單 ---
    st.markdown("---")
    st.subheader("歷史帳單總覽")
    
    @st.cache_data
    def get_bills_for_meter(meter_id):
        return finance_model.get_bill_records_for_meter_as_df(meter_id)

    bills_df = get_bills_for_meter(selected_meter_id)

    if bills_df.empty:
        st.info("此錶號尚無任何費用帳單紀錄。")
    else:
        st.dataframe(bills_df, width="stretch", hide_index=True)

        st.markdown("---")
        st.subheader("編輯或刪除單筆帳單")
        bill_options_dict = {
            row['id']: f"ID:{row['id']} - {row['帳單起始日']}~{row['帳單結束日']} 金額:{row['帳單金額']}" 
            for _, row in bills_df.iterrows()
        }
        selected_bill_id = st.selectbox(
            "請從上方列表選擇一筆紀錄進行操作：",
            options=[None] + list(bill_options_dict.keys()),
            format_func=lambda x: "請選擇..." if x is None else bill_options_dict.get(x)
        )
        if selected_bill_id:
            bill_details = finance_model.get_single_bill_details(selected_bill_id)
            if not bill_details:
                st.error("找不到選定的帳單資料，可能已被刪除。")
            else:
                with st.form(f"edit_bill_form_{selected_bill_id}"):
                    st.markdown(f"##### 正在編輯 ID: {bill_details['id']} 的帳單")
                    st.text_input("對應錶號", value=meter_options.get(selected_meter_id, "未知"), disabled=True)
                    
                    c1, c2, c3 = st.columns(3)
                    
                    bill_type_options_edit = ["電費", "水費", "天然氣", "瓦斯費", "網路費", "子母車", "其他 (請手動輸入)"]
                    current_bill_type = bill_details['bill_type']
                    default_index_edit = bill_type_options_edit.index(current_bill_type) if current_bill_type in bill_type_options_edit else bill_type_options_edit.index("其他 (請手動輸入)")
                    pre_fill_custom = "" if current_bill_type in bill_type_options_edit else current_bill_type
                    
                    selected_edit_type = c1.selectbox("費用類型", bill_type_options_edit, index=default_index_edit, key=f"edit_type_{selected_bill_id}")
                    custom_edit_type = c1.text_input("自訂費用類型", value=pre_fill_custom, key=f"edit_custom_{selected_bill_id}")

                    amount_edit = c2.number_input("帳單總金額", min_value=0, step=100, value=bill_details['amount'], key=f"edit_amount_{selected_bill_id}")
                    
                    usage_value = bill_details.get('usage_amount')
                    display_usage_value = float(usage_value) if usage_value is not None else None
                    usage_amount_edit = c3.number_input("用量(度/噸) (選填)", min_value=0.0, format="%.2f", value=display_usage_value, key=f"edit_usage_{selected_bill_id}")

                    dc1, dc2, dc3 = st.columns(3)
                    bill_start_date_edit = dc1.date_input("帳單起始日", value=bill_details.get('bill_start_date'))
                    bill_end_date_edit = dc2.date_input("帳單結束日", value=bill_details.get('bill_end_date'))
                    
                    payer_options_edit = ["我司", "雇主", "工人"]
                    current_payer = bill_details.get('payer', '我司')
                    payer_index = payer_options_edit.index(current_payer) if current_payer in payer_options_edit else 0
                    payer_edit = dc3.selectbox("費用支付方", payer_options_edit, index=payer_index)

                    is_invoiced_edit = st.checkbox("已向雇主/員工請款?", value=bool(bill_details.get('is_invoiced')))
                    is_pass_through_edit = st.checkbox("此筆為「代收代付」帳款", value=bool(bill_details.get('is_pass_through')))
                    notes_edit = st.text_area("備註", value=bill_details.get('notes', ''))
                    
                    submitted = st.form_submit_button("儲存變更")
                    if submitted:
                        final_edit_bill_type = custom_edit_type if selected_edit_type == "其他 (請手動輸入)" else selected_edit_type
                            
                        update_data = { "meter_id": selected_meter_id, "bill_type": final_edit_bill_type, "amount": amount_edit, "usage_amount": usage_amount_edit, "bill_start_date": str(bill_start_date_edit) if bill_start_date_edit else None, "bill_end_date": str(bill_end_date_edit) if bill_end_date_edit else None, "is_invoiced": is_invoiced_edit, "notes": notes_edit, "payer": payer_edit, "is_pass_through": is_pass_through_edit }
                        success, message = finance_model.update_bill_record(selected_bill_id, update_data)
                        if success:
                            st.success(message)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(message)
                
                st.markdown("---")
                st.markdown("##### 危險操作區")
                confirm_delete = st.checkbox("我了解並確認要刪除此筆費用紀錄", key=f"delete_confirm_{selected_bill_id}")
                if st.button("🗑️ 刪除此筆紀錄", type="primary", disabled=not confirm_delete, key=f"delete_button_{selected_bill_id}"):
                    success, message = finance_model.delete_bill_record(selected_bill_id)
                    if success:
                        st.success(message)
                        st.cache_data.clear() 
                        st.rerun()
                    else:
                        st.error(message)