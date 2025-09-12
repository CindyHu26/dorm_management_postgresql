import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import loss_analyzer_model

def render():
    """渲染「虧損宿舍分析」頁面"""
    st.header("虧損宿舍分析")
    st.info("此頁面用於快速找出目前處於虧損狀態的我司管理宿舍，並分析其收支結構。")

    if st.button("🔄 重新整理所有數據"):
        st.cache_data.clear()

    st.markdown("---")

    # --- 區塊一：年度虧損總覽 ---
    st.subheader("年度虧損宿舍總覽")
    st.caption("此報表統計在過去一年內，所有收支加總後，淨損益為負數的宿舍。")

    @st.cache_data
    def get_annual_loss_data():
        return loss_analyzer_model.get_loss_making_dorms('annual')

    annual_loss_df = get_annual_loss_data()

    if annual_loss_df.empty:
        st.success("恭喜！在過去一年內，沒有任何宿舍出現整體虧損。")
    else:
        st.warning(f"在過去一年內，共發現 {len(annual_loss_df)} 間宿舍整體呈現虧損：")
        st.dataframe(annual_loss_df, width="stretch", hide_index=True)

    st.markdown("---")

    # --- 區塊二：單月虧損查詢 ---
    st.subheader("單月虧損宿舍查詢")
    st.caption("請選擇一個月份，查詢在該月份淨損益為負數的宿舍。")

    today = datetime.now()
    c1, c2 = st.columns(2)
    selected_year = c1.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2, key="loss_year")
    selected_month = c2.selectbox("選擇月份", options=range(1, 13), index=today.month - 1, key="loss_month")
    year_month_str = f"{selected_year}-{selected_month:02d}"

    @st.cache_data
    def get_monthly_loss_data(period):
        return loss_analyzer_model.get_loss_making_dorms(period)

    monthly_loss_df = get_monthly_loss_data(year_month_str)

    if monthly_loss_df.empty:
        st.success(f"在 {year_month_str}，沒有任何宿舍出現虧損。")
    else:
        st.warning(f"在 {year_month_str}，共發現 {len(monthly_loss_df)} 間宿舍呈現虧損：")
        st.dataframe(monthly_loss_df, width="stretch", hide_index=True)