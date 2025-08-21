import streamlit as st
import pandas as pd
from data_models import reminder_model

def render():
    """渲染「智慧提醒」儀表板"""
    st.header("智慧提醒儀表板")
    
    days_ahead = st.slider(
        "設定提醒範圍（天數）：",
        min_value=30,
        max_value=180,
        value=90, # 預設為90天
        step=30
    )
    st.info(f"以下將顯示在 **{days_ahead} 天內**即將到期的所有項目。")
    
    if st.button("🔄 重新整理"):
        st.cache_data.clear()

    @st.cache_data
    def get_reminders(days):
        return reminder_model.get_upcoming_reminders(days)

    reminders = get_reminders(days_ahead)

    st.markdown("---")

    # --- 租賃合約提醒 ---
    st.subheader(f"📄 即將到期的租賃合約 ({len(reminders['leases'])} 筆)")
    if not reminders['leases'].empty:
        st.dataframe(reminders['leases'], use_container_width=True, hide_index=True)
    else:
        st.success("在指定範圍內，沒有即將到期的租賃合約。")
        
    st.markdown("---")

    # --- 移工工作期限提醒 ---
    st.subheader(f"🧑‍💼 即將到期的移工工作期限 ({len(reminders['workers'])} 筆)")
    if not reminders['workers'].empty:
        st.dataframe(reminders['workers'], use_container_width=True, hide_index=True)
    else:
        st.success("在指定範圍內，沒有即將到期的移工工作期限。")

    st.markdown("---")

    # --- 設備提醒 ---
    st.subheader(f"🧯 即將到期的設備 ({len(reminders['equipment'])} 筆)")
    if not reminders['equipment'].empty:
        st.dataframe(reminders['equipment'], use_container_width=True, hide_index=True)
    else:
        st.success("在指定範圍內，沒有需要更換或檢查的設備。")
        
    st.markdown("---")
    
    # --- 保險提醒 ---
    st.subheader(f"🛡️ 即將到期的宿舍保險 ({len(reminders['insurance'])} 筆)")
    if not reminders['insurance'].empty:
        st.dataframe(reminders['insurance'], use_container_width=True, hide_index=True)
    else:
        st.success("在指定範圍內，沒有即將到期的宿舍保險。")