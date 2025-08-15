import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import dashboard_model

def render():
    """渲染儀表板頁面，包含「住宿總覽」和「財務分析」兩個頁籤。"""
    st.header("系統儀表板")

    tab1, tab2 = st.tabs(["📊 住宿情況總覽", "💰 財務收支分析"])

    # --- 頁籤一：住宿總覽 ---
    with tab1:
        st.subheader("各宿舍即時住宿統計")
        if st.button("🔄 重新整理住宿數據"):
            st.cache_data.clear()

        @st.cache_data
        def get_overview_data():
            return dashboard_model.get_dormitory_dashboard_data()

        overview_df = get_overview_data()

        if overview_df is None or overview_df.empty:
            st.warning("目前沒有任何在住人員的資料可供統計。")
        else:
            total_residents = int(overview_df['總人數'].sum())
            manager_summary = overview_df.groupby('主要管理人')['總人數'].sum()
            my_company_residents = int(manager_summary.get('我司', 0))
            employer_residents = int(manager_summary.get('雇主', 0))
            col1, col2, col3 = st.columns(3)
            col1.metric("總在住人數", f"{total_residents} 人")
            col2.metric("我司管理宿舍人數", f"{my_company_residents} 人")
            col3.metric("雇主管理宿舍人數", f"{employer_residents} 人")
            
            st.dataframe(overview_df, use_container_width=True, hide_index=True)

    # --- 頁籤二：財務分析 ---
    with tab2:
        st.subheader("我司管理宿舍 - 每月預估損益")
        st.info("此報表統計「預計總收入」(在住人員月費總和)與「預計總支出」(宿舍月租+上月雜費+本月攤銷)的差額。")

        # 時間選擇器
        today = datetime.now()
        selected_year = st.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2)
        selected_month = st.selectbox("選擇月份", options=range(1, 13), index=today.month - 1)
        year_month_str = f"{selected_year}-{selected_month:02d}"

        if st.button("🔍 產生財務報表"):
            st.cache_data.clear()

        @st.cache_data
        def get_finance_data(period):
            return dashboard_model.get_financial_dashboard_data(period)

        finance_df = get_finance_data(year_month_str)

        if finance_df is None or finance_df.empty:
            st.warning(f"在 {year_month_str} 沒有找到任何「我司管理」宿舍的收支數據。")
        else:
            # 總覽指標
            total_income = int(finance_df['預計總收入'].sum())
            total_expense = int(finance_df['預計總支出'].sum())
            profit_loss = total_income - total_expense
            
            f_col1, f_col2, f_col3 = st.columns(3)
            f_col1.metric(f"{year_month_str} 預計總收入", f"NT$ {total_income:,}")
            f_col2.metric(f"{year_month_str} 預計總支出", f"NT$ {total_expense:,}")
            f_col3.metric(f"{year_month_str} 預估損益", f"NT$ {profit_loss:,}", delta=f"{profit_loss:,}")

            st.markdown("##### 各宿舍損益詳情")
            
            # 為損益欄位上色
            def style_profit(val):
                color = 'red' if val < 0 else 'green'
                return f'color: {color}'

            st.dataframe(
                finance_df.style.applymap(style_profit, subset=['預估損益']),
                use_container_width=True, 
                hide_index=True
            )