# 檔案路徑: views/employer_dashboard_view.py

import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from data_models import employer_dashboard_model, dormitory_model

def render():
    """渲染「雇主儀表板」頁面"""
    st.header("雇主視角儀表板")
    st.info("請從下方選擇一位或多位雇主，以檢視其所有在住員工的詳細住宿分佈與財務貢獻情況。")

    @st.cache_data
    def get_employers_list():
        return employer_dashboard_model.get_all_employers()

    employers_list = get_employers_list()
    
    if not employers_list:
        st.warning("目前資料庫中沒有任何員工資料可供查詢。")
        return

    selected_employers = st.multiselect(
        "請選擇要分析的雇主 (可多選)：",
        options=employers_list
    )

    if st.button("🔄 重新整理所有數據"):
        st.cache_data.clear()

    st.markdown("---")

    if selected_employers:
        
        @st.cache_data
        def get_dorm_id_map():
            all_dorms = dormitory_model.get_dorms_for_selection()
            return {d['original_address']: d['id'] for d in all_dorms}
        dorm_id_map = get_dorm_id_map()

        tab1, tab2 = st.tabs(["📊 按月檢視", "📅 年度總覽"])

        with tab1:
            st.subheader("每月財務與住宿分析")
            
            # --- 【核心修改】預設選取 2 個月前 ---
            today = datetime.now()
            default_date = today - relativedelta(months=2)
            default_year = default_date.year
            default_month = default_date.month
            
            year_options = list(range(today.year - 2, today.year + 2))
            try:
                default_year_index = year_options.index(default_year)
            except ValueError:
                default_year_index = 2

            c1, c2 = st.columns(2)
            selected_year_month = c1.selectbox("選擇年份", options=year_options, index=default_year_index, key="monthly_year")
            selected_month_month = c2.selectbox("選擇月份", options=range(1, 13), index=default_month - 1, key="monthly_month")
            year_month_str = f"{selected_year_month}-{selected_month_month:02d}"

            @st.cache_data
            def get_finance_summary(employers, period):
                return employer_dashboard_model.get_employer_financial_summary(employers, period)
            
            finance_df_month = get_finance_summary(selected_employers, year_month_str)

            @st.cache_data
            def get_details_for_period(employers, period):
                # 呼叫修改後的函數，傳入年月
                return employer_dashboard_model.get_employer_resident_details(employers, period)

            report_df_month = get_details_for_period(selected_employers, year_month_str)

            if finance_df_month.empty:
                st.warning(f"在 {year_month_str} 中，找不到與所選雇主相關的任何收支紀錄。")
            else:
                st.markdown(f"#### {year_month_str} 財務總覽")
                finance_df_month['總收入'] = finance_df_month['收入(員工月費)'] + finance_df_month['分攤其他收入']
                total_income = finance_df_month['總收入'].sum()
                
                total_expense_by_us = finance_df_month['我司分攤合約費'].sum() + finance_df_month['我司分攤雜費'].sum() + finance_df_month['我司分攤攤銷'].sum()
                profit_loss = total_income - total_expense_by_us

                f_col1, f_col2, f_col3 = st.columns(3)
                f_col1.metric("總收入", f"NT$ {total_income:,.0f}", help="總收入 = 員工月費 + 分攤的其他收入")
                f_col2.metric("我司分攤總支出", f"NT$ {total_expense_by_us:,.0f}")
                f_col3.metric("淨貢獻", f"NT$ {profit_loss:,.0f}", delta=f"{profit_loss:,.0f}")

                st.markdown("##### 各宿舍收支詳情 (所選雇主)")
                display_df = finance_df_month.copy()
                display_df['淨損益'] = (display_df['收入(員工月費)'] + display_df['分攤其他收入']) - \
                                    (display_df['我司分攤合約費'] + display_df['我司分攤雜費'] + display_df['我司分攤攤銷'])
                
                cols_to_display = ["宿舍地址", "淨損益", "收入(員工月費)", "分攤其他收入", "我司分攤合約費", "我司分攤雜費", "我司分攤攤銷"]
                cols_to_display_exist = [col for col in cols_to_display if col in display_df.columns]
                
                st.dataframe(display_df[cols_to_display_exist], width='stretch', hide_index=True,
                    column_config={col: st.column_config.NumberColumn(format="NT$ %d") for col in cols_to_display_exist if col != "宿舍地址"})

                st.markdown("---")
                st.markdown("##### 查看單一宿舍財務細項")
                
                dorm_options = ["請選擇..."] + list(display_df['宿舍地址'].unique())
                selected_dorm_address = st.selectbox("選擇要查看詳情的宿舍：", options=dorm_options, key="monthly_detail_select")

                if selected_dorm_address and selected_dorm_address != "請選擇...":
                    selected_dorm_id = dorm_id_map.get(selected_dorm_address)
                    if selected_dorm_id:
                        with st.spinner(f"正在查詢 {selected_dorm_address} 的詳細資料..."):
                            income_details, expense_details = employer_dashboard_model.get_employer_financial_details_for_dorm(
                                selected_employers, selected_dorm_id, year_month_str
                            )
                        
                        st.markdown(f"**收入明細**")
                        if income_details is None or income_details.empty:
                            st.info("無收入明細資料。")
                        else:
                            st.dataframe(income_details, width='stretch', hide_index=True)

                        st.markdown(f"**支出明細 (我司分攤後)**")
                        if expense_details is None or expense_details.empty:
                            st.info("無支出明細資料。")
                        else:
                            st.dataframe(expense_details, width='stretch', hide_index=True)

        with tab2:
            st.subheader("年度財務總覽")
            
            today_annual = datetime.now()
            selected_year_annual = st.selectbox("選擇年份", options=range(today_annual.year - 2, today_annual.year + 2), index=2, key="annual_year")

            # --- 【核心修正 7】更新函式名稱 ---
            @st.cache_data
            def get_finance_summary_annual(employers, year):
                return employer_dashboard_model.get_employer_financial_summary_annual(employers, year)

            finance_df_annual = get_finance_summary_annual(selected_employers, selected_year_annual)

            if finance_df_annual.empty:
                st.warning(f"在 {selected_year_annual} 年中，找不到與所選雇主相關的任何收支紀錄。")
            else:
                st.markdown(f"#### {selected_year_annual} 年度財務總覽")
                finance_df_annual['總收入'] = finance_df_annual['收入(員工月費)'] + finance_df_annual['分攤其他收入']
                total_income_annual = finance_df_annual['總收入'].sum()
                
                total_expense_by_us_annual = finance_df_annual['我司分攤合約費'].sum() + finance_df_annual['我司分攤雜費'].sum() + finance_df_annual['我司分攤攤銷'].sum()
                profit_loss_annual = total_income_annual - total_expense_by_us_annual

                fa_col1, fa_col2, fa_col3 = st.columns(3)
                fa_col1.metric("年度總收入", f"NT$ {total_income_annual:,.0f}", help="總收入 = 員工月費 + 分攤的其他收入")
                fa_col2.metric("年度我司分攤總支出", f"NT$ {total_expense_by_us_annual:,.0f}")
                fa_col3.metric("年度淨貢獻", f"NT$ {profit_loss_annual:,.0f}", delta=f"{profit_loss_annual:,.0f}")

                st.markdown("##### 各宿舍年度收支詳情 (所選雇主)")
                display_df_annual = finance_df_annual.copy()
                display_df_annual['淨損益'] = (display_df_annual['收入(員工月費)'] + display_df_annual['分攤其他收入']) - \
                                            (display_df_annual['我司分攤合約費'] + display_df_annual['我司分攤雜費'] + display_df_annual['我司分攤攤銷'])
                
                cols_to_display_annual = [
                    "宿舍地址", "淨損益", "收入(員工月費)", "分攤其他收入", 
                    "我司分攤合約費", "我司分攤雜費", "我司分攤攤銷"
                ]
                
                cols_to_display_annual_exist = [col for col in cols_to_display_annual if col in display_df_annual.columns]

                st.dataframe(display_df_annual[cols_to_display_annual_exist], width='stretch', hide_index=True,
                    column_config={col: st.column_config.NumberColumn(format="NT$ %d") for col in cols_to_display_annual_exist if col != "宿舍地址"})
                
                st.markdown("---")
                st.markdown("##### 查看單一宿舍年度財務細項")
                
                dorm_options_annual = ["請選擇..."] + list(display_df_annual['宿舍地址'].unique())
                selected_dorm_address_annual = st.selectbox("選擇要查看詳情的宿舍：", options=dorm_options_annual, key="annual_detail_select")

                if selected_dorm_address_annual and selected_dorm_address_annual != "請選擇...":
                    selected_dorm_id_annual = dorm_id_map.get(selected_dorm_address_annual)
                    if selected_dorm_id_annual:
                        with st.spinner(f"正在查詢 {selected_dorm_address_annual} 的詳細資料..."):
                             income_details_annual, expense_details_annual = employer_dashboard_model.get_employer_financial_details_for_dorm(
                                selected_employers, selected_dorm_id_annual, str(selected_year_annual)
                            )
                        
                        st.markdown(f"**年度收入明細**")
                        if income_details_annual is None or income_details_annual.empty:
                            st.info("無收入明細資料。")
                        else:
                            st.dataframe(income_details_annual, width='stretch', hide_index=True)

                        st.markdown(f"**年度支出明細 (我司分攤後)**")
                        if expense_details_annual is None or expense_details_annual.empty:
                            st.info("無支出明細資料。")
                        else:
                            st.dataframe(expense_details_annual, width='stretch', hide_index=True)
        
        st.markdown("---")
        st.subheader("各宿舍即時住宿分佈")
        @st.cache_data
        def get_details(employers):
            return employer_dashboard_model.get_employer_resident_details(employers)

        report_df = get_details(selected_employers)
        if report_df.empty:
            st.info("所選雇主目前沒有任何在住員工的住宿紀錄。")
        else:
            total_workers = len(report_df)
            my_company_managed_count = len(report_df[report_df['主要管理人'] == '我司'])
            
            s_col1, s_col2 = st.columns(2)
            s_col1.metric("所選雇主總在住員工數", f"{total_workers} 人")
            s_col2.metric("住在我司管理宿舍人數", f"{my_company_managed_count} 人")

            grouped = report_df.groupby(['宿舍地址', '主要管理人'])
            summary_df = grouped.agg(
                總人數=('姓名', 'count'),
                男性人數=('性別', lambda s: (s == '男').sum()),
                女性人數=('性別', lambda s: (s == '女').sum())
            )
            def create_distribution_string(series):
                series = series.dropna()
                if series.empty: return ""
                return ", ".join([f"{item}:{count}" for item, count in series.value_counts().items()])
            def create_status_string(series):
                series = series.dropna()[series.str.strip() != '']
                if series.empty: return ""
                return ", ".join([f"{item}:{count}人" for item, count in series.value_counts().items()])
            nationality_df = grouped['國籍'].apply(create_distribution_string).rename('國籍分佈')
            status_df = grouped['特殊狀況'].apply(create_status_string).rename('特殊狀況總計')
            dorm_summary_df = pd.concat([summary_df, nationality_df, status_df], axis=1).reset_index()
            st.dataframe(dorm_summary_df, width='stretch', hide_index=True)
            
            with st.expander("點此查看員工住宿詳情"):
                # 1. 定義要顯示的欄位 (移除 "主要管理人", 加入 "入住日", "離住日")
                columns_to_show = [
                    "宿舍地址", "房號", "姓名", "性別", "國籍", 
                    "入住日", "離住日", "員工月費", "特殊狀況", "雇主"
                ]

                # 2. 確保只選取 DataFrame 中實際存在的欄位
                existing_columns = [col for col in columns_to_show if col in report_df_month.columns]

                # 3. 顯示指定的 DataFrame，並設定日期格式
                st.dataframe(
                    report_df_month[existing_columns],  # <-- 只顯示指定欄位
                    width='stretch', 
                    hide_index=True,
                    column_config={
                        "員工月費": st.column_config.NumberColumn(format="NT$ %d"),
                        "入住日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                        "離住日": st.column_config.DateColumn(format="YYYY-MM-DD")
                    }
                )