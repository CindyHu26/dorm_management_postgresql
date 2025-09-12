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
    selected_dorm_id = st.selectbox("請選擇宿舍：", options=list(dorm_options.keys()), format_func=lambda x: dorm_options.get(x))

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
                    st.rerun()
                else:
                    st.error(message)

    st.markdown("---")
    st.subheader("歷史收入紀錄")

    if st.button("🔄 重新整理列表"):
        st.cache_data.clear()
        
    @st.cache_data
    def get_income_df(dorm_id):
        return income_model.get_income_for_dorm_as_df(dorm_id)
        
    income_df = get_income_df(selected_dorm_id)
    
    if income_df.empty:
        st.info("此宿舍尚無任何其他收入紀錄。")
    else:
        st.dataframe(income_df, width="stretch", hide_index=True)

        st.markdown("---")
        st.subheader("刪除單筆紀錄")
        
        # 使用獨立的下拉選單來選擇要刪除的項目
        options_dict = {
            row['id']: f"ID:{row['id']} - {row['收入日期']} {row['收入項目']} 金額:{row['金額']}" 
            for _, row in income_df.iterrows()
        }
        
        selected_income_id = st.selectbox(
            "請從上方列表選擇一筆紀錄進行刪除：",
            options=[None] + list(options_dict.keys()),
            format_func=lambda x: "請選擇..." if x is None else options_dict.get(x)
        )

        if selected_income_id:
            confirm_delete = st.checkbox("我了解並確認要刪除此筆收入紀錄")
            if st.button("🗑️ 刪除選定紀錄", type="primary", disabled=not confirm_delete):
                success, message = income_model.delete_income_record(selected_income_id)
                if success:
                    st.success(message)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(message)