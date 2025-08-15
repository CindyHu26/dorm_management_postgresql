import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from data_models import finance_model, dormitory_model

def render():
    """渲染「年度費用管理」頁面"""
    st.header("我司管理宿舍 - 年度/長期費用管理")
    st.info("用於登錄如年度保險、消防年費等一次性支付，但效益橫跨多個月份的費用。")

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
    with st.expander("📝 新增一筆長期費用紀錄"):
        with st.form("new_annual_expense_form", clear_on_submit=True):
            today = datetime.now()
            
            c1, c2, c3 = st.columns(3)
            expense_item = c1.text_input("費用項目", placeholder="例如: 建築保險、消防年費")
            payment_date = c2.date_input("實際支付日期", value=today)
            total_amount = c3.number_input("支付總金額", min_value=0, step=1000)

            st.markdown("##### 攤提期間")
            sc1, sc2, sc3 = st.columns(3)
            amortization_start_date = sc1.date_input("攤提起始日", value=payment_date)
            amortization_period = sc2.number_input("攤提月數", min_value=1, step=1, value=12)
            
            # 自動計算結束月份
            if amortization_start_date and amortization_period:
                end_date = amortization_start_date + relativedelta(months=amortization_period - 1)
                amortization_end_month = end_date.strftime('%Y-%m')
                sc3.text_input("攤提結束月份 (自動計算)", value=amortization_end_month, disabled=True)
            
            notes = st.text_area("備註")
            
            submitted = st.form_submit_button("儲存費用紀錄")
            if submitted:
                if not expense_item or not total_amount:
                    st.error("「費用項目」和「總金額」為必填欄位！")
                else:
                    details = {
                        "dorm_id": selected_dorm_id,
                        "expense_item": expense_item,
                        "payment_date": str(payment_date),
                        "total_amount": total_amount,
                        "amortization_start_month": amortization_start_date.strftime('%Y-%m'),
                        "amortization_end_month": amortization_end_month,
                        "notes": notes
                    }
                    success, message, _ = finance_model.add_annual_expense_record(details)
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
    def get_annual_expenses(dorm_id):
        return finance_model.get_annual_expenses_for_dorm_as_df(dorm_id)

    expenses_df = get_annual_expenses(selected_dorm_id)

    if expenses_df.empty:
        st.info("此宿舍尚無任何長期費用紀錄。")
    else:
        st.dataframe(expenses_df, use_container_width=True, hide_index=True)
        
        expense_to_delete = st.selectbox(
            "選擇要刪除的費用紀錄：",
            options=[""] + [f"{row['費用項目']} ({row['支付日期']})" for index, row in expenses_df.iterrows()]
        )
        if st.button("🗑️ 刪除選定紀錄", type="primary"):
            if not expense_to_delete:
                st.warning("請選擇一筆要刪除的紀錄。")
            else:
                item_to_find = expense_to_delete.split(' (')[0]
                date_to_find = expense_to_delete.split(' (')[1][:-1]
                record_id = expenses_df[(expenses_df['費用項目'] == item_to_find) & (expenses_df['支付日期'] == date_to_find)].iloc[0]['id']
                success, message = finance_model.delete_annual_expense_record(record_id)
                if success:
                    st.success(message)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(message)