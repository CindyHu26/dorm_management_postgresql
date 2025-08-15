import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import finance_model, dormitory_model

def render():
    """渲染「費用管理」頁面"""
    st.header("我司管理宿舍 - 費用登錄與查詢")

    # --- 1. 宿舍選擇 ---
    @st.cache_data
    def get_my_dorms():
        return dormitory_model.get_my_company_dorms_for_selection()

    my_dorms = get_my_dorms()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍，無法進行費用管理。")
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

    # --- 2. 新增費用紀錄 ---
    with st.expander("📝 新增本月費用紀錄"):
        with st.form("new_expense_form", clear_on_submit=True):
            today = datetime.now()
            # 產生年月格式，例如 2025-08
            billing_month = st.text_input("費用月份 (格式 YYYY-MM)", value=today.strftime('%Y-%m'))
            
            c1, c2, c3 = st.columns(3)
            electricity_fee = c1.number_input("電費", min_value=0, step=100)
            water_fee = c2.number_input("水費", min_value=0, step=50)
            gas_fee = c3.number_input("瓦斯費", min_value=0, step=50)

            c4, c5, c6 = st.columns(3)
            internet_fee = c4.number_input("網路費", min_value=0, step=100)
            other_fee = c5.number_input("其他費用 (如維修)", min_value=0, step=100)
            is_invoiced = c6.checkbox("已向雇主/員工請款?")
            
            submitted = st.form_submit_button("儲存費用紀錄")
            if submitted:
                details = {
                    "dorm_id": selected_dorm_id,
                    "billing_month": billing_month,
                    "electricity_fee": electricity_fee,
                    "water_fee": water_fee,
                    "gas_fee": gas_fee,
                    "internet_fee": internet_fee,
                    "other_fee": other_fee,
                    "is_invoiced": is_invoiced
                }
                success, message, _ = finance_model.add_expense_record(details)
                if success:
                    st.success(message)
                    st.cache_data.clear() # 清除快取以刷新列表
                else:
                    st.error(message)

    st.markdown("---")
    
    # --- 3. 費用歷史紀錄 ---
    st.subheader(f"歷史費用總覽: {dorm_options[selected_dorm_id]}")

    if st.button("🔄 重新整理費用列表"):
        st.cache_data.clear()

    @st.cache_data
    def get_expenses(dorm_id):
        return finance_model.get_expenses_for_dorm_as_df(dorm_id)

    expenses_df = get_expenses(selected_dorm_id)

    if expenses_df.empty:
        st.info("此宿舍尚無任何費用紀錄。")
    else:
        st.dataframe(expenses_df, use_container_width=True, hide_index=True)
        
        # 增加刪除功能
        expense_to_delete = st.selectbox(
            "選擇要刪除的費用紀錄月份：",
            options=[""] + expenses_df['費用月份'].tolist()
        )
        if st.button("🗑️ 刪除選定紀錄", type="primary"):
            if not expense_to_delete:
                st.warning("請選擇一筆要刪除的紀錄。")
            else:
                record_id = expenses_df[expenses_df['費用月份'] == expense_to_delete].iloc[0]['id']
                success, message = finance_model.delete_expense_record(record_id)
                if success:
                    st.success(message)
                    st.cache_data.clear()
                    st.rerun() # 重新執行以刷新頁面
                else:
                    st.error(message)