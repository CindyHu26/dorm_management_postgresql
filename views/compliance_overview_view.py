import streamlit as st
import pandas as pd
from data_models import compliance_model, dormitory_model

def render():
    st.info("可以直接在表格中修改申報項目、期限或費用。修改後請點擊下方「儲存變更」按鈕。")

    # --- 1. 篩選區塊 ---
    with st.container(border=True):
        c1, c2 = st.columns(2)
        dorms = dormitory_model.get_dorms_for_selection()
        dorm_options = {d['id']: d['original_address'] for d in dorms}
        
        sel_dorm = c1.selectbox("篩選宿舍", options=[None] + list(dorm_options.keys()), 
                                format_func=lambda x: "全部宿舍" if x is None else dorm_options[x])
        
        type_options = ["建物申報", "消防安檢", "其他"]
        sel_type = c2.selectbox("資料類別", options=[None] + type_options,
                                format_func=lambda x: "全部類別" if x is None else x)

    # --- 2. 獲取並處理資料 ---
    full_df = compliance_model.get_compliance_flat_report(dorm_id=sel_dorm, record_type=sel_type)

    if full_df.empty:
        st.warning("查無符合條件的合規紀錄。")
        return

    # 隱藏原始 JSON 欄位 raw_details
    display_df = full_df.drop(columns=['raw_details'])

    # --- 3. 編輯表格 ---
    # 使用 data_editor 提供即時編輯功能
    st.markdown("#### 申報資料清單")
    edited_output = st.data_editor(
        display_df,
        key="comp_editor",
        use_container_width=True,
        hide_index=True,
        column_config={
            "id": None, # 隱藏系統 ID
            "宿舍": st.column_config.TextColumn("所屬宿舍", disabled=True),
            "類別": st.column_config.TextColumn("類別", disabled=True),
            "核准止": st.column_config.DateColumn("核准截止日期"),
            "下次申報止": st.column_config.DateColumn("下次申報期限", required=True),
            "金額(未稅)": st.column_config.NumberColumn("金額", format="$%d"),
            "申報項目": st.column_config.TextColumn("申報項目", width="large")
        }
    )

    # --- 4. 編輯存檔區塊 ---
    # 從 session_state 獲取編輯狀態
    state = st.session_state.comp_editor
    if state.get("edited_rows"):
        st.warning(f"偵測到 {len(state['edited_rows'])} 筆資料已變更，請務必點擊儲存。")
        if st.button("💾 儲存已修改的變更內容", type="primary", use_container_width=True):
            with st.spinner("正在儲存變更..."):
                success, msg = compliance_model.update_compliance_batch(state["edited_rows"], full_df)
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    # --- 5. 刪除區塊 ---
    st.markdown("---")
    with st.expander("🗑️ 刪除紀錄管理"):
        record_to_del = st.selectbox(
            "選擇要移除的合規紀錄", 
            options=full_df.to_dict('records'),
            format_func=lambda x: f"{x['宿舍']} | {x['類別']} | 期限:{x['下次申報止']}"
        )
        
        if st.button("⚠️ 確認永久刪除紀錄", type="secondary"):
            if compliance_model.delete_compliance_record(record_to_del['id']):
                st.success("紀錄已成功刪除")
                st.rerun()
            else:
                st.error("刪除失敗，請檢查資料庫狀態。")