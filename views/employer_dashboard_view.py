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
        
        # --- 財務總覽 ---
        st.subheader(f"財務總覽 ({year_month_str})")
        
        @st.cache_data
        def get_finance_summary(employer, period):
            return employer_dashboard_model.get_employer_financial_summary(employer, period)

        finance_summary = get_finance_summary(selected_employer, year_month_str)

        f_col1, f_col2, f_col3 = st.columns(3)
        f_col1.metric("預估總收入 (員工月費)", f"NT$ {finance_summary['total_income']:,}")
        f_col2.metric("預估分攤支出", f"NT$ {finance_summary['total_expense']:,} (開發中)")
        f_col3.metric("預估淨貢獻", f"NT$ {finance_summary['profit_loss']:,}", delta=f"{finance_summary['profit_loss']:,}")

        st.markdown("---")

        # --- 人員詳情 ---
        st.subheader(f"「{selected_employer}」員工住宿詳情")
        
        @st.cache_data
        def get_details(employer):
            return employer_dashboard_model.get_employer_resident_details(employer)

        report_df = get_details(selected_employer)

        if report_df.empty:
            st.info("這位雇主目前沒有任何在住員工的住宿紀錄。")
        else:
            st.dataframe(report_df, use_container_width=True, hide_index=True)