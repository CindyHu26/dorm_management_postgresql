import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import employer_dashboard_model

def render():
    """渲染「雇主儀表板」頁面"""
    st.header("雇主視角儀表板")
    st.info("請從下方選擇一位雇主，以檢視其所有在住員工的詳細住宿分佈與財務貢獻情況。")

    # --- 1. 雇主與月份選擇 ---
    @st.cache_data
    def get_employers_list():
        return employer_dashboard_model.get_all_employers()

    employers_list = get_employers_list()
    
    if not employers_list:
        st.warning("目前資料庫中沒有任何員工資料可供查詢。")
        return

    c1, c2 = st.columns([2,1])
    selected_employer = c1.selectbox(
        "請選擇要分析的雇主：",
        options=[""] + employers_list,
        format_func=lambda x: "請選擇..." if x == "" else x
    )
    
    today = datetime.now()
    selected_year = c2.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2)
    selected_month = c2.selectbox("選擇月份", options=range(1, 13), index=today.month - 1)
    year_month_str = f"{selected_year}-{selected_month:02d}"

    if st.button("🔄 重新整理數據"):
        st.cache_data.clear()

    st.markdown("---")

    # --- 2. 顯示結果 ---
    if selected_employer:
        
        @st.cache_data
        def get_details(employer):
            return employer_dashboard_model.get_employer_resident_details(employer)
        
        @st.cache_data
        def get_finance_summary(employer, period):
            return employer_dashboard_model.get_employer_financial_summary(employer, period)

        report_df = get_details(selected_employer)
        finance_df = get_finance_summary(selected_employer, year_month_str)

        if report_df.empty:
            st.info("這位雇主目前沒有任何在住員工的住宿紀錄。")
        else:
            st.subheader(f"財務總覽 ({year_month_str})")
            
            if finance_df.empty:
                st.warning("在選定月份中，找不到與此雇主相關的任何收支紀錄。")
            else:
                finance_df['總收入'] = finance_df['收入(員工月費)'] + finance_df['分攤其他收入']
                total_income = finance_df['總收入'].sum()
                total_expense_by_us = finance_df['我司分攤月租'].sum() + finance_df['我司分攤雜費'].sum() + finance_df['我司分攤攤銷'].sum()
                profit_loss = total_income - total_expense_by_us

                f_col1, f_col2, f_col3 = st.columns(3)
                f_col1.metric("預估總收入", f"NT$ {total_income:,.0f}", help="總收入 = 員工月費 + 分攤的其他收入")
                f_col2.metric("預估我司分攤總支出", f"NT$ {total_expense_by_us:,.0f}")
                f_col3.metric("預估淨貢獻", f"NT$ {profit_loss:,.0f}", delta=f"{profit_loss:,.0f}")

                st.markdown("##### 各宿舍收支詳情 (此雇主)")
                display_df = finance_df.copy()
                display_df['我司總支出'] = display_df['我司分攤月租'] + display_df['我司分攤雜費'] + display_df['我司分攤攤銷']
                display_df['雇主總支出'] = display_df['雇主分攤月租'] + display_df['雇主分攤雜費']
                display_df['工人總支出'] = display_df['工人分攤月租'] + display_df['工人分攤雜費']
                display_df['淨損益'] = display_df['總收入'] - display_df['我司總支出']
                display_df = display_df.sort_values(by="我司總支出", ascending=False)
                
                cols_to_display = [
                    "宿舍地址", "總收入", "收入(員工月費)", "分攤其他收入", "我司總支出",
                    "雇主總支出", "工人總支出", "淨損益"
                ]
                st.dataframe(display_df[cols_to_display], use_container_width=True, hide_index=True)

            st.markdown("---")

            # --- 各宿舍住宿分佈總覽 (維持不變) ---
            st.subheader("各宿舍住宿分佈總覽")
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
            
            st.markdown("---")

            # --- 人員詳情列表  ---
            st.subheader(f"「{selected_employer}」員工住宿詳情")
            st.dataframe(report_df, use_container_width=True, hide_index=True)