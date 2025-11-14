# 檔案路徑: views/room_assignment_view.py
# (v2.1 - 修正 data_editor 狀態提交問題)

import streamlit as st
import pandas as pd
from data_models import room_assignment_model, dormitory_model

def render():
    """渲染「房間與床位分配」頁面"""
    st.header("🛏️ 房間與床位分配")
    st.info(
        """
        此頁面用於快速修正 `[未分配房間]` 的員工。
        - **運作方式：** 系統會直接**覆蓋**該員工的 `[未分配房間]` 紀錄，將其改為您指定的新房號與床位。
        - **日期邏輯：**
            - 如果「新入住日」**留空**：系統將**保留**員工原始的 `[未分配房間]` 入住日。
            - 如果「新入住日」**有填**：系統會**連同日期一起覆蓋**。
        - **注意：** 您可以在下方步驟三選擇此操作要套用的資料保護層級。
        """
    ) 

    # --- 步驟一：篩選宿舍 ---
    @st.cache_data
    def get_my_dorms():
        return dormitory_model.get_my_company_dorms_for_selection()

    my_dorms = get_my_dorms()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍。")
        return
    
    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}
    
    selected_dorm_id = st.selectbox(
        "步驟一：請選擇宿舍",
        options=[None] + list(dorm_options.keys()),
        format_func=lambda x: "請選擇..." if x is None else dorm_options.get(x),
    )

    if not selected_dorm_id:
        return

    # --- 步驟二：載入資料 ---
    @st.cache_data
    def get_unassigned(dorm_id):
        return room_assignment_model.get_unassigned_workers(dorm_id)
        
    @st.cache_data
    def get_rooms_for_dorm(dorm_id):
        rooms_in_dorm = dormitory_model.get_rooms_for_selection(dorm_id) or []
        room_options = {r['id']: r['room_number'] for r in rooms_in_dorm if r['room_number'] != '[未分配房間]'}
        return room_options

    workers_df = get_unassigned(selected_dorm_id)
    room_options = get_rooms_for_dorm(selected_dorm_id)

    if workers_df.empty:
        st.success("太好了！這間宿舍目前沒有員工被分配在 `[未分配房間]`。")
        return
        
    if not room_options:
        st.error(f"錯誤：宿舍 '{dorm_options[selected_dorm_id]}' 尚未建立任何可用房號（除了[未分配房間]）。請先至「地址管理」新增房號，才能進行分配。")
        return

    st.markdown("---")
    
    # --- 【*** 核心修改：將所有操作元件放入 st.form ***】 ---
    with st.form("assignment_form"):
        st.subheader("步驟二：分配房間與床位")
        st.caption(f"偵測到 {len(workers_df)} 位員工在 `[未分配房間]`。請在下方表格中為他們指定新房號與床位。")

        # 準備 data_editor
        workers_df["新房號"] = None
        workers_df["新床位編號"] = ""
        workers_df["新入住日"] = pd.NaT 

        edited_df = st.data_editor(
            workers_df,
            key="assignment_editor",
            width='stretch',
            hide_index=True,
            column_config={
                "ah_id": None, 
                "worker_unique_id": None,
                "雇主": st.column_config.TextColumn(disabled=True),
                "姓名": st.column_config.TextColumn(disabled=True),
                "原入住日": st.column_config.DateColumn(format="YYYY-MM-DD", disabled=True),
                "原房號": st.column_config.TextColumn(disabled=True),
                "新房號": st.column_config.SelectboxColumn(
                    "新房號 (必填)",
                    options=list(room_options.keys()),
                    format_func=lambda x: room_options.get(x, "請選擇..."),
                    required=True,
                ),
                "新床位編號": st.column_config.TextColumn(
                    "新床位編號 (選填)",
                    max_chars=50
                ),
                "新入住日": st.column_config.DateColumn(
                    "新入住日 (選填)",
                    format="YYYY-MM-DD",
                    help="若留空，將保留「原入住日」"
                )
            },
            disabled=["雇主", "姓名", "原入住日", "原房號", "ah_id", "worker_unique_id"]
        )

        st.markdown("---")
        st.subheader("步驟三：設定保護層級")
        st.info("請選擇在分配房間後，這些員工的資料保護狀態。")
        
        protection_options = {
            "手動調整": "保護「住宿位置/日期」，但允許爬蟲未來更新「離住日」。 (建議選項)",
            "系統自動更新": "不保護。在下次執行時，用系統資料覆蓋此次修改。",
            "手動管理(他仲)": "完全鎖定。未來將跳過這些人，不更新任何資料（包括離住日）。"
        }
        
        form_protection_level = st.selectbox(
            "選擇更新後的保護層級*",
            options=list(protection_options.keys()),
            format_func=lambda x: protection_options[x],
            index=0, # 預設 "手動調整"
            key="assignment_protection_level"
        )
        
        # --- 【*** 核心修改：將 st.button 改為 st.form_submit_button ***】 ---
        submitted = st.form_submit_button("🚀 儲存分配結果", type="primary")

        if submitted:
            # 這裡的 edited_df 會是按下按鈕瞬間的最終狀態
            updates_df = edited_df[edited_df["新房號"].notna()]
            
            if updates_df.empty:
                st.warning("您沒有分配任何新的房號。")
            else:
                updates_list = []
                for _, row in updates_df.iterrows():
                    updates_list.append({
                        'ah_id': row['ah_id'],
                        'worker_id': row['worker_unique_id'],
                        'new_room_id': row['新房號'],
                        'new_bed_number': str(row['新床位編號']).strip() or None,
                        'new_start_date': row['新入住日'] 
                    })
                
                with st.spinner(f"正在為 {len(updates_list)} 位員工更新住宿資料..."):
                    success_count, failed_count, message = room_assignment_model.batch_update_assignments(
                        updates_list,
                        form_protection_level 
                    )
                    
                if failed_count > 0:
                    st.error(message)
                else:
                    st.success(message)
                    
                st.cache_data.clear()
                # st.rerun() # 在 form 內部，rerun 不是必須的，資料會自動刷新