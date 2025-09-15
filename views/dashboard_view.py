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
        if st.button("🔄 重新整理住宿數據", key="refresh_overview"):
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
            
            st.markdown("---")
            st.subheader("特殊狀況人員統計")

            @st.cache_data
            def get_status_summary():
                return dashboard_model.get_special_status_summary()

            status_df = get_status_summary()

            if status_df is None or status_df.empty:
                st.info("目前沒有任何註記特殊狀況的在住人員。")
            else:
                st.dataframe(status_df, width="stretch", hide_index=True)
            
            st.markdown("---")
            st.subheader("各宿舍詳細統計")
            st.dataframe(
                overview_df, 
                width="stretch", 
                hide_index=True,
                column_config={
                    "總人數": st.column_config.NumberColumn(format="%d 人"),
                    "男性人數": st.column_config.NumberColumn(format="%d 人"),
                    "女性人數": st.column_config.NumberColumn(format="%d 人"),
                    "月租金總額": st.column_config.NumberColumn(format="NT$ %d"),
                    "最多人數租金": st.column_config.NumberColumn(format="NT$ %d"),
                    "平均租金": st.column_config.NumberColumn(format="NT$ %d")
                }
            )

    # --- 頁籤二：財務分析 ---
    with tab2:
        st.subheader("我司管理宿舍 - 財務分析")

        today = datetime.now()
        c1, c2 = st.columns(2)
        selected_year = c1.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2)
        selected_month = c2.selectbox("選擇月份", options=range(1, 13), index=today.month - 1)
        year_month_str = f"{selected_year}-{selected_month:02d}"

        with st.container(border=True):
            st.markdown("##### 費用預測分析")
            
            @st.cache_data
            def get_annual_forecast():
                return dashboard_model.get_expense_forecast_data()
            
            annual_forecast_data = get_annual_forecast()
            
            @st.cache_data
            def get_seasonal_forecast(period):
                return dashboard_model.get_seasonal_expense_forecast(period)
                
            seasonal_forecast_data = get_seasonal_forecast(year_month_str)
            
            if annual_forecast_data and seasonal_forecast_data:
                f_col1, f_col2 = st.columns(2)
                
                with f_col1:
                    st.metric(label="預估單月總支出 (年均)", value=f"NT$ {annual_forecast_data['estimated_monthly_expense']:,.0f}", help=f"此估算基於過去 {annual_forecast_data['lookback_days']} 天的數據。")
                
                with f_col2:
                    st.metric(label=f"預估 {year_month_str} 單月總支出 (季節性)", value=f"NT$ {seasonal_forecast_data['estimated_monthly_expense']:,.0f}", help=f"此估算基於去年同期 ({seasonal_forecast_data.get('lookback_period', 'N/A')}) 的數據。")
            else:
                st.info("尚無足夠歷史數據進行預測。")

        st.markdown("---")

        st.subheader("每月實際損益")
        st.info("此報表統計實際發生的「總收入」(員工月費+其他收入)與「總支出」(宿舍月租+當月帳單攤銷+年度費用攤銷)的差額。")

        # --- 將函式定義移到按鈕上方 ---
        @st.cache_data
        def get_finance_data(period):
            return dashboard_model.get_financial_dashboard_data(period)

        if st.button("🔍 產生財務報表"):
            get_finance_data.clear()

        finance_df = get_finance_data(year_month_str)

        if finance_df is None or finance_df.empty:
            st.warning(f"在 {year_month_str} 沒有找到任何「我司管理」宿舍的收支數據。")
        else:
            total_income = int(finance_df['預計總收入'].sum())
            total_expense = int(finance_df['預計總支出'].sum())
            profit_loss = total_income - total_expense
            
            fin_col1, fin_col2, fin_col3 = st.columns(3)
            fin_col1.metric(f"{year_month_str} 預計總收入", f"NT$ {total_income:,}")
            fin_col2.metric(f"{year_month_str} 預計總支出", f"NT$ {total_expense:,}")
            fin_col3.metric(f"{year_month_str} 預估損益", f"NT$ {profit_loss:,}", delta=f"{profit_loss:,}")

            st.markdown("##### 各宿舍損益詳情")
            
            def style_profit(val):
                color = 'red' if val < 0 else 'green' if val > 0 else 'grey'
                return f'color: {color}'
            
            st.dataframe(
                finance_df.style.apply(lambda x: x.map(lambda y: style_profit(y) if x.name == '預估損益' else None)),
                width="stretch", 
                hide_index=True,
                column_config={
                    "預計總收入": st.column_config.NumberColumn(format="NT$ %d"),
                    "宿舍月租": st.column_config.NumberColumn(format="NT$ %d"),
                    "變動雜費(我司支付)": st.column_config.NumberColumn(format="NT$ %d"),
                    "長期攤銷": st.column_config.NumberColumn(format="NT$ %d"),
                    "預計總支出": st.column_config.NumberColumn(format="NT$ %d"),
                    "預估損益": st.column_config.NumberColumn(format="NT$ %d")
                }
            )