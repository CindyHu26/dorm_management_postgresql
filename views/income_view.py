import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import income_model, dormitory_model

def render():
    st.header("我司管理宿舍 - 其他收入管理")
    st.info("用於登錄房租以外的收入，例如冷氣卡儲值、押金沒收、雜項收入等。")

    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前沒有「我司管理」的宿舍可供操作。")
        return

    dorm_options = {d['id']: d['original_address'] for d in my_dorms}
    selected_dorm_id = st.selectbox("請選擇宿舍：", options=dorm_options.keys(), format_func=lambda x: dorm_options.get(x))

    if not selected_dorm_id: return
    st.markdown("---")

    with st.expander("📝 新增一筆收入紀錄"):
        with st.form("new_income_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            income_item = c1.text_input("收入項目", "冷氣卡儲值")
            amount = c2.number_input("收入金額", min_value=0)
            transaction_date = c3.date_input("收入日期", value=datetime.now())
            notes = st.text_area("備註")
            
            submitted = st.form_submit_button("儲存收入紀錄")
            if submitted:
                details = {
                    "dorm_id": selected_dorm_id, "income_item": income_item,
                    "transaction_date": str(transaction_date), "amount": amount, "notes": notes
                }
                success, message, _ = income_model.add_income_record(details)
                if success:
                    st.success(message)
                    st.cache_data.clear()
                else:
                    st.error(message)

    st.subheader("歷史收入紀錄")
    income_df = income_model.get_income_for_dorm_as_df(selected_dorm_id)
    st.dataframe(income_df, use_container_width=True, hide_index=True)