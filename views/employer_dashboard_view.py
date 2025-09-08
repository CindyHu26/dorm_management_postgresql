# cindyhu26/dorm_management_postgresql/dorm_management_postgresql-40db7a95298be6441da6d9bda99bf22aaaeaa89c/views/employer_dashboard_view.py
import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import employer_dashboard_model

def render():
    """渲染「雇主儀表板」頁面"""
    st.header("雇主視角儀表板")
    st.info("請從下方選擇一位雇主，以檢視其所有在住員工的詳細住宿分佈與財務貢獻情況。")

    # --- 1. 雇主選擇 ---
    @st.cache_data
    def get_employers_list():
        return employer_dashboard_model.get_all_employers()

    employers_list = get_employers_list()
    
    if not employers_list:
        st.warning("目前資料庫中沒有任何員工資料可供查詢。")
        return

    selected_employer = st.selectbox(
        "請選擇要分析的雇主：",
        options=[""] + employers_list,
        format_func=lambda x: "請選擇..." if x == "" else x
    )

    if st.button("🔄 重新整理所有數據"):
        st.cache_data.clear()

    st.markdown("---")

    if selected_employer:
        
        tab1, tab2 = st.tabs(["📊 按月檢視", "📅 年度總覽"])

        with tab1:
            st.subheader("每月財務與住宿分析")
            
            c1, c2 = st.columns(2)
            today = datetime.now()
            selected_year_month = c1.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2, key="monthly_year")
            selected_month_month = c2.selectbox("選擇月份", options=range(1, 13), index=today.month - 1, key="monthly_month")
            year_month_str = f"{selected_year_month}-{selected_month_month:02d}"

            @st.cache_data
            def get_finance_summary(employer, period):
                return employer_dashboard_model.get_employer_financial_summary(employer, period)

            finance_df_month = get_finance_summary(selected_employer, year_month_str)

            if finance_df_month.empty:
                st.warning(f"在 {year_month_str} 中，找不到與此雇主相關的任何收支紀錄。")
            else:
                st.markdown(f"#### {year_month_str} 財務總覽")
                finance_df_month['總收入'] = finance_df_month['收入(員工月費)'] + finance_df_month['分攤其他收入']
                total_income = finance_df_month['總收入'].sum()
                total_expense_by_us = finance_df_month['我司分攤月租'].sum() + finance_df_month['我司分攤雜費'].sum() + finance_df_month['我司分攤攤銷'].sum()
                profit_loss = total_income - total_expense_by_us

                f_col1, f_col2, f_col3 = st.columns(3)
                f_col1.metric("預估總收入", f"NT$ {total_income:,.0f}", help="總收入 = 員工月費 + 分攤的其他收入")
                f_col2.metric("預估我司分攤總支出", f"NT$ {total_expense_by_us:,.0f}")
                f_col3.metric("預估淨貢獻", f"NT$ {profit_loss:,.0f}", delta=f"{profit_loss:,.0f}")

                st.markdown("##### 各宿舍收支詳情 (此雇主)")
                display_df = finance_df_month.copy()
                display_df['淨損益'] = (display_df['收入(員工月費)'] + display_df['分攤其他收入']) - \
                                    (display_df['我司分攤月租'] + display_df['我司分攤雜費'] + display_df['我司分攤攤銷'])
                
                # --- 【核心修改點】---
                # 重新定義要顯示的欄位，直接展示所有細項
                cols_to_display = [
                    "宿舍地址", "淨損益", "收入(員工月費)", "分攤其他收入", 
                    "我司分攤月租", "我司分攤雜費", "我司分攤攤銷"
                ]
                
                # 篩選出存在的欄位來顯示，避免錯誤
                cols_to_display_exist = [col for col in cols_to_display if col in display_df.columns]
                
                st.dataframe(display_df[cols_to_display_exist], use_container_width=True, hide_index=True,
                    column_config={col: st.column_config.NumberColumn(format="NT$ %d") for col in cols_to_display_exist if col != "宿舍地址"})

        with tab2:
            st.subheader("年度財務總覽")
            
            today = datetime.now()
            selected_year_annual = st.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2, key="annual_year")

            @st.cache_data
            def get_finance_summary_annual(employer, year):
                return employer_dashboard_model.get_employer_financial_summary_annual(employer, year)

            finance_df_annual = get_finance_summary_annual(selected_employer, selected_year_annual)

            if finance_df_annual.empty:
                st.warning(f"在 {selected_year_annual} 年中，找不到與此雇主相關的任何收支紀錄。")
            else:
                st.markdown(f"#### {selected_year_annual} 年度財務總覽")
                finance_df_annual['總收入'] = finance_df_annual['收入(員工月費)'] + finance_df_annual['分攤其他收入']
                total_income_annual = finance_df_annual['總收入'].sum()
                total_expense_by_us_annual = finance_df_annual['我司分攤月租'].sum() + finance_df_annual['我司分攤雜費'].sum() + finance_df_annual['我司分攤攤銷'].sum()
                profit_loss_annual = total_income_annual - total_expense_by_us_annual

                fa_col1, fa_col2, fa_col3 = st.columns(3)
                fa_col1.metric("年度總收入", f"NT$ {total_income_annual:,.0f}", help="總收入 = 員工月費 + 分攤的其他收入")
                fa_col2.metric("年度我司分攤總支出", f"NT$ {total_expense_by_us_annual:,.0f}")
                fa_col3.metric("年度淨貢獻", f"NT$ {profit_loss_annual:,.0f}", delta=f"{profit_loss_annual:,.0f}")

                st.markdown("##### 各宿舍年度收支詳情 (此雇主)")
                display_df_annual = finance_df_annual.copy()
                display_df_annual['淨損益'] = (display_df_annual['收入(員工月費)'] + display_df_annual['分攤其他收入']) - \
                                            (display_df_annual['我司分攤月租'] + display_df_annual['我司分攤雜費'] + display_df_annual['我司分攤攤銷'])
                
                # --- 【核心修改點】---
                # 同樣為年度總覽定義要顯示的細項欄位
                cols_to_display_annual = [
                    "宿舍地址", "淨損益", "收入(員工月費)", "分攤其他收入", 
                    "我司分攤月租", "我司分攤雜費", "我司分攤攤銷"
                ]
                
                cols_to_display_annual_exist = [col for col in cols_to_display_annual if col in display_df_annual.columns]

                st.dataframe(display_df_annual[cols_to_display_annual_exist], use_container_width=True, hide_index=True,
                    column_config={col: st.column_config.NumberColumn(format="NT$ %d") for col in cols_to_display_annual_exist if col != "宿舍地址"})

        st.markdown("---")
        st.subheader("各宿舍即時住宿分佈")
        @st.cache_data
        def get_details(employer):
            return employer_dashboard_model.get_employer_resident_details(employer)

        report_df = get_details(selected_employer)
        if report_df.empty:
            st.info("這位雇主目前沒有任何在住員工的住宿紀錄。")
        else:
            total_workers = len(report_df)
            my_company_managed_count = len(report_df[report_df['主要管理人'] == '我司'])
            
            s_col1, s_col2 = st.columns(2)
            s_col1.metric("該雇主總在住員工數", f"{total_workers} 人")
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
            st.dataframe(dorm_summary_df, use_container_width=True, hide_index=True)
            
            with st.expander("點此查看員工住宿詳情"):
                st.dataframe(report_df, use_container_width=True, hide_index=True)