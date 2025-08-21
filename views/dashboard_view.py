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
            """快取住宿總覽的查詢結果。"""
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

            # --- 特殊狀況人員統計 ---
            st.markdown("---")
            st.subheader("特殊狀況人員統計")

            @st.cache_data
            def get_status_summary():
                return dashboard_model.get_special_status_summary()

            status_df = get_status_summary()

            if status_df is None or status_df.empty:
                st.info("目前沒有任何註記特殊狀況的在住人員。")
            else:
                st.dataframe(status_df, use_container_width=True, hide_index=True)

            st.markdown("##### 各宿舍詳細統計")
            manager_filter = st.selectbox(
                "篩選主要管理人：",
                options=["全部"] + overview_df['主要管理人'].unique().tolist(),
                key="overview_manager_filter"
            )

            if manager_filter != "全部":
                display_df = overview_df[overview_df['主要管理人'] == manager_filter]
            else:
                display_df = overview_df
            
            # --- 修正所有 format 字串 ---
            st.dataframe(
                display_df, 
                use_container_width=True, 
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

        with st.container(border=True):
            st.markdown("##### 營運費用估算 (基於過去12個月數據)")
            @st.cache_data
            def get_forecast():
                return dashboard_model.get_expense_forecast_data()
            
            forecast_data = get_forecast()
            
            if forecast_data:
                f_col1, f_col2, f_col3 = st.columns(3)
                f_col1.metric("預估每日總支出", f"NT$ {forecast_data['avg_daily_expense']:,.0f}")
                f_col2.metric("預估單月總支出 (月均)", f"NT$ {forecast_data['estimated_monthly_expense']:,.0f}")
                f_col3.metric("預估年度總支出 (年均)", f"NT$ {forecast_data['estimated_annual_expense']:,.0f}")

                with st.expander("查看估算細節"):
                    st.write(f"此估算基於過去 {forecast_data['lookback_days']} 天的數據分析得出：")
                    st.markdown(f"- **固定成本 (月租)**：每日平均約 NT$ {forecast_data['rent_part']:,.0f} 元")
                    st.markdown(f"- **變動成本 (水電等)**：每日平均約 NT$ {forecast_data['utilities_part']:,.0f} 元")
            else:
                st.info("尚無足夠歷史數據進行估算。")
        
        st.markdown("---")

        st.subheader("每月預估損益 (實際入帳)")
        st.info("此報表統計「預計總收入」與「預計總支出」(宿舍月租+當月帳單攤銷+年度費用攤銷)的差額。")

        today = datetime.now()
        c1, c2 = st.columns(2)
        selected_year = c1.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2)
        selected_month = c2.selectbox("選擇月份", options=range(1, 13), index=today.month - 1)
        year_month_str = f"{selected_year}-{selected_month:02d}"

        if st.button("🔍 產生財務報表"):
            get_finance_data.clear()

        @st.cache_data
        def get_finance_data(period):
            return dashboard_model.get_financial_dashboard_data(period)

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
            
            # --- 修正所有 format 字串 ---
            st.dataframe(
                finance_df,
                use_container_width=True, 
                hide_index=True,
                column_config={
                    "預計總收入": st.column_config.NumberColumn(format=" %d"),
                    "宿舍月租": st.column_config.NumberColumn(format=" %d"),
                    "變動雜費": st.column_config.NumberColumn(format=" %d"),
                    "長期攤銷": st.column_config.NumberColumn(format=" %d"),
                    "預計總支出": st.column_config.NumberColumn(format=" %d"),
                    "預估損益": st.column_config.NumberColumn(format=" %d")
                }
            )