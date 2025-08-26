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
            f_col2.metric("預估分攤總支出", f"NT$ {finance_summary['total_expense']:,}")
            f_col3.metric("預估淨貢獻", f"NT$ {finance_summary['profit_loss']:,}", delta=f"{finance_summary['profit_loss']:,}")

            with st.expander("查看支出細項 (按人數比例分攤)"):
                st.dataframe(pd.DataFrame(list(finance_summary['details'].items()), columns=['費用項目', '分攤金額']), use_container_width=True, hide_index=True)

            st.markdown("---")

            # --- 各宿舍住宿分佈總覽---
            st.subheader("各宿舍住宿分佈總覽")

            # --- 在總覽上方增加指標 ---
            total_workers = len(report_df)
            my_company_managed_count = len(report_df[report_df['主要管理人'] == '我司'])
            
            s_col1, s_col2 = st.columns(2)
            s_col1.metric("該雇主總在住員工數", f"{total_workers} 人")
            s_col2.metric("住在我司管理宿舍人數", f"{my_company_managed_count} 人")

            # 舊的寫法已移除，改用以下更穩定的方式來產生 dorm_summary_df

            # 1. 將資料按所需欄位分組
            grouped = report_df.groupby(['宿舍地址', '主要管理人'])

            # 2. 使用 .agg() 進行高效率的數值統計
            summary_df = grouped.agg(
                總人數=('姓名', 'count'),
                男性人數=('性別', lambda s: (s == '男').sum()),
                女性人數=('性別', lambda s: (s == '女').sum())
            )

            # 3. 針對需要複雜處理的文字欄位，獨立使用 .apply()
            def create_distribution_string(series):
                """一個通用的輔助函式，用來產生像 "越南:5, 印尼:2" 這樣的字串"""
                series = series.dropna()
                if series.empty:
                    return ""
                return ", ".join([f"{item}:{count}" for item, count in series.value_counts().items()])

            def create_status_string(series):
                """處理特殊狀況，並加上 "人" 的後綴"""
                series = series.dropna()[series.str.strip() != '']
                if series.empty:
                    return ""
                return ", ".join([f"{item}:{count}人" for item, count in series.value_counts().items()])

            nationality_df = grouped['國籍'].apply(create_distribution_string).rename('國籍分佈')
            status_df = grouped['特殊狀況'].apply(create_status_string).rename('特殊狀況總計')
            
            # 4. 將所有結果合併成最終的 DataFrame
            dorm_summary_df = pd.concat([summary_df, nationality_df, status_df], axis=1).reset_index()

            st.dataframe(dorm_summary_df, use_container_width=True, hide_index=True)
            
            st.markdown("---")

            # --- 人員詳情列表 ---
            st.subheader(f"「{selected_employer}」員工住宿詳情")
            st.dataframe(report_df, use_container_width=True, hide_index=True)