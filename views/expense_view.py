import streamlit as st
import pandas as pd
from datetime import datetime, date
from data_models import finance_model, dormitory_model, meter_model

def render():
    """渲染「費用管理」頁面 (帳單式)"""
    st.header("我司管理宿舍 - 費用帳單管理")
    st.info("用於登錄每一筆獨立的水電、網路等費用帳單，系統將根據帳單起訖日自動計算每月攤分費用。")

    # --- 1. 宿舍選擇 ---
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

    # --- 2. 新增帳單紀錄 ---
    with st.expander("📝 新增一筆費用帳單"):
        with st.form("new_bill_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            
            bill_type_options = ["電費", "水費", "天然氣", "瓦斯費", "網路費", "子母車", "其他 (請手動輸入)"]
            selected_bill_type = c1.selectbox("費用類型", bill_type_options)
            custom_bill_type = c1.text_input("自訂費用類型", help="若上方選擇「其他 (請手動輸入)」，請務必在此填寫")

            amount = c2.number_input("帳單總金額", min_value=0, step=100)
            
            meters_for_selection = meter_model.get_meters_for_selection(selected_dorm_id)
            meter_options = {m['id']: m.get('display_name', m['id']) for m in meters_for_selection}
            meter_id = c3.selectbox("對應電水錶 (可選)", options=[None] + list(meter_options.keys()), format_func=lambda x: "無(整棟總計)" if x is None else meter_options.get(x))

            dc1, dc2, dc3 = st.columns(3)
            bill_start_date = dc1.date_input("帳單起始日", value=None)
            bill_end_date = dc2.date_input("帳單結束日", value=None)
            payer = dc3.selectbox("費用支付方", ["我司", "雇主", "工人"])
            
            is_invoiced = st.checkbox("已向雇主/員工請款?")
            is_pass_through = st.checkbox("此筆為「代收代付」帳款", help="勾選此項後，帳單金額將同時計入收入和支出，損益為零。適用於我司先向工人收費，再代為繳納的狀況。")
            notes = st.text_area("備註")
            
            submitted = st.form_submit_button("儲存帳單紀錄")
            if submitted:
                final_bill_type = custom_bill_type if selected_bill_type == "其他 (請手動輸入)" else selected_bill_type

                if not all([bill_start_date, bill_end_date, amount >= 0, final_bill_type]):
                    st.error("「費用類型」、「帳單起訖日」和「總金額」為必填欄位！")
                elif bill_start_date > bill_end_date:
                    st.error("帳單起始日不能晚於結束日！")
                else:
                    details = {
                        "dorm_id": selected_dorm_id, "meter_id": meter_id,
                        "bill_type": final_bill_type, "amount": amount,
                        "bill_start_date": str(bill_start_date),
                        "bill_end_date": str(bill_end_date),
                        "is_invoiced": is_invoiced, "notes": notes,
                        "payer": payer,
                        "is_pass_through": is_pass_through
                    }
                    success, message, _ = finance_model.add_bill_record(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

    st.markdown("---")
    
    # --- 3. 帳單歷史紀錄與管理 ---
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
        # 現在 DataFrame 會自動包含新欄位
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
                with st.form(f"edit_bill_form_{selected_bill_id}"):
                    st.markdown(f"##### 正在編輯 ID: {bill_details['id']} 的帳單")
                    c1, c2, c3 = st.columns(3)
                    
                    bill_type_options = ["電費", "水費", "天然氣", "瓦斯費", "網路費", "子母車", "其他 (請手動輸入)"]
                    current_bill_type = bill_details['bill_type']
                    
                    default_index = bill_type_options.index(current_bill_type) if current_bill_type in bill_type_options else bill_type_options.index("其他 (請手動輸入)")
                    pre_fill_custom = "" if current_bill_type in bill_type_options else current_bill_type
                    
                    selected_edit_type = c1.selectbox("費用類型", bill_type_options, index=default_index)
                    custom_edit_type = c1.text_input("自訂費用類型", value=pre_fill_custom, help="若上方選擇「其他 (請手動輸入)」，請務必在此填寫")

                    amount = c2.number_input("帳單總金額", min_value=0, step=100, value=bill_details['amount'])
                    
                    meters_for_edit = meter_model.get_meters_for_selection(selected_dorm_id)
                    meter_options_edit = {m['id']: m.get('display_name', m['id']) for m in meters_for_edit}
                    meter_ids_edit = [None] + list(meter_options_edit.keys())
                    
                    current_meter_id = bill_details.get('meter_id')
                    current_meter_index = meter_ids_edit.index(current_meter_id) if current_meter_id in meter_ids_edit else 0
                    meter_id = c3.selectbox("對應電水錶 (可選)", options=meter_ids_edit, format_func=lambda x: "無" if x is None else meter_options_edit.get(x), index=current_meter_index)

                    dc1, dc2, dc3 = st.columns(3)
                    start_date = bill_details.get('bill_start_date')
                    end_date = bill_details.get('bill_end_date')
                    bill_start_date = dc1.date_input("帳單起始日", value=start_date)
                    bill_end_date = dc2.date_input("帳單結束日", value=end_date)
                    
                    # 【核心修改】加入編輯欄位
                    payer_options = ["我司", "雇主", "工人"]
                    current_payer = bill_details.get('payer', '我司') # 預設為我司
                    payer_index = payer_options.index(current_payer) if current_payer in payer_options else 0
                    payer = dc3.selectbox("費用支付方", payer_options, index=payer_index)

                    is_invoiced = st.checkbox("已向雇主/員工請款?", value=bool(bill_details.get('is_invoiced')))
                    is_pass_through = st.checkbox("此筆為「代收代付」帳款", value=bool(bill_details.get('is_pass_through')), help="勾選此項後，帳單金額將同時計入收入和支出，損益為零。適用於我司先向工人收費，再代為繳納的狀況。")
                    notes = st.text_area("備註", value=bill_details.get('notes', ''))
                    
                    submitted = st.form_submit_button("儲存變更")
                    if submitted:
                        final_edit_bill_type = custom_edit_type if selected_edit_type == "其他 (請手動輸入)" else selected_edit_type
                            
                        update_data = {
                            "meter_id": meter_id, "bill_type": final_edit_bill_type, "amount": amount,
                            "bill_start_date": str(bill_start_date) if bill_start_date else None, 
                            "bill_end_date": str(bill_end_date) if bill_end_date else None,
                            "is_invoiced": is_invoiced, "notes": notes,
                            "payer": payer, # 【新增】
                            "is_pass_through": is_pass_through # 【新增】
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
                confirm_delete = st.checkbox("我了解並確認要刪除此筆費用紀錄", key=f"delete_confirm_{selected_bill_id}")
                if st.button("🗑️ 刪除此筆紀錄", type="primary", disabled=not confirm_delete, key=f"delete_button_{selected_bill_id}"):
                    success, message = finance_model.delete_bill_record(selected_bill_id)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)