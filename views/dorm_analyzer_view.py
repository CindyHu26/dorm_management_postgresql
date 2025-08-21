import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import dormitory_model, single_dorm_analyzer

def render():
    """渲染「宿舍深度分析」頁面"""
    st.header("宿舍深度分析儀表板")

    # --- 1. 宿舍選擇 ---
    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前沒有「我司管理」的宿舍可供分析。")
        return

    dorm_options = {d['id']: d['original_address'] for d in my_dorms}
    selected_dorm_id = st.selectbox(
        "請選擇要分析的宿舍：",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options.get(x, "未知宿舍")
    )

    if not selected_dorm_id: return
    st.markdown("---")

    # --- 2. 顯示基本資訊 ---
    basic_info = single_dorm_analyzer.get_dorm_basic_info(selected_dorm_id)
    meters_df = single_dorm_analyzer.get_dorm_meters(selected_dorm_id)

    st.subheader(f"基本資訊: {dorm_options[selected_dorm_id]}")
    if basic_info:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("主要管理人", basic_info.get('primary_manager'))
        c2.metric("租金支付方", basic_info.get('rent_payer'))
        c3.metric("水電支付方", basic_info.get('utilities_payer'))
        
        # --- 更安全的格式化方式 ---
        rent_value = basic_info.get('monthly_rent') or 0
        c4.metric("當前月租", f"NT$ {int(rent_value):,}")
        # --- 修改結束 ---

        st.write(f"**租賃合約期間:** {basic_info.get('lease_start_date', 'N/A')} ~ {basic_info.get('lease_end_date', 'N/A')}")

    if not meters_df.empty:
        with st.expander("顯示此宿舍的電水錶號"):
            st.dataframe(meters_df, use_container_width=True, hide_index=True)
            
    st.markdown("---")

    # --- 3. 數據分析區塊 ---
    st.subheader("數據分析")
    
    today = datetime.now()
    sc1, sc2 = st.columns(2)
    selected_year = sc1.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2)
    selected_month = sc2.selectbox("選擇月份", options=range(1, 13), index=today.month - 1)
    year_month_str = f"{selected_year}-{selected_month:02d}"

    # 獲取數據
    resident_data = single_dorm_analyzer.get_resident_summary(selected_dorm_id, year_month_str)
    expense_data_df = single_dorm_analyzer.get_expense_summary(selected_dorm_id, year_month_str)

    # 顯示數據
    st.markdown(f"#### {year_month_str} 住宿人員分析")
    st.metric("總在住人數", f"{resident_data['total_residents']} 人")

    res_c1, res_c2, res_c3 = st.columns(3)
    with res_c1:
        st.markdown("**性別分佈**")
        st.dataframe(resident_data['gender_counts'], use_container_width=True, hide_index=True)
    with res_c2:
        st.markdown("**國籍分佈**")
        st.dataframe(resident_data['nationality_counts'], use_container_width=True, hide_index=True)
    with res_c3:
        st.markdown("**房租簡表**")
        st.dataframe(resident_data['rent_summary'], use_container_width=True, hide_index=True)

    st.markdown(f"#### {year_month_str} 預估支出分析")
    total_expense = int(expense_data_df['金額'].sum())
    st.metric("預估總支出", f"NT$ {total_expense:,}")
    st.dataframe(expense_data_df, use_container_width=True, hide_index=True)

    # --- 4. 【本次新增】在住人員詳細名單 ---
    st.markdown("---")
    st.subheader(f"{year_month_str} 在住人員詳細名單")
    
    # 從後端獲取詳細名單
    resident_details_df = single_dorm_analyzer.get_resident_details_as_df(selected_dorm_id, year_month_str)

    if resident_details_df.empty:
        st.info("此宿舍於該月份沒有在住人員。")
    else:
        st.dataframe(resident_details_df, use_container_width=True, hide_index=True)