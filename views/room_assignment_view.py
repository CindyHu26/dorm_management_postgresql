# views/room_assignment_view.py
# (v2.3 - 移除快取以解決資料不同步問題)

import streamlit as st
import pandas as pd
from data_models import room_assignment_model, dormitory_model

def render():
    """渲染「房間與床位分配」頁面"""
    st.header("🛏️ 房間與床位管理")

    # --- 模式切換 ---
    mode = st.radio(
        "請選擇操作模式：",
        options=["分配新進人員 (針對未分配者)", "修正現有房號 (針對打錯/調整)"],
        horizontal=True,
        label_visibility="collapsed"
    )

    # --- 步驟一：篩選宿舍 (共用) ---
    # 【核心修改】移除 @st.cache_data，確保能讀到最新新增的宿舍
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
        key="common_dorm_selector"
    )

    if not selected_dorm_id:
        return

    # 【核心修改】移除 @st.cache_data，確保能讀到最新新增的房號
    def get_rooms_for_dorm(dorm_id):
        rooms_in_dorm = dormitory_model.get_rooms_for_selection(dorm_id) or []
        # 排除 [未分配房間]，只顯示真實房間
        room_options = {r['id']: r['room_number'] for r in rooms_in_dorm if r['room_number'] != '[未分配房間]'}
        return room_options

    room_options = get_rooms_for_dorm(selected_dorm_id)
    if not room_options:
        st.error(f"錯誤：此宿舍尚未建立任何可用房號。請先至「地址管理」新增房號。")
        return

    st.markdown("---")

    # ==========================================================================
    # 模式 A: 分配新進人員 (原本的功能)
    # ==========================================================================
    if mode == "分配新進人員 (針對未分配者)":
        st.info(
            """
            **模式說明**：此功能專用於將目前暫掛在 `[未分配房間]` 的員工移入正式房間。
            - **運作方式**：系統會**直接更新**該員工目前的 `[未分配房間]` 紀錄為您指定的新房號（**不會**產生額外的換宿歷史）。
            - **日期設定**：您可以指定「新入住日」，若留空則沿用原本在 `[未分配房間]` 的入住日。
            """
        )

        # 【核心修改】移除 @st.cache_data，確保能讀到最新的人員狀態
        def get_unassigned(dorm_id):
            return room_assignment_model.get_unassigned_workers(dorm_id)

        workers_df = get_unassigned(selected_dorm_id)

        if workers_df.empty:
            st.success("太好了！這間宿舍目前沒有員工被分配在 `[未分配房間]`。")
            return
            
        with st.form("assignment_form"):
            st.subheader("步驟二：分配房間與床位")
            st.caption(f"偵測到 {len(workers_df)} 位員工在 `[未分配房間]`。")

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
                    "新床位編號": st.column_config.TextColumn("新床位 (選填)"),
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
            
            protection_options = {
                "手動調整": "保護「住宿位置」，但允許系統更新「離住日」。 (建議)",
                "系統自動更新": "不保護。下次同步時可能被系統覆蓋。",
                "手動管理(他仲)": "完全鎖定。系統不再更新此人任何資料。"
            }
            
            form_protection_level = st.selectbox(
                "選擇更新後的保護層級*",
                options=list(protection_options.keys()),
                format_func=lambda x: protection_options[x],
                index=0,
                key="assign_prot_level"
            )
            
            submitted = st.form_submit_button("🚀 儲存分配結果", type="primary")

            if submitted:
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
                    
                    with st.spinner(f"正在更新 {len(updates_list)} 位員工..."):
                        success_cnt, failed_cnt, msg = room_assignment_model.batch_update_assignments(
                            updates_list, form_protection_level 
                        )
                    
                    if failed_cnt > 0: st.error(msg)
                    else: st.success(msg)
                        
                    # 雖然移除了函式快取，但仍清除全域快取以防萬一
                    st.cache_data.clear()
                    st.rerun()

    # ==========================================================================
    # 模式 B: 修正現有房號
    # ==========================================================================
    else:
        st.info(
            """
            **模式說明**：此功能用於**修正錯誤**（例如：大批匯入時房號填錯）。
            - 系統**不會**產生新紀錄，而是直接修改目前這一筆住宿紀錄的房號。
            - 「入住日」會保持不變。
            """
        )

        # 【核心修改】移除 @st.cache_data，確保能讀到最新的人員狀態
        def get_residents_for_correction(dorm_id):
            return room_assignment_model.get_active_residents_for_correction(dorm_id)

        residents_df = get_residents_for_correction(selected_dorm_id)

        if residents_df.empty:
            st.warning("此宿舍目前沒有任何在住員工可供修正。")
            return

        with st.form("correction_form"):
            st.subheader("步驟二：直接修正房號/床位")
            st.caption(f"此宿舍共有 {len(residents_df)} 位在住員工。請直接在下方修改他們的房號。")

            residents_df["修正後房號"] = None 
            residents_df["修正後床位"] = None 

            edited_df = st.data_editor(
                residents_df,
                key="correction_editor",
                width='stretch',
                hide_index=True,
                column_config={
                    "ah_id": None, "worker_unique_id": None,
                    "雇主": st.column_config.TextColumn(disabled=True),
                    "姓名": st.column_config.TextColumn(disabled=True),
                    "入住日": st.column_config.DateColumn(format="YYYY-MM-DD", disabled=True),
                    "目前房號": st.column_config.TextColumn(disabled=True),
                    "目前床位": st.column_config.TextColumn(disabled=True),
                    
                    "修正後房號": st.column_config.SelectboxColumn(
                        "修正後房號 (若無變更請留空)",
                        options=list(room_options.keys()),
                        format_func=lambda x: room_options.get(x, ""),
                        required=False 
                    ),
                    "修正後床位": st.column_config.TextColumn("修正後床位 (選填)")
                },
                disabled=["雇主", "姓名", "入住日", "目前房號", "目前床位", "ah_id", "worker_unique_id"]
            )

            st.markdown("---")
            st.subheader("步驟三：設定保護層級")
            
            protection_options = {
                "手動調整": "保護「住宿位置」，但允許系統更新「離住日」。 (建議)",
                "系統自動更新": "不保護。下次同步時可能被系統覆蓋。",
                "手動管理(他仲)": "完全鎖定。系統不再更新此人任何資料。"
            }
            
            form_protection_level = st.selectbox(
                "選擇更新後的保護層級*",
                options=list(protection_options.keys()),
                format_func=lambda x: protection_options[x],
                index=0,
                key="correct_prot_level"
            )

            submitted = st.form_submit_button("🚀 執行修正 (直接更新)", type="primary")

            if submitted:
                updates_list = []
                for _, row in edited_df.iterrows():
                    new_room_val = row['修正後房號']
                    new_bed_val = row['修正後床位']
                    
                    if pd.notna(new_room_val):
                        updates_list.append({
                            'ah_id': row['ah_id'],
                            'worker_id': row['worker_unique_id'],
                            'new_room_id': int(new_room_val),
                            'new_bed_number': str(new_bed_val).strip() if pd.notna(new_bed_val) and str(new_bed_val).strip() else None
                        })

                if not updates_list:
                    st.warning("您沒有選擇任何要修正的「新房號」。")
                else:
                    with st.spinner(f"正在修正 {len(updates_list)} 筆紀錄..."):
                        success_cnt, failed_cnt, msg = room_assignment_model.batch_correct_assignments(
                            updates_list, form_protection_level 
                        )
                    
                    if failed_cnt > 0: st.error(msg)
                    else: st.success(msg)
                        
                    st.cache_data.clear()
                    st.rerun()