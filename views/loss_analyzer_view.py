import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from data_models import loss_analyzer_model

def render():
    """渲染「虧損宿舍分析」頁面"""
    st.info("此頁面用於快速找出目前處於虧損狀態的我司管理宿舍，並分析其收支結構。")

    if st.button("🔄 重新整理所有數據"):
        st.cache_data.clear()

    st.markdown("---")

    # --- 新增頁籤 ---
    tab1, tab2 = st.tabs(["📊 日常營運分析", "💰 完整財務分析 (含攤銷)"])

    # --- 頁籤一：日常營運分析 (新功能) ---
    with tab1:
        st.subheader("年度日常營運虧損總覽")
        st.caption("【僅計算日常現金流】此報表統計過去一年內，僅考慮「員工收入」與「房東月租、變動雜費」後，淨損益為負數的宿舍。")

        @st.cache_data
        def get_daily_annual_loss_data():
            # 呼叫我們新增的函式
            return loss_analyzer_model.get_daily_loss_making_dorms('annual')

        daily_annual_loss_df = get_daily_annual_loss_data()

        if daily_annual_loss_df.empty:
            st.success("恭喜！在過去一年內，沒有任何宿舍出現日常營運虧損。")
        else:
            st.warning(f"在過去一年內，共發現 {len(daily_annual_loss_df)} 間宿舍日常營運呈現虧損：")
            st.dataframe(daily_annual_loss_df, width="stretch", hide_index=True)

        st.markdown("---")

        st.subheader("單月日常營運虧損查詢")
        st.caption("【僅計算日常現金流】請選擇一個月份，查詢在該月份淨損益為負數的宿舍。")

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
        selected_year_daily = c1.selectbox("選擇年份", options=year_options, index=default_year_index, key="daily_loss_year")
        selected_month_daily = c2.selectbox("選擇月份", options=range(1, 13), index=default_month - 1, key="daily_loss_month")
        year_month_str_daily = f"{selected_year_daily}-{selected_month_daily:02d}"

        @st.cache_data
        def get_daily_monthly_loss_data(period):
            # 呼叫我們新增的函式
            return loss_analyzer_model.get_daily_loss_making_dorms(period)

        # --- 區塊內修改 column_config ---
        daily_monthly_loss_df = get_daily_monthly_loss_data(year_month_str_daily)

        if daily_monthly_loss_df.empty:
            st.success(f"在 {year_month_str_daily}，沒有任何宿舍出現日常營運虧損。")
        else:
            st.warning(f"在 {year_month_str_daily}，共發現 {len(daily_monthly_loss_df)} 間宿舍日常營運呈現虧損：")
            st.dataframe(
                daily_monthly_loss_df, 
                width="stretch", 
                hide_index=True,
                column_config={
                    "年度總收入": st.column_config.NumberColumn("總收入", format="$%d"), # 名稱雖為年度，實為該期間
                    "年度總支出": st.column_config.NumberColumn("總支出", format="$%d"),
                    "淨損益": st.column_config.NumberColumn(format="$%d"),
                    "宿舍備註": st.column_config.TextColumn("備註 (潛在收入/提醒)", help="此欄位顯示宿舍的基本資料備註，可用於註記特殊收入管道。")
                }
            )

    # --- 頁籤二：完整財務分析 (原始功能) ---
    with tab2:
        st.subheader("年度完整財務虧損總覽")
        st.caption("【包含長期攤銷】此報表統計在過去一年內，所有收支加總後，淨損益為負數的宿舍。")

        @st.cache_data
        def get_annual_loss_data():
            # 呼叫原始的函式
            return loss_analyzer_model.get_loss_making_dorms('annual')

        annual_loss_df = get_annual_loss_data()

        if annual_loss_df.empty:
            st.success("恭喜！在過去一年內，沒有任何宿舍出現整體財務虧損。")
        else:
            st.warning(f"在過去一年內，共發現 {len(annual_loss_df)} 間宿舍整體呈現虧損：")
            st.dataframe(annual_loss_df, width="stretch", hide_index=True)

        st.markdown("---")

        st.subheader("單月完整財務虧損查詢")
        st.caption("【包含長期攤銷】請選擇一個月份，查詢在該月份淨損益為負數的宿舍。")

        today_full = datetime.now()
        default_date_full = today_full - relativedelta(months=2)
        default_year_full = default_date_full.year
        default_month_full = default_date_full.month
        
        year_options_full = list(range(today_full.year - 2, today_full.year + 2))
        try:
            default_year_index_full = year_options_full.index(default_year_full)
        except ValueError:
            default_year_index_full = 2

        c1_full, c2_full = st.columns(2)
        selected_year_full = c1_full.selectbox("選擇年份", options=year_options_full, index=default_year_index_full, key="full_loss_year")
        selected_month_full = c2_full.selectbox("選擇月份", options=range(1, 13), index=default_month_full - 1, key="full_loss_month")
        year_month_str_full = f"{selected_year_full}-{selected_month_full:02d}"

        @st.cache_data
        def get_monthly_loss_data(period):
            # 呼叫原始的函式
            return loss_analyzer_model.get_loss_making_dorms(period)

        monthly_loss_df = get_monthly_loss_data(year_month_str_full)

        if monthly_loss_df.empty:
            st.success(f"在 {year_month_str_full}，沒有任何宿舍出現完整財務虧損。")
        else:
            st.warning(f"在 {year_month_str_full}，共發現 {len(monthly_loss_df)} 間宿舍呈現虧損：")
            st.dataframe(monthly_loss_df, width="stretch", hide_index=True)