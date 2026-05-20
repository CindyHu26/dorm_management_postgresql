# views/dashboard_view.py

import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from data_models import dashboard_model

def render():
    """渲染儀表板頁面，包含「住宿總覽」、「財務分析」與「雇主統計」三個頁籤。"""
    st.header("系統儀表板")

    tab1, tab2, tab3 = st.tabs(["📊 住宿情況總覽", "💰 財務收支分析", "👥 雇主住宿統計"])

    # --- 頁籤一：住宿總覽 (維持不變) ---
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

    # --- 頁籤二：財務分析 (加入名詞解釋) ---
    with tab2:
        st.subheader("我司管理宿舍 - 財務分析")

        # === 【新增】費用名詞解釋區塊 ===
        with st.expander("💡 費用項目名詞解釋 (點此查看)", expanded=False):
            st.markdown("為方便理解財務報表，以下為各費用類別的定義：")
            c_info1, c_info2, c_info3 = st.columns(3)
            
            with c_info1:
                st.markdown("##### 📋 長期合約")
                st.caption("""
                指每月金額固定的經常性支出。
                * **例如**：付給房東的房租、固定網路費、垃圾清運費。
                * **來源**：長期合約管理。
                """)
            
            with c_info2:
                st.markdown("##### 💧 變動雜費")
                st.caption("""
                指依據帳單浮動的支出。
                * **例如**：台電電費、自來水費、瓦斯費、臨時小額修繕。
                * **來源**：費用帳單管理。
                """)
            
            with c_info3:
                st.markdown("##### 📅 長期攤銷")
                st.caption("""
                指一次付清但分攤至各月的成本。
                * **例如**：年度消防安檢、商業保險、設備採購、大型修繕工程。
                * **來源**：年度/攤銷費用、設備管理。
                """)
        # ==============================

        fin_tab1, fin_tab2 = st.tabs(["按月檢視", "按年檢視"])
        
        today = datetime.now()
        today_year = today.year

        # --- 子頁籤一：按月檢視 ---
        with fin_tab1:
            st.markdown("##### 選擇月份")
            
            default_date = today - relativedelta(months=2)
            default_year = default_date.year
            default_month = default_date.month
            
            year_options = list(range(today_year - 2, today_year + 2))
            try:
                default_year_index = year_options.index(default_year)
            except ValueError:
                default_year_index = 2

            c1, c2 = st.columns(2)
            selected_year_month = c1.selectbox("選擇年份", options=year_options, index=default_year_index, key="month_year")
            selected_month_month = c2.selectbox("選擇月份", options=range(1, 13), index=default_month - 1, key="month_month")
            year_month_str = f"{selected_year_month}-{selected_month_month:02d}"

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

            @st.cache_data
            def get_finance_data(period):
                return dashboard_model.get_financial_dashboard_data(period)

            if st.button("🔍 產生每月財務報表", key="generate_monthly_report"):
                get_finance_data.clear()

            finance_df = get_finance_data(year_month_str)

            if finance_df is None or finance_df.empty:
                st.warning(f"在 {year_month_str} 沒有找到任何「我司管理」的收支數據。")
            else:
                total_income = int(finance_df['總收入'].sum())
                total_expense = int(finance_df['總支出'].sum())
                profit_loss = total_income - total_expense
                
                fin_col1, fin_col2, fin_col3 = st.columns(3)
                fin_col1.metric(f"{year_month_str} 總收入", f"NT$ {total_income:,}")
                fin_col2.metric(f"{year_month_str} 總支出", f"NT$ {total_expense:,}")
                fin_col3.metric(f"{year_month_str} 淨損益", f"NT$ {profit_loss:,}", delta=f"{profit_loss:,}")

                st.markdown("##### 各宿舍損益詳情")
                
                def style_profit(val):
                    color = 'red' if val < 0 else 'green' if val > 0 else 'grey'
                    return f'color: {color}'
                
                # 【修改】在 column_config 中加入 help 提示
                st.dataframe(
                    finance_df.style.apply(lambda x: x.map(lambda y: style_profit(y) if x.name == '淨損益' else None)),
                    width="stretch", 
                    hide_index=True,
                    column_order=["宿舍地址", "雇主", "總收入", "總支出", "淨損益"],
                    column_config={
                        "宿舍地址": st.column_config.TextColumn("宿舍地址", width="medium"),
                        "雇主": st.column_config.TextColumn("雇主", width="medium"),
                        "總收入": st.column_config.NumberColumn("總收入", format="NT$ %d", help="包含工人月費扣款 + 其他雜項收入"),
                        "總支出": st.column_config.NumberColumn("總支出", format="NT$ %d", help="包含合約 + 變動雜費 + 年度攤銷"),
                        "淨損益": st.column_config.NumberColumn("淨損益", format="NT$ %d"),
                        
                        # 隱藏欄位 (點擊眼睛可見)，加上詳細說明
                        "長期合約支出": st.column_config.NumberColumn("長期合約支出", format="NT$ %d", help="固定的月費支出 (如房租)"),
                        "變動雜費(我司支付)": st.column_config.NumberColumn("變動雜費", format="NT$ %d", help="浮動的帳單支出 (如水電)"),
                        "長期攤銷": st.column_config.NumberColumn("長期攤銷", format="NT$ %d", help="分攤至本月的年度費用 (如保險、修繕)"),
                        "宿舍備註": st.column_config.TextColumn("宿舍備註")
                    }
                )

        # --- 子頁籤二：按年檢視 ---
        with fin_tab2:
            st.markdown("##### 選擇年份")
            selected_year_annual = st.selectbox("選擇年份", options=range(today_year - 2, today_year + 2), index=2, key="annual_year")

            st.markdown("---")
            
            if selected_year_annual < today_year:
                annual_title = f"{selected_year_annual} 年度實際損益 (完整年度)"
                annual_info = f"此報表統計 {selected_year_annual} 年 1月1日 至 12月31日 的完整年度收支總額。"
            else:
                annual_title = f"{selected_year_annual} 年度實際損益 (計算至今日)"
                annual_info = f"此報表統計 {selected_year_annual} 年 1月1日 至「今天」為止的收支總額。"
            
            st.subheader(annual_title)
            st.info(annual_info)
            
            @st.cache_data
            def get_annual_finance_data(year):
                return dashboard_model.get_annual_financial_dashboard_data(year)

            if st.button("🔍 產生年度財務報表", key="generate_annual_report"):
                get_annual_finance_data.clear()
            
            annual_finance_df = get_annual_finance_data(selected_year_annual)

            if annual_finance_df is None or annual_finance_df.empty:
                st.warning(f"在 {selected_year_annual} 年沒有找到任何「我司管理」的收支數據。")
            else:
                total_income_annual = int(annual_finance_df['總收入'].sum())
                total_expense_annual = int(annual_finance_df['總支出'].sum())
                profit_loss_annual = total_income_annual - total_expense_annual
                
                fin_col_a1, fin_col_a2, fin_col_a3 = st.columns(3)
                fin_col_a1.metric(f"{selected_year_annual}年 總收入", f"NT$ {total_income_annual:,}")
                fin_col_a2.metric(f"{selected_year_annual}年 總支出", f"NT$ {total_expense_annual:,}")
                fin_col_a3.metric(f"{selected_year_annual}年 淨損益", f"NT$ {profit_loss_annual:,}", delta=f"{profit_loss_annual:,}")

                st.markdown("##### 各宿舍年度損益詳情")
                
                def style_profit_annual(val):
                    color = 'red' if val < 0 else 'green' if val > 0 else 'grey'
                    return f'color: {color}'
                
                # 更新表格配置
                st.dataframe(
                    annual_finance_df.style.apply(lambda x: x.map(lambda y: style_profit_annual(y) if x.name == '淨損益' else None)),
                    width="stretch", 
                    hide_index=True,
                    # 在 column_order 中加入新的欄位
                    column_order=["宿舍地址", "雇主", "備註", "總收入", "總支出", "淨損益", "租金收入", "每月支出"],
                    column_config={
                        "宿舍地址": st.column_config.TextColumn("宿舍地址", width="medium"),
                        "雇主": st.column_config.TextColumn("雇主", width="medium"),
                        "總收入": st.column_config.NumberColumn("總收入", format="NT$ %d", help="包含工人月費扣款 + 其他雜項收入"),
                        "總支出": st.column_config.NumberColumn("總支出", format="NT$ %d", help="包含合約 + 變動雜費 + 年度攤銷"),
                        "淨損益": st.column_config.NumberColumn("淨損益", format="NT$ %d"),
                        
                        # 新增兩欄的顯示設定
                        "租金收入": st.column_config.TextColumn("租金收入", help="當前在住移工收租明細 (格式：金額:人數(雇主))"),
                        "每月支出": st.column_config.TextColumn("每月支出", help="當前每月固定支出明細（合約／雜費／攤銷）", width="large"),
                        "備註": st.column_config.TextColumn("備註", width="medium"),
                        
                        "長期合約支出": st.column_config.NumberColumn("長期合約支出", format="NT$ %d"),
                        "變動雜費(我司支付)": st.column_config.NumberColumn("變動雜費", format="NT$ %d"),
                        "長期攤銷": st.column_config.NumberColumn("長期攤銷", format="NT$ %d"),
                        "宿舍備註": st.column_config.TextColumn("宿舍備註")
                    }
                )

    # --- 頁籤三：雇主住宿統計---
    with tab3:
        st.subheader("各雇主月度住宿人數統計")
        
        today_emp = datetime.now()
        ec1, ec2, ec3 = st.columns(3)
        
        selected_year_emp = ec1.selectbox("選擇年份", options=range(today_emp.year - 2, today_emp.year + 2), index=2, key="emp_stat_year")
        selected_month_emp = ec2.selectbox("選擇月份", options=range(1, 13), index=today_emp.month - 1, key="emp_stat_month")
        min_headcount = ec3.number_input("最小人數篩選 (>= N)", min_value=0, value=10, step=1, help="只顯示在住人數大於或等於此數字的雇主")
        
        year_month_str_emp = f"{selected_year_emp}-{selected_month_emp:02d}"
        
        @st.cache_data
        def get_emp_counts(period, min_cnt):
            return dashboard_model.get_employer_resident_counts(period, min_cnt)

        if st.button("🔍 查詢雇主統計", key="btn_query_emp_stats"):
            get_emp_counts.clear()

        df_emp_counts = get_emp_counts(year_month_str_emp, min_headcount)
        
        st.markdown("---")
        
        if df_emp_counts.empty:
            st.warning(f"在 {year_month_str_emp} 期間，找不到人數 >= {min_headcount} 的雇主資料。")
        else:
            st.success(f"共找到 {len(df_emp_counts)} 位符合條件的雇主。")
            # st.markdown("##### 人數分佈圖")
            # chart_data = df_emp_counts.set_index("雇主")
            # st.bar_chart(chart_data)
            
            st.markdown("##### 詳細數據表")
            st.dataframe(
                df_emp_counts, 
                width="stretch", 
                hide_index=True,
                column_config={
                    "在住人數": st.column_config.NumberColumn(format="%d 人"),
                }
            )