import streamlit as st
import pandas as pd
from data_models import room_assignment_model

def render():
    st.info("此頁面自動列出所有目前住在「我司管理」宿舍，但房號為 `[未分配房間]` 的人員。請盡速為他們分配房間。")

    if st.button("🔄 重新整理"):
        st.cache_data.clear()
        st.rerun()

    @st.cache_data
    def get_data():
        # 後端已預設只查詢 '我司' 管理的宿舍
        return room_assignment_model.get_all_unassigned_workers_global()

    df = get_data()

    if df.empty:
        st.success("🎉 恭喜！目前沒有任何人員滯留在 `[未分配房間]`。")
    else:
        # --- 【核心修改】雙重篩選器區塊 ---
        st.subheader("🔍 篩選條件")
        
        # 1. 準備選項 (從現有資料中提取)
        all_dorms = sorted(df['宿舍地址'].unique().tolist())
        all_employers = sorted(df['雇主'].unique().tolist())
        
        c1, c2 = st.columns(2)
        
        # 2. 宿舍篩選 (預設全選)
        selected_dorms = c1.multiselect(
            "篩選宿舍地址",
            options=all_dorms,
            default=all_dorms, 
            placeholder="請選擇宿舍..."
        )
        
        # 3. 雇主篩選 (預設全選)
        selected_employers = c2.multiselect(
            "篩選雇主",
            options=all_employers,
            default=all_employers, 
            placeholder="請選擇雇主..."
        )
        
        # 4. 執行過濾 (兩個條件都必須成立)
        if selected_dorms and selected_employers:
            filtered_df = df[
                (df['宿舍地址'].isin(selected_dorms)) & 
                (df['雇主'].isin(selected_employers))
            ]
        else:
            # 如果任一邊被清空，則顯示空表 (邏輯：且)
            filtered_df = pd.DataFrame(columns=df.columns)
        # --------------------------------

        if not filtered_df.empty:
            st.warning(f"⚠️ 在篩選範圍內，共有 {len(filtered_df)} 位人員尚未分配房間：")
            
            # 統計摘要：顯示各宿舍、各雇主的待分配人數
            st.markdown("##### 📊 待分配人數統計")
            summary = filtered_df.groupby(['宿舍地址', '雇主']).size().reset_index(name='人數')
            st.dataframe(summary, hide_index=True, width='stretch')
            
            st.markdown("---")
            st.markdown("##### 📋 詳細名單")
            st.dataframe(
                filtered_df, 
                width="stretch", 
                hide_index=True,
                column_config={
                    "入住日期": st.column_config.DateColumn(format="YYYY-MM-DD")
                }
            )
            
            st.info("💡 提示：請至 **「房間分配」** 頁面，選擇對應的宿舍來進行分配操作。")
        else:
            if not selected_dorms or not selected_employers:
                st.info("請從上方選單選擇「宿舍」與「雇主」以查看資料。")
            else:
                st.success("在目前的篩選條件下，沒有未分配房間的人員。")