import streamlit as st
import pandas as pd
from datetime import date, timedelta
from data_models import finance_dashboard_model, dormitory_model

def render():
    st.info("此頁面匯總了所有財務相關模組的詳細資料，並以「宿舍地址」作為主要關聯依據。")

    # --- 1. 全域篩選器 ---
    with st.expander("🔍 篩選條件", expanded=True):
        c1, c2, c3 = st.columns(3)
        
        # 日期篩選
        today = date.today()
        first_day = today.replace(day=1)
        start_date = c1.date_input("開始日期", value=first_day)
        end_date = c2.date_input("結束日期", value=today)
        
        # 宿舍篩選
        all_dorms = dormitory_model.get_dorms_for_selection()
        dorm_options = {d['id']: d['original_address'] for d in all_dorms}
        selected_dorm_ids = c3.multiselect("選擇宿舍 (留空代表全部)", options=list(dorm_options.keys()), format_func=lambda x: dorm_options[x])
        
        if not selected_dorm_ids:
            selected_dorm_ids = None # 傳入 None 代表全選

    if start_date > end_date:
        st.error("開始日期不能晚於結束日期！")
        return

    # --- 2. 準備資料 ---
    # 為了效能，我們在這裡一次呼叫所有需要的資料
    # (Streamlit 的 rerender 機制會確保這裡是最新的)
    
    # 收入類
    df_worker_fees = finance_dashboard_model.get_worker_fee_details(start_date, end_date, selected_dorm_ids)
    df_other_income = finance_dashboard_model.get_other_income_details(start_date, end_date, selected_dorm_ids)
    
    # 支出類
    df_utilities = finance_dashboard_model.get_utility_bills_details(start_date, end_date, selected_dorm_ids)
    df_annual = finance_dashboard_model.get_annual_expenses_details(start_date, end_date, selected_dorm_ids)
    df_leases = finance_dashboard_model.get_lease_contracts(selected_dorm_ids) # 合約通常看當下有效
    df_maintenance = finance_dashboard_model.get_maintenance_details(start_date, end_date, selected_dorm_ids)

    # 計算總額供標題使用
    total_income = df_worker_fees['金額'].sum() + df_other_income['金額'].sum()
    total_expense = df_utilities['金額'].sum() + df_annual['金額'].sum() + df_maintenance['金額'].sum()
    # (合約月租不直接加總到區間支出，因為它是參考性質，除非特別計算區間月份數)

    # --- 3. 顯示分頁 ---
    tab_income, tab_expense = st.tabs([f"📈 收入明細 (${total_income:,})", f"💸 支出明細 (不含租金: ${total_expense:,})"])

    # === 分頁 1: 收入 ===
    with tab_income:
        st.subheader("👥 人員總收租 (FeeHistory)")
        st.caption("來自「費用歷史」的紀錄，包含房租、水電費扣款等。")
        if not df_worker_fees.empty:
            st.dataframe(df_worker_fees, use_container_width=True, hide_index=True)
            st.markdown(f"**小計**: ${df_worker_fees['金額'].sum():,}")
        else:
            st.info("此區間無人員收費紀錄。")
            
        st.markdown("---")
        
        st.subheader("💵 其他收入 (OtherIncome)")
        st.caption("來自「其他收入」與「固定收入生成」的紀錄。")
        if not df_other_income.empty:
            st.dataframe(df_other_income, use_container_width=True, hide_index=True)
            st.markdown(f"**小計**: ${df_other_income['金額'].sum():,}")
        else:
            st.info("此區間無其他收入紀錄。")

    # === 分頁 2: 支出 ===
    with tab_expense:
        st.subheader("⚡ 變動費用 (UtilityBills)")
        st.caption("包含水費、電費等依帳單週期的費用。")
        if not df_utilities.empty:
            st.dataframe(df_utilities, use_container_width=True, hide_index=True)
            st.markdown(f"**小計**: ${df_utilities['金額'].sum():,}")
        else:
            st.info("此區間無變動費用紀錄。")

        st.markdown("---")

        st.subheader("📅 年度費用/攤銷 (AnnualExpenses)")
        st.caption("包含稅金、保險、建物申報等，以支付日期篩選。")
        if not df_annual.empty:
            st.dataframe(df_annual, use_container_width=True, hide_index=True)
            st.markdown(f"**小計**: ${df_annual['金額'].sum():,}")
        else:
            st.info("此區間無年度費用紀錄。")

        st.markdown("---")

        st.subheader("🛠 維修紀錄 (MaintenanceLog)")
        st.caption("列出費用 > 0 的維修紀錄。")
        if not df_maintenance.empty:
            st.dataframe(df_maintenance, use_container_width=True, hide_index=True)
            st.markdown(f"**小計**: ${df_maintenance['金額'].sum():,}")
        else:
            st.info("此區間無維修費用紀錄。")

        st.markdown("---")

        st.subheader("📝 有效租賃合約 (Leases)")
        st.caption("列出目前所有生效中的租賃合約 (僅供參考，不計入上方支出總和)。")
        if not df_leases.empty:
            st.dataframe(df_leases, use_container_width=True, hide_index=True)
            total_monthly_rent = df_leases['月租金額'].sum()
            st.markdown(f"**目前每月應付租金總額**: ${total_monthly_rent:,}")
        else:
            st.info("目前無生效中的合約。")