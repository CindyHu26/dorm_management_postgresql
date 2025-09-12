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
        st.rerun()

    @st.cache_data
    def get_reminders(days):
        return reminder_model.get_upcoming_reminders(days)

    reminders = get_reminders(days_ahead)

    st.markdown("---")

    # --- 合規申報提醒 ---
    st.subheader(f"📜 即將到期的合規申報 ({len(reminders.get('compliance', []))} 筆)")
    compliance_df = reminders.get('compliance', pd.DataFrame())
    if not compliance_df.empty:
        st.dataframe(compliance_df, width="stretch", hide_index=True)
    else:
        st.success("在指定範圍內，沒有即將到期的建物或消防申報項目。")       
    st.markdown("---")

    # --- 租賃合約提醒 ---
    st.subheader(f"📄 即將到期的租賃合約 ({len(reminders.get('leases', []))} 筆)")
    leases_df = reminders.get('leases', pd.DataFrame())
    if not leases_df.empty:
        st.dataframe(leases_df, width="stretch", hide_index=True)
    else:
        st.success("在指定範圍內，沒有即將到期的租賃合約。")
    st.markdown("---")

    # --- 設備提醒 ---
    st.subheader(f"🧯 即將到期的設備 ({len(reminders.get('equipment', []))} 筆)")
    equipment_df = reminders.get('equipment', pd.DataFrame())
    if not equipment_df.empty:
        st.dataframe(equipment_df, width="stretch", hide_index=True)
    else:
        st.success("在指定範圍內，沒有需要更換或檢查的設備。")     
    st.markdown("---")
    
    # --- 保險提醒 ---
    st.subheader(f"🛡️ 即將到期的宿舍保險 ({len(reminders.get('insurance', []))} 筆)")
    insurance_df = reminders.get('insurance', pd.DataFrame())
    if not insurance_df.empty:
        st.dataframe(insurance_df, width="stretch", hide_index=True)
    else:
        st.success("在指定範圍內，沒有即將到期的宿舍保險。")
    st.markdown("---")

    # --- 移工工作期限提醒 ---
    st.subheader(f"🧑‍💼 即將到期的移工工作期限 ({len(reminders.get('workers', []))} 筆)")
    workers_df = reminders.get('workers', pd.DataFrame())
    if not workers_df.empty:
        st.dataframe(workers_df, width="stretch", hide_index=True)
    else:
        st.success("在指定範圍內，沒有即將到期的移工工作期限。")