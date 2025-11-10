# views/meter_expense_view.py

import streamlit as st
import pandas as pd
from datetime import date
from data_models import finance_model, dormitory_model, meter_model

def render():
    """渲染「錶號費用管理」頁面 (DataEditor 模式)"""
    st.header("錶號費用管理")
    st.info("此頁面專為快速登錄與特定錶號相關的費用（如水電費）而設計。請先搜尋並選取一個錶號開始操作。")

    # --- 1. 搜尋與選取錶號 (維持不變) ---
    search_term = st.text_input("搜尋錶號、類型或地址以篩選列表：")
    
    @st.cache_data
    def get_all_meters(term):
        return meter_model.search_all_meters(term)

    all_meters = get_all_meters(search_term)
    
    if not all_meters:
        st.warning("找不到任何錶號。請先至「電水錶管理」頁面新增。")
        return

    meter_options = {m['id']: f"{m['original_address']} - {m['meter_type']} ({m['meter_number']})" for m in all_meters}
    
    selected_meter_id = st.selectbox(
        "請選擇要管理的錶號：",
        options=[None] + list(meter_options.keys()),
        format_func=lambda x: "請選擇..." if x is None else meter_options.get(x),
    )

    if not selected_meter_id:
        return

    # --- 2. 顯示關聯的宿舍資訊 (維持不變) ---
    @st.cache_data
    def get_context_details(meter_id):
        dorm_id = meter_model.get_dorm_id_from_meter_id(meter_id)
        if not dorm_id:
            return None, None
        dorm_details = dormitory_model.get_dorm_details_by_id(dorm_id)
        return dorm_id, dorm_details

    dorm_id, dorm_details = get_context_details(selected_meter_id)
    
    if not dorm_id or not dorm_details:
        st.error("發生錯誤：找不到此錶號關聯的宿舍。")
        return
        
    st.markdown("---")
    with st.container(border=True):
        st.subheader(f"目前操作對象: {meter_options[selected_meter_id]}")
        col1, col2 = st.columns(2)
        # 【功能保留】
        col1.info(f"**宿舍編號:** {dorm_details.get('legacy_dorm_code') or '未設定'}")
        col2.info(f"**變動費用備註:** {dorm_details.get('utility_bill_notes') or '無'}")

    st.markdown("---")
    
    # --- 3. 【核心修改】使用 DataEditor 替換所有舊表單 ---
    st.subheader("帳單紀錄 (可直接編輯)")
    st.info(
        """
        - **編輯**：直接在表格中修改資料。
        - **新增**：點擊表格底部的 `+` 按鈕新增一列。
        - **刪除**：點擊該列最左側的 `▢` 並於右上角選擇 `🗑`。
        """
    )

    @st.cache_data
    def get_bills_for_editor(meter_id):
        # 呼叫我們新增的函式
        return finance_model.get_bills_for_editor(meter_id)

    bills_df = get_bills_for_editor(selected_meter_id)

    # 準備選項
    bill_type_options = ["電費", "水費", "天然氣", "網路費", "子母車", "清潔", "瓦斯費"]
    payer_options = ["我司", "雇主", "工人"]

    with st.form("bill_editor_form"):
        edited_df = st.data_editor(
            bills_df,
            key=f"bill_editor_{selected_meter_id}",
            width="stretch",
            hide_index=True,
            num_rows="dynamic", # 允許新增和刪除
            column_config={
                "id": st.column_config.NumberColumn(
                    "ID", 
                    disabled=True
                ),
                "bill_type": st.column_config.SelectboxColumn(
                    "費用類型",
                    options=bill_type_options,
                    required=True,
                    help="若為 '其他'，請直接輸入文字"
                ),
                "amount": st.column_config.NumberColumn(
                    "帳單金額",
                    min_value=0,
                    step=100,
                    format="%d",
                    required=True
                ),
                "usage_amount": st.column_config.NumberColumn(
                    "用量(度/噸)",
                    min_value=0.0,
                    format="%.2f"
                ),
                "bill_start_date": st.column_config.DateColumn(
                    "帳單起始日",
                    format="YYYY-MM-DD",
                    required=True
                ),
                "bill_end_date": st.column_config.DateColumn(
                    "帳單結束日",
                    format="YYYY-MM-DD",
                    required=True
                ),
                "payer": st.column_config.SelectboxColumn(
                    "支付方",
                    options=payer_options,
                    default="我司",
                    required=True
                ),
                "is_pass_through": st.column_config.CheckboxColumn(
                    "代收代付?",
                    default=False
                ),
                "is_invoiced": st.column_config.CheckboxColumn(
                    "已請款?",
                    default=False
                ),
                "notes": st.column_config.TextColumn(
                    "備註"
                )
            }
        )
        
        submitted = st.form_submit_button("🚀 儲存所有帳單變更")
        if submitted:
            with st.spinner("正在同步帳單資料..."):
                # 呼叫新的後端函式
                success, message = finance_model.batch_sync_bills(
                    selected_meter_id, 
                    dorm_id, 
                    edited_df
                )
            
            if success:
                st.success(message)
                st.cache_data.clear() # 清除所有快取
                st.rerun()
            else:
                st.error(message)