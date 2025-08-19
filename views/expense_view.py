import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import finance_model, dormitory_model, meter_model

def render():
    """Renders the 'Expense Management' page with a stable selection flow and flexible input."""
    st.header("我司管理宿舍 - 費用帳單管理")
    st.info("用於登錄每一筆獨立的水電、網路等費用帳單，系統將根據帳單起訖日自動計算每月攤分費用。")

    # --- 1. Dormitory Selection ---
    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍。")
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

    # --- 2. Add New Bill Record ---
    with st.expander("📝 新增一筆費用帳單"):
        with st.form("new_bill_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)

            # Flexible 'Other' option for new bills
            bill_type_options = ["電費", "水費", "瓦斯費", "網路費", "其他費用", "其他 (請手動輸入)"]
            selected_bill_type = c1.selectbox("費用類型", bill_type_options, key="new_bill_type")

            custom_bill_type = ""
            if selected_bill_type == "其他 (請手動輸入)":
                custom_bill_type = c1.text_input("請輸入自訂費用類型：", key="new_custom_bill_type")

            amount = c2.number_input("帳單總金額", min_value=0, step=100)
            
            meters = meter_model.get_meters_for_dorm_as_df(selected_dorm_id)
            meter_options = {m['id']: f"{m['類型']} ({m['錶號']})" for _, m in meters.iterrows()}
            meter_id = c3.selectbox("對應電水錶 (可選)", options=[None] + list(meter_options.keys()), format_func=lambda x: "無(整棟總計)" if x is None else meter_options.get(x))

            dc1, dc2 = st.columns(2)
            bill_start_date = dc1.date_input("帳單起始日", value=None)
            bill_end_date = dc2.date_input("帳單結束日", value=None)
            
            is_invoiced = st.checkbox("已向雇主/員工請款?")
            notes = st.text_area("備註")
            
            submitted = st.form_submit_button("儲存帳單紀錄")
            if submitted:
                final_bill_type = custom_bill_type if selected_bill_type == "其他 (請手動輸入)" else selected_bill_type

                if not all([bill_start_date, bill_end_date, amount > 0, final_bill_type]):
                    st.error("「費用類型」、「帳單起訖日」和「總金額」為必填欄位！")
                elif bill_start_date > bill_end_date:
                    st.error("帳單起始日不能晚於結束日！")
                else:
                    details = {
                        "dorm_id": selected_dorm_id, "meter_id": meter_id,
                        "bill_type": final_bill_type, "amount": amount,
                        "bill_start_date": str(bill_start_date),
                        "bill_end_date": str(bill_end_date),
                        "is_invoiced": is_invoiced, "notes": notes
                    }
                    success, message, _ = finance_model.add_bill_record(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                    else:
                        st.error(message)

    st.markdown("---")
    
    # --- 3. Bill History and Management ---
    st.subheader(f"歷史帳單總覽: {dorm_options.get(selected_dorm_id)}")

    if st.button("🔄 重新整理帳單列表"):
        st.cache_data.clear()

    @st.cache_data
    def get_bills(dorm_id):
        return finance_model.get_bill_records_for_dorm_as_df(dorm_id)

    bills_df = get_bills(selected_dorm_id)

    if bills_df.empty:
        st.info("此宿舍尚無任何費用帳單紀錄。")
    else:
        st.dataframe(bills_df, use_container_width=True, hide_index=True)
        
        st.markdown("---")

        st.subheader("編輯或刪除單筆帳單")
        
        bill_options_dict = {
            row['id']: f"ID:{row['id']} - {row['費用類型']} ({row['帳單起始日']}~{row['帳單結束日']}) 金額:{row['帳單金額']}" 
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
                with st.form("edit_bill_form"):
                    st.markdown(f"##### 正在編輯 ID: {bill_details['id']} 的帳單")
                    c1, c2, c3 = st.columns(3)

                    # Flexible 'Other' option for editing
                    bill_type_options = ["電費", "水費", "瓦斯費", "網路費", "其他費用", "其他 (請手動輸入)"]
                    current_bill_type = bill_details['bill_type']
                    
                    if current_bill_type in bill_type_options:
                        default_index = bill_type_options.index(current_bill_type)
                    else:
                        default_index = bill_type_options.index("其他 (請手動輸入)")
                    
                    selected_edit_type = c1.selectbox("費用類型", bill_type_options, index=default_index, key="edit_bill_type")
                    
                    custom_edit_type = ""
                    if selected_edit_type == "其他 (請手動輸入)":
                        pre_fill_custom = current_bill_type if current_bill_type not in bill_type_options else ""
                        custom_edit_type = c1.text_input("請輸入自訂費用類型：", value=pre_fill_custom, key="edit_custom_bill_type")

                    amount = c2.number_input("帳單總金額", min_value=0, step=100, value=bill_details['amount'], key="edit_amount")
                    
                    meters = meter_model.get_meters_for_dorm_as_df(selected_dorm_id)
                    meter_options = {m['id']: f"{m['類型']} ({m['錶號']})" for _, m in meters.iterrows()}
                    meter_ids = [None] + list(meter_options.keys())
                    current_meter_index = meter_ids.index(bill_details.get('meter_id')) if bill_details.get('meter_id') in meter_ids else 0
                    meter_id = c3.selectbox("對應電水錶 (可選)", options=meter_ids, format_func=lambda x: "無" if x is None else meter_options.get(x), index=current_meter_index, key="edit_meter")

                    dc1, dc2 = st.columns(2)
                    start_date = datetime.strptime(bill_details['bill_start_date'], '%Y-%m-%d').date()
                    end_date = datetime.strptime(bill_details['bill_end_date'], '%Y-%m-%d').date()
                    bill_start_date = dc1.date_input("帳單起始日", value=start_date, key="edit_start")
                    bill_end_date = dc2.date_input("帳單結束日", value=end_date, key="edit_end")
                    
                    is_invoiced = st.checkbox("已向雇主/員工請款?", value=bool(bill_details.get('is_invoiced')), key="edit_invoiced")
                    notes = st.text_area("備註", value=bill_details.get('notes', ''), key="edit_notes")
                    
                    submitted = st.form_submit_button("儲存變更")
                    if submitted:
                        final_edit_bill_type = custom_edit_type if selected_edit_type == "其他 (請手動輸入)" else selected_edit_type
                        update_data = {
                            "meter_id": meter_id, "bill_type": final_edit_bill_type, "amount": amount,
                            "bill_start_date": str(bill_start_date), "bill_end_date": str(bill_end_date),
                            "is_invoiced": is_invoiced, "notes": notes
                        }
                        success, message = finance_model.update_bill_record(selected_bill_id, update_data)
                        if success:
                            st.success(message)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(message)
                
                st.markdown("---")
                st.markdown("##### 危險操作區")
                confirm_delete = st.checkbox("我了解並確認要刪除此筆費用紀錄")
                if st.button("🗑️ 刪除此筆紀錄", type="primary", disabled=not confirm_delete):
                    success, message = finance_model.delete_bill_record(selected_bill_id)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)