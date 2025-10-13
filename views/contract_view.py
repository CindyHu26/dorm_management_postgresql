# 檔案路徑: views/contract_view.py

import streamlit as st
import pandas as pd
from data_models import contract_model

def render():
    """渲染「合約總覽」頁面"""
    st.header("合約總覽 (依項目分類)")
    st.info("此頁面用於快速檢視所有宿舍中，屬於同一項目的長期合約，方便進行比較與管理。")

    # 步驟 1: 獲取所有可選的合約項目
    contract_items = contract_model.get_distinct_contract_items()

    if not contract_items:
        st.warning("目前資料庫中沒有任何長期合約可供查詢。")
        return

    # 步驟 2: 建立篩選器
    st.markdown("---")
    selected_item = st.selectbox(
        "請選擇要檢視的合約項目：",
        options=contract_items
    )

    # 步驟 3: 根據選擇的項目，查詢並顯示結果
    if selected_item:
        with st.spinner(f"正在查詢所有「{selected_item}」的合約..."):
            contracts_df = contract_model.get_leases_by_item(selected_item)
        
        st.subheader(f"「{selected_item}」合約列表")
        if contracts_df.empty:
            st.info(f"找不到任何關於「{selected_item}」的合約紀錄。")
        else:
            st.dataframe(
                contracts_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "月費金額": st.column_config.NumberColumn(format="NT$ %d"),
                    "押金": st.column_config.NumberColumn(format="NT$ %d")
                }
            )