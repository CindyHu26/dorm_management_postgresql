# views/residency_analyzer_view.py (v1.2 - 新增雇主與歷史篩選)

import streamlit as st
import pandas as pd
from datetime import date
# 【核心修改 1】匯入 employer_dashboard_model
from data_models import residency_analyzer_model, dormitory_model, employer_dashboard_model

def render():
    """渲染「歷史在住查詢」頁面"""
    st.header("歷史在住查詢")
    st.info("您可以透過設定日期區間和宿舍，來查詢過去、現在或未來的住宿人員名單及其費用狀況。")

    # --- 篩選器區塊 ---
    @st.cache_data
    def get_dorms_list():
        return dormitory_model.get_dorms_for_selection()

    @st.cache_data
    def get_employers_list():
        return employer_dashboard_model.get_all_employers()

    dorms = get_dorms_list()
    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms} if dorms else {}
    
    employers_list = get_employers_list()
    if not employers_list:
        st.warning("目前資料庫中沒有任何雇主資料可供篩選。")
        return

    st.markdown("##### 篩選條件")
    c1, c2 = st.columns(2)
    start_date = c1.date_input("查詢起始日", value=date.today())
    end_date = c2.date_input("查詢結束日", value=date.today())
    
    c3, c4 = st.columns(2)
    # 【核心修改 2】新增雇主多選
    selected_employer_names = c3.multiselect(
        "篩選雇主 (可不選，預設為全部)",
        options=employers_list
    )
    selected_dorm_ids = c4.multiselect(
        "篩選宿舍 (可不選，預設為全部)",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options.get(x)
    )
    
    # 【核心修改 3】新增住宿歷史篩選
    min_history_filter = st.checkbox("僅顯示 2 段以上住宿歷史者 (曾換宿/搬遷者)")
    
    if st.button("🔍 開始查詢", type="primary"):
        if start_date > end_date:
            st.error("錯誤：起始日不能晚於結束日！")
        else:
            # 【核心修改 4】將新篩選器加入 filters
            filters = {
                "start_date": start_date,
                "end_date": end_date,
                "dorm_ids": selected_dorm_ids if selected_dorm_ids else None,
                "employer_names": selected_employer_names if selected_employer_names else None,
                "min_history_count": 2 if min_history_filter else None
            }
            with st.spinner("正在查詢中..."):
                # 兩種查詢都會接收到新的 filters
                results_df = residency_analyzer_model.get_residents_for_period(filters)
                new_residents_df = residency_analyzer_model.get_new_residents_for_period(filters)
            
            # ---「期間新增入住人員」區塊 ---
            st.markdown("---")
            st.subheader(f"期間新增入住人員 ({start_date} ~ {end_date})")
            if new_residents_df.empty:
                st.info("此期間內無新增入住人員。")
            else:
                st.success(f"此期間內共有 {len(new_residents_df)} 位新入住人員。")
                st.dataframe(new_residents_df, width='stretch', hide_index=True)

            st.markdown("---")
            st.subheader("住宿總覽")

            if results_df.empty:
                st.warning("在您指定的條件下，查無任何住宿紀錄。")
            else:
                total_records = len(results_df)
                total_fee = results_df['總費用'].sum()

                st.success(f"在 **{start_date}** 至 **{end_date}** 期間，共查詢到 **{total_records}** 筆住宿人次紀錄。")
                
                m1, m2 = st.columns(2)
                m1.metric("總住宿人次", f"{total_records} 人次")
                m2.metric("期間費用總計 (以月費為基礎)", f"NT$ {total_fee:,}")
                
                # 預設顯示的欄位順序
                column_order = [
                    "宿舍地址", "編號", "主要管理人", "負責人", "房號", 
                    "雇主", "姓名", "性別", "國籍", "入住日", "退宿日", "總費用"
                ]
                # 確保只顯示實際存在的欄位
                display_columns = [col for col in column_order if col in results_df.columns]
                st.dataframe(results_df[display_columns], width='stretch', hide_index=True)