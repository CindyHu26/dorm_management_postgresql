import streamlit as st
import pandas as pd
from data_models import room_assignment_model

def render():
    st.header("未分配房間人員總覽")
    st.info("此頁面自動列出所有目前住在「我司管理」宿舍，但房號為 `[未分配房間]` 的人員。請盡速為他們分配房間。")

    if st.button("🔄 重新整理"):
        st.cache_data.clear()
        st.rerun()

    @st.cache_data
    def get_data():
        return room_assignment_model.get_all_unassigned_workers_global()

    df = get_data()

    if df.empty:
        st.success("🎉 恭喜！目前沒有任何人員滯留在 `[未分配房間]`。")
    else:
        st.warning(f"⚠️ 目前共有 {len(df)} 位人員尚未分配房間：")
        
        # 為了方便查看，我們可以先按宿舍分組統計
        summary = df.groupby('宿舍地址').size().reset_index(name='待分配人數')
        st.markdown("##### 各宿舍待分配人數")
        st.dataframe(summary, hide_index=True)
        
        st.markdown("---")
        st.markdown("##### 詳細名單")
        st.dataframe(
            df, 
            width="stretch", 
            hide_index=True,
            column_config={
                "入住日期": st.column_config.DateColumn(format="YYYY-MM-DD")
            }
        )
        
        st.info("💡 提示：請至 **「房間分配」** 頁面，選擇對應的宿舍來進行分配操作。")