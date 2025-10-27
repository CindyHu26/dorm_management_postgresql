# 檔案路徑: views/reminder_view.py

import streamlit as st
import pandas as pd
from data_models import reminder_model

def render():
    """渲染「智慧提醒」儀表板"""
    st.header("智慧提醒儀表板")
    
    # --- 【核心修改 1】調整滑桿範圍，允許負數 ---
    days_ahead = st.slider(
        "設定提醒範圍（天數）：",
        min_value=-180,  # 允許查詢過去 180 天的過期項目
        max_value=180,
        value=90,        # 預設值不變
        step=30
    )
    
    # --- 【核心修改 2】根據選擇的天數，動態顯示提示文字 ---
    if days_ahead >= 0:
        st.info(f"以下將顯示從【今天】到【未來 {days_ahead} 天內】即將到期的所有項目。")
    else:
        st.error(f"以下將顯示在【過去 {-days_ahead} 天內】已經過期或發生，但可能被忽略的項目。")
    
    if st.button("🔄 重新整理"):
        st.cache_data.clear()
        st.rerun()

    @st.cache_data
    def get_reminders(days):
        return reminder_model.get_upcoming_reminders(days)

    reminders = get_reminders(days_ahead)

    st.markdown("---")

    # --- 合規申報提醒 ---
    st.subheader(f"📜 合規申報 ({len(reminders.get('compliance', []))} 筆)")
    compliance_df = reminders.get('compliance', pd.DataFrame())
    if not compliance_df.empty:
        st.dataframe(compliance_df, width="stretch", hide_index=True)
    else:
        st.success("在指定範圍內，沒有相關的建物或消防申報項目。")       
    st.markdown("---")

    # --- 租賃合約提醒 ---
    st.subheader(f"📄 租賃合約 ({len(reminders.get('leases', []))} 筆)")
    leases_df = reminders.get('leases', pd.DataFrame())
    if not leases_df.empty:
        st.dataframe(leases_df, width="stretch", hide_index=True)
    else:
        st.success("在指定範圍內，沒有相關的租賃合約。")
    st.markdown("---")

    # --- 設備提醒 ---
    st.subheader(f"🧯 設備保養/更換 ({len(reminders.get('equipment', []))} 筆)")
    equipment_df = reminders.get('equipment', pd.DataFrame())
    if not equipment_df.empty:
        st.dataframe(equipment_df, width="stretch", hide_index=True)
    else:
        st.success("在指定範圍內，沒有需要更換或檢查的設備。")     
    st.markdown("---")
    
    # --- 保險提醒 ---
    st.subheader(f"🛡️ 宿舍保險 ({len(reminders.get('insurance', []))} 筆)")
    insurance_df = reminders.get('insurance', pd.DataFrame())
    if not insurance_df.empty:
        st.dataframe(insurance_df, width="stretch", hide_index=True)
    else:
        st.success("在指定範圍內，沒有相關的宿舍保險。")
    st.markdown("---")

# --- 清掃排程提醒 ---
    st.subheader(f"🧹 宿舍清掃排程 ({len(reminders.get('cleaning_schedules', []))} 筆)")
    cleaning_df = reminders.get('cleaning_schedules', pd.DataFrame())
    if not cleaning_df.empty:
        # 將日期字串轉為 date 物件以便格式化
        cleaning_df['下次預計日期'] = pd.to_datetime(cleaning_df['下次預計日期'], errors='coerce').dt.date
        cleaning_df['上次完成日期'] = pd.to_datetime(cleaning_df['上次完成日期'], errors='coerce').dt.date
        st.dataframe(
            cleaning_df,
            width="stretch",
            hide_index=True,
            column_config={
                "下次預計日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "上次完成日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
            }
         )
    else:
        st.success("在指定範圍內，沒有需要執行的清掃排程。")
    st.markdown("---")

    # --- 移工工作期限提醒 ---
    st.subheader(f"🧑‍💼 移工工作期限 ({len(reminders.get('workers', []))} 筆)")
    workers_df = reminders.get('workers', pd.DataFrame())
    if not workers_df.empty:
        st.dataframe(workers_df, width="stretch", hide_index=True)
    else:
        st.success("在指定範圍內，沒有相關的移工工作期限。")

