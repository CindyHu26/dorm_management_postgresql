import streamlit as st
import pandas as pd
from datetime import datetime
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
    selected_dorm_id = st.selectbox("請選擇要管理的宿舍：", options=dorm_options.keys(), format_func=lambda x: dorm_options[x])

    if not selected_dorm_id: return
    st.markdown("---")

    # --- 2. 新增帳單紀錄 ---
    with st.expander("📝 新增一筆費用帳單"):
        with st.form("new_bill_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            bill_type = c1.selectbox("費用類型", ["電費", "水費", "瓦斯費", "網路費", "其他費用"])
            amount = c2.number_input("帳單總金額", min_value=0, step=100)
            
            # 動態載入該宿舍的電水錶選項
            meters = meter_model.get_meters_for_dorm_as_df(selected_dorm_id)
            meter_options = {m['id']: f"{m['類型']} ({m['錶號']})" for _, m in meters.iterrows()}
            meter_id = c3.selectbox("對應電水錶 (可選)", options=[None] + list(meter_options.keys()), format_func=lambda x: "無(整棟總計)" if x is None else meter_options[x])

            dc1, dc2 = st.columns(2)
            bill_start_date = dc1.date_input("帳單起始日", value=None)
            bill_end_date = dc2.date_input("帳單結束日", value=None)
            
            is_invoiced = st.checkbox("已向雇主/員工請款?")
            notes = st.text_area("備註")
            
            submitted = st.form_submit_button("儲存帳單紀錄")
            if submitted:
                if not all([bill_start_date, bill_end_date, amount > 0]):
                    st.error("「帳單起訖日」和「總金額」為必填欄位！")
                elif bill_start_date > bill_end_date:
                    st.error("帳單起始日不能晚於結束日！")
                else:
                    details = {
                        "dorm_id": selected_dorm_id, "meter_id": meter_id,
                        "bill_type": bill_type, "amount": amount,
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
    
    # --- 3. 帳單歷史紀錄 ---
    st.subheader(f"歷史帳單總覽: {dorm_options[selected_dorm_id]}")

    if st.button("🔄 重新整理帳單列表"): st.cache_data.clear()

    @st.cache_data
    def get_bills(dorm_id):
        return finance_model.get_bill_records_for_dorm_as_df(dorm_id)

    bills_df = get_bills(selected_dorm_id)

    if bills_df.empty:
        st.info("此宿舍尚無任何費用帳單紀錄。")
    else:
        st.dataframe(bills_df, use_container_width=True, hide_index=True)
        
        # 刪除功能
        record_to_delete = st.selectbox(
            "選擇要刪除的帳單紀錄：",
            options=[""] + [f"ID:{row['id']} - {row['費用類型']} ({row['帳單起始日']}~{row['帳單結束日']})" for _, row in bills_df.iterrows()]
        )
        if st.button("🗑️ 刪除選定紀錄", type="primary"):
            if not record_to_delete:
                st.warning("請選擇一筆要刪除的紀錄。")
            else:
                record_id = int(record_to_delete.split(" - ")[0].replace("ID:", ""))
                success, message = finance_model.delete_bill_record(record_id)
                if success:
                    st.success(message)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(message)