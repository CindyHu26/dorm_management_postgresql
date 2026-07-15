# views/cleaning_schedule_view.py

import streamlit as st
import pandas as pd
from datetime import date
from data_models import cleaning_model, dormitory_model
import io # 用於處理 BytesIO
import database

def render():
    """渲染「清掃排程管理」頁面"""
    st.info("管理「我司」負責宿舍的清掃排程。簡易清掃固定於每年3、9月；大掃除固定於每年6、12月。") # 更新說明文字

    if st.button("🔄 重新整理排程列表"):
        st.cache_data.clear()
        st.rerun() # 清除快取後重新執行

    # --- 批次設定區塊 ---
    with st.expander("⚙️ 批次排程設定 (適用所有我司宿舍)"):
        st.warning("⚠️ 注意：以下操作將會影響所有「我司管理」的宿舍！")

        # --- 強制初始化 ---
        st.markdown("##### 重新設定所有宿舍的下次清掃日期")
        st.caption("系統將以此日期為基準，找出下一個固定的清掃月份（3/9月或6/12月）作為首次排程日期。") # 更新說明
        start_calc_date = st.date_input("選擇排程計算基準日期*", value=date.today()) # 修改標籤
        confirm_force_init = st.checkbox("我確認要清除所有現有清掃排程，並根據上方基準日期重新設定所有『我司管理』宿舍的排程。")
        if st.button("🚀 套用設定至所有宿舍 (將覆蓋現有排程)", disabled=not confirm_force_init): # 修改按鈕文字
            with st.spinner("正在清除舊排程並重新設定所有宿舍..."):
                processed_count, message = cleaning_model.force_initialize_all_schedules(start_calc_date)
            if processed_count > 0:
                 st.success(message)
                 st.cache_data.clear()
                 st.rerun()
            else:
                 st.error(message)

        st.markdown("---")
        # --- 清除所有排程 ---
        st.markdown("##### 清除所有清掃排程紀錄")
        st.error("🔴 危險操作：此動作將刪除所有「我司管理」宿舍的清掃紀錄，包括上次完成日期和下次預計日期。")
        confirm_clear_all = st.checkbox("我確認要刪除所有清掃排程紀錄。")
        if st.button("🗑️ 清除所有現有清掃排程", type="primary", disabled=not confirm_clear_all):
             with st.spinner("正在清除所有清掃排程..."):
                 deleted_count, message = cleaning_model.clear_all_cleaning_schedules()
             if deleted_count >= 0: # 即使刪除0筆也是成功
                 st.success(message)
                 st.cache_data.clear()
                 st.rerun()
             else:
                 st.error(message)


    # --- 顯示目前的排程狀態 ---
    st.markdown("---")
    st.subheader("🗓️ 目前清掃排程狀態")

    @st.cache_data
    def get_schedule_data():
        # 後端已預設查詢 '我司' 宿舍
        return cleaning_model.get_cleaning_schedule()

    schedule_df = get_schedule_data()

    if schedule_df.empty:
        st.warning("目前沒有任何「我司管理」的宿舍排程紀錄。您可以嘗試使用上方的「批次排程設定」。")
    else:
        # --- 篩選器 ---
        st.markdown("##### 篩選排程列表")
        filter_cols = st.columns(4) # 4欄
        # 取得唯一值用於選項 (處理 NaN)
        cities = sorted(schedule_df['縣市'].dropna().unique())
        districts = sorted(schedule_df['區域'].dropna().unique())
        persons = sorted(schedule_df['負責人'].dropna().unique())
        cleaning_types = sorted(schedule_df['清掃類型'].dropna().unique())

        selected_cities = filter_cols[0].multiselect("依縣市篩選", cities, key="city_filter")
        selected_districts = filter_cols[1].multiselect("依區域篩選", districts, key="district_filter")
        selected_persons = filter_cols[2].multiselect("依負責人篩選", persons, key="person_filter")
        selected_cleaning_types = filter_cols[3].multiselect("依清掃類型篩選", cleaning_types, key="cleaning_type_filter")

        # 應用篩選條件
        filtered_schedule_df = schedule_df.copy()
        if selected_cities:
            filtered_schedule_df = filtered_schedule_df[filtered_schedule_df['縣市'].isin(selected_cities)]
        if selected_districts:
            filtered_schedule_df = filtered_schedule_df[filtered_schedule_df['區域'].isin(selected_districts)]
        if selected_persons:
            filtered_schedule_df = filtered_schedule_df[filtered_schedule_df['負責人'].isin(selected_persons)]
        if selected_cleaning_types:
            filtered_schedule_df = filtered_schedule_df[filtered_schedule_df['清掃類型'].isin(selected_cleaning_types)]
        # --- 篩選器結束 ---

        # --- 全選/取消全選按鈕 ---
        select_all_key = "cleaning_select_all_state"
        if select_all_key not in st.session_state:
            st.session_state[select_all_key] = False # 預設不全選

        button_cols = st.columns(2)
        if button_cols[0].button("✅ 全選 (目前篩選結果)"):
            st.session_state[select_all_key] = True
            st.rerun() # 重新執行以套用狀態
        if button_cols[1].button("⬜ 取消全選 (目前篩選結果)"):
            st.session_state[select_all_key] = False
            st.rerun() # 重新執行以套用狀態
        # --- 全選/取消全選結束 ---


        # 準備用於 data_editor 的 DataFrame
        filtered_schedule_df_with_selection = filtered_schedule_df.copy()
        select_value = st.session_state[select_all_key]
        filtered_schedule_df_with_selection.insert(0, "選取", select_value) # 插入 "選取" 欄

        column_order = [
            "選取", "宿舍地址", "縣市", "區域", "負責人",
            "清掃類型", "上次完成日期", "下次預計日期", "頻率(月)", "id"
        ]
        display_columns = [col for col in column_order if col in filtered_schedule_df_with_selection.columns]

        st.markdown("##### 排程列表 (可勾選)")
        edited_df = st.data_editor(
            filtered_schedule_df_with_selection[display_columns],
            key="schedule_editor",
            hide_index=True,
            column_config={
                "選取": st.column_config.CheckboxColumn(required=True),
                "id": None, # 隱藏 ID
                "上次完成日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "下次預計日期": st.column_config.DateColumn(format="YYYY-MM-DD"),
                "頻率(月)": st.column_config.NumberColumn(format="%d 個月")
            },
            disabled=filtered_schedule_df.columns # 只允許編輯 "選取" 欄
        )

        selected_rows = edited_df[edited_df.選取] # 取得勾選的列

        # --- 批次標記完成 與 批次刪除 區塊 ---
        st.markdown("---")
        col_mark, col_delete = st.columns(2) # 並排顯示

        with col_mark:
            st.subheader("✅ 批次標記完成")
            completion_date_input = st.date_input("選擇完成日期*", value=date.today(), key="completion_date")
            if st.button("🚀 標記選定項目為完成", type="primary", disabled=selected_rows.empty, key="mark_complete_btn"):
                record_ids_to_complete = selected_rows['id'].tolist()
                with st.spinner(f"正在批次更新 {len(record_ids_to_complete)} 筆紀錄..."):
                    success, message = cleaning_model.mark_cleaning_complete(record_ids_to_complete, completion_date_input)
                if success:
                    st.success(message)
                    st.cache_data.clear()
                    st.session_state[select_all_key] = False # 操作完成後取消全選
                    st.rerun()
                else:
                    st.error(message)

        with col_delete:
            st.subheader("🗑️ 批次刪除排程")
            st.error("注意：此操作將永久刪除選取的排程紀錄！") # 提醒
            confirm_batch_delete = st.checkbox("我確認要刪除所有選取的排程紀錄")
            if st.button("❌ 刪除選定項目", disabled=selected_rows.empty or not confirm_batch_delete, key="delete_selected_btn"):
                 record_ids_to_delete = selected_rows['id'].tolist()
                 with st.spinner(f"正在批次刪除 {len(record_ids_to_delete)} 筆紀錄..."):
                      deleted_count, message = cleaning_model.batch_delete_cleaning_schedules(record_ids_to_delete)
                 if deleted_count >= 0: # 刪除0筆也算成功
                     st.success(message)
                     st.cache_data.clear()
                     st.session_state[select_all_key] = False # 操作完成後取消全選
                     st.rerun()
                 else:
                     st.error(message)

# --- 公告匯出區塊 (加入篩選 和 預選) ---
    st.markdown("---")
    st.subheader("📢 匯出打掃公告 (Word)")

    st.markdown("##### 篩選宿舍列表 (公告用)") # 加上標題區分
    notice_filter_cols = st.columns(4)
    # 使用 schedule_df 的資料來產生篩選選項 (如果 schedule_df 存在)
    notice_cities = sorted(schedule_df['縣市'].dropna().unique()) if not schedule_df.empty else []
    notice_districts = sorted(schedule_df['區域'].dropna().unique()) if not schedule_df.empty else []
    notice_persons = sorted(schedule_df['負責人'].dropna().unique()) if not schedule_df.empty else []
    notice_cleaning_types = sorted(schedule_df['清掃類型'].dropna().unique()) if not schedule_df.empty else []

    selected_notice_cities = notice_filter_cols[0].multiselect("依縣市篩選公告", notice_cities, key="notice_city_filter")
    selected_notice_districts = notice_filter_cols[1].multiselect("依區域篩選公告", notice_districts, key="notice_district_filter")
    selected_notice_persons = notice_filter_cols[2].multiselect("依負責人篩選公告", notice_persons, key="notice_person_filter")
    selected_notice_cleaning_types = notice_filter_cols[3].multiselect("依清掃類型篩選公告", notice_cleaning_types, key="notice_cleaning_type_filter")

    # 應用篩選條件到 schedule_df 以獲取宿舍列表
    filtered_notice_df = schedule_df.copy() # Start with the full schedule data
    if selected_notice_cities:
        filtered_notice_df = filtered_notice_df[filtered_notice_df['縣市'].isin(selected_notice_cities)]
    if selected_notice_districts:
        filtered_notice_df = filtered_notice_df[filtered_notice_df['區域'].isin(selected_notice_districts)]
    if selected_notice_persons:
        filtered_notice_df = filtered_notice_df[filtered_notice_df['負責人'].isin(selected_notice_persons)]
    if selected_notice_cleaning_types:
        filtered_notice_df = filtered_notice_df[filtered_notice_df['清掃類型'].isin(selected_notice_cleaning_types)]

    # --- 從篩選後的 DataFrame 提取唯一的宿舍 ID 和地址 ---
    filtered_dorm_info = {}
    if not filtered_notice_df.empty:
        conn = database.get_db_connection()
        if conn:
             try:
                 with conn.cursor() as cursor:
                     # 查詢與篩選後 compliance record id 相關的 dorm id 和 address
                     cursor.execute(
                         'SELECT DISTINCT d.id, d.original_address FROM "Dormitories" d JOIN "ComplianceRecords" cr ON d.id = cr.dorm_id WHERE cr.id = ANY(%s)',
                         (filtered_notice_df['id'].tolist(),)
                     )
                     # 建立 dorm_id: address 的字典
                     filtered_dorm_info = {row['id']: row['original_address'] for row in cursor.fetchall()}
             except Exception as e:
                 st.error(f"查詢篩選宿舍時出錯: {e}")
             finally:
                 if conn: conn.close()

    # --- 準備 multiselect 的選項和預設值 ---
    dorm_options_for_notice_filtered = filtered_dorm_info if filtered_dorm_info else {"": "無符合篩選的宿舍"}
    # --- 核心修改：預設選取所有篩選出的宿舍 ---
    default_selection = list(dorm_options_for_notice_filtered.keys())
    # 移除可能的空鍵 ""
    default_selection = [dorm_id for dorm_id in default_selection if dorm_id != ""]
    # --- 修改結束 ---


    notice_col1, notice_col2 = st.columns(2)
    selected_dorm_ids_for_notice = notice_col1.multiselect(
        "選擇要產生公告的宿舍*",
        options=list(dorm_options_for_notice_filtered.keys()),
        format_func=lambda x: dorm_options_for_notice_filtered.get(x, "未知宿舍"),
        # --- 核心修改：設定 default ---
        default=default_selection,
        # --- 修改結束 ---
        key="notice_dorm_select" # 給 multiselect 一個 key
    )
    notice_cleaning_date = notice_col2.date_input("預計打掃日期*", value=date.today())


    if st.button("📄 產生 Word 公告檔案"):
        # 檢查 selected_dorm_ids_for_notice 是否包含無效的空鍵 ""
        valid_selected_dorm_ids = [dorm_id for dorm_id in selected_dorm_ids_for_notice if dorm_id != ""]

        if not valid_selected_dorm_ids:
            st.error("請至少選擇一間宿舍！")
        elif not cleaning_model.DOCX_AVAILABLE:
             st.error("錯誤：缺少 `python-docx` 函式庫，無法產生 Word 文件。請聯繫系統管理員安裝。")
        else:
            for dorm_id in valid_selected_dorm_ids:
                # 使用篩選後的字典來獲取地址
                dorm_address = dorm_options_for_notice_filtered.get(dorm_id, f"宿舍ID_{dorm_id}")
                file_name_date = notice_cleaning_date.strftime("%m%d")
                file_name = f"{dorm_address}_{file_name_date}打掃公告.docx"
                file_name = "".join(c for c in file_name if c.isalnum() or c in (' ', '.', '_')).rstrip()

                with st.spinner(f"正在產生 {dorm_address} 的公告..."):
                    notice_buffer = cleaning_model.generate_cleaning_notice(dorm_address, notice_cleaning_date)

                if notice_buffer:
                    st.download_button(
                        label=f"📥 下載 {file_name}",
                        data=notice_buffer,
                        file_name=file_name,
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        key=f"download_{dorm_id}"
                    )
                else:
                    st.error(f"產生 {dorm_address} 的公告失敗。")