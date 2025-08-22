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
        
        # --- 獲取數據 ---
        @st.cache_data
        def get_details(employer):
            return employer_dashboard_model.get_employer_resident_details(employer)

        report_df = get_details(selected_employer)

        if report_df.empty:
            st.info("這位雇主目前沒有任何在住員工的住宿紀錄。")
        else:
            # --- 財務總覽 (維持不變) ---
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

            # --- 各宿舍住宿分佈總覽 (大幅升級) ---
            st.subheader("各宿舍住宿分佈總覽")

            # --- 在總覽上方增加指標 ---
            total_workers = len(report_df)
            my_company_managed_count = len(report_df[report_df['主要管理人'] == '我司'])
            
            s_col1, s_col2 = st.columns(2)
            s_col1.metric("該雇主總在住員工數", f"{total_workers} 人")
            s_col2.metric("住在我司管理宿舍人數", f"{my_company_managed_count} 人")

            # --- 為聚合函式增加特殊狀況的計算 ---
            def aggregate_dorm_data(group):
                # 篩選出有內容的特殊狀況
                special_status = group['特殊狀況'].dropna()
                status_counts = special_status[special_status != ''].value_counts()
                
                agg_data = {
                    '總人數': group['姓名'].count(),
                    '男性人數': (group['性別'] == '男').sum(),
                    '女性人數': (group['性別'] == '女').sum(),
                    '國籍分佈': ", ".join([f"{nat}:{count}" for nat, count in group['國籍'].value_counts().items()]),
                    '特殊狀況總計': ", ".join([f"{status}:{count}人" for status, count in status_counts.items()])
                }
                return pd.Series(agg_data)

            dorm_summary_df = report_df.groupby(['宿舍地址', '主要管理人']).apply(aggregate_dorm_data).reset_index()

            st.dataframe(dorm_summary_df, use_container_width=True, hide_index=True)
            
            st.markdown("---")

            # --- 人員詳情列表 ---
            st.subheader(f"「{selected_employer}」員工住宿詳情")
            st.dataframe(report_df, use_container_width=True, hide_index=True)