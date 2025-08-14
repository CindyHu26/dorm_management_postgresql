import streamlit as st
import pandas as pd
from data_models import dashboard_model

def render():
    """渲染「儀表板」頁面的所有 Streamlit UI 元件。"""
    st.header("宿舍住宿情況儀表板")
    st.info("此儀表板顯示所有「在住」人員的即時統計數據。")

    if st.button("🔄 重新整理數據"):
        st.cache_data.clear()

    @st.cache_data
    def get_dashboard_data():
        """快取資料庫查詢結果，提升效能。"""
        return dashboard_model.get_dormitory_dashboard_data()

    dashboard_df = get_dashboard_data()

    if dashboard_df is None or dashboard_df.empty:
        st.warning("目前沒有任何在住人員的資料可供統計。")
    else:
        # --- 數據總覽指標 (維持不變) ---
        total_residents = int(dashboard_df['總人數'].sum())
        total_rent = int(dashboard_df['月租金總額'].sum())
        manager_summary = dashboard_df.groupby('主要管理人')['總人數'].sum()
        my_company_residents = int(manager_summary.get('我司', 0))
        employer_residents = int(manager_summary.get('雇主', 0))

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("總在住人數", f"{total_residents} 人")
        col2.metric("我司管理宿舍人數", f"{my_company_residents} 人")
        col3.metric("雇主管理宿舍人數", f"{employer_residents} 人")
        col4.metric("月租金總額 (預估)", f"NT$ {total_rent:,}")
        
        st.markdown("---")

        # --- 數據表格 ---
        st.subheader("各宿舍詳細統計")

        manager_filter = st.selectbox(
            "篩選主要管理人：",
            options=["全部"] + dashboard_df['主要管理人'].unique().tolist()
        )

        if manager_filter != "全部":
            display_df = dashboard_df[dashboard_df['主要管理人'] == manager_filter]
        else:
            display_df = dashboard_df

        # 使用 st.dataframe 來顯示，它會自動呈現所有查詢出來的欄位
        # 因為我們的 SQL 查詢已經移除了 dorm_name 並加入了新欄位，UI會自動同步
        st.dataframe(display_df, use_container_width=True, hide_index=True)