# views/operations_analyzer_view.py

import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from data_models import operations_analyzer_model

def render():
    """渲染「營運分析」頁面"""
    
    if st.button("🔄 重新整理所有數據"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")

    # --- 區塊一：房租設定異常偵測 ---
    with st.container(border=True):
        st.subheader("🛠️ 房租設定異常偵測")
        st.info("此工具會自動列出所有目前在住（非掛宿外住），但「月費(房租)」欄位為 0 或尚未設定的員工。")

        @st.cache_data
        def get_zero_rent_workers():
            return operations_analyzer_model.get_workers_with_zero_rent()

        zero_rent_df = get_zero_rent_workers()

        if zero_rent_df.empty:
            st.success("🎉 恭喜！目前所有在住人員皆已設定房租。")
        else:
            st.warning(f"發現 {len(zero_rent_df)} 筆房租設定異常紀錄：")
            st.dataframe(zero_rent_df, hide_index=True, width='stretch')
            
            st.markdown("---")
            st.markdown("##### 批次修正")
            st.write("點擊下方按鈕，系統將會自動查找每位員工所在**宿舍**與所屬**雇主**的其他員工，並將房租更新為該群體中最常見的金額。此費用將從該員工的**入住日**開始生效。")
            
            if st.button("🚀 一鍵修正所有異常房租", type="primary"):
                with st.spinner("正在批次更新中，請稍候..."):
                    updated_count, individual_failures, missing_standard_summary = operations_analyzer_model.batch_update_zero_rent_workers(zero_rent_df)
                
                if updated_count > 0:
                    st.success(f"成功更新 {updated_count} 筆房租紀錄！")

                if missing_standard_summary:
                    st.error("部分紀錄因缺少參照標準而無法自動更新。")
                    st.markdown("原因：系統在以下群體中找不到任何一位已設定非零房租的員工，因此無法決定要更新為多少金額。")
                    st.markdown("**請先至「人員管理」頁面，為下列群體手動設定至少一位員工的正確房租：**")
                    
                    error_messages = []
                    for group, count in missing_standard_summary.items():
                        error_messages.append(f"- {group} (共影響 {count} 人)")
                    st.code("\n".join(error_messages))

                if individual_failures:
                    st.error(f"另有 {len(individual_failures)} 筆紀錄因獨立原因更新失敗：")
                    st.dataframe(pd.DataFrame(individual_failures), hide_index=True, width='stretch')
                
                if updated_count > 0 or individual_failures or missing_standard_summary:
                    st.info("請點擊上方的「重新整理所有數據」按鈕以查看最新狀態。")

    st.markdown("---")

    # --- 區塊二：虧損宿舍營運建議 ---
    with st.container(border=True):
        st.subheader("📉 虧損宿舍營運建議")
        st.info("選擇一個月份，系統將分析該月份我司管理的宿舍中，出現虧損的項目，並提供調整建議。")

        # --- 設定日期選擇器 (預設為2個月前) ---
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
        selected_year = c1.selectbox("選擇年份", options=year_options, index=default_year_index, key="op_loss_year")
        selected_month = c2.selectbox("選擇月份", options=range(1, 13), index=default_month - 1, key="op_loss_month")
        year_month_str = f"{selected_year}-{selected_month:02d}"
        
        @st.cache_data
        def get_loss_analysis(period):
            return operations_analyzer_model.get_loss_making_dorms_analysis(period)

        loss_analysis_df = get_loss_analysis(year_month_str)

        if loss_analysis_df.empty:
            st.success(f"🎉 恭喜！在 {year_month_str}，所有我司管理的宿舍均處於獲利狀態。")
        else:
            st.warning(f"在 {year_month_str} 發現 {len(loss_analysis_df)} 間虧損宿舍，詳情如下：")
            st.dataframe(
                loss_analysis_df,
                hide_index=True,
                width='stretch',
                column_config={
                    "淨損益": st.column_config.NumberColumn(format="$ %d"),
                    "在住人數": st.column_config.NumberColumn(format="%d 人"),
                    "宿舍備註": st.column_config.TextColumn(help="宿舍的特殊備註")
                }
            )