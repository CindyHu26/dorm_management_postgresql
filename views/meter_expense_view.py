# views/meter_expense_view.py
# (v5.0 - 版面調整：總覽在上、新增在下；度數改為整數)

import streamlit as st
import pandas as pd
from datetime import date
from data_models import finance_model, dormitory_model, meter_model
import numpy as np
from dateutil.relativedelta import relativedelta

def render():
    """渲染「錶號費用管理」頁面 (DataEditor 模式)"""
    st.info("此頁面專為快速登錄與特定錶號相關的費用（如水電費）而設計。請先搜尋並選取一個錶號開始操作。")

    # --- 1. 搜尋與選取錶號 ---
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

    # --- 2. 顯示關聯的宿舍資訊---
    def get_context_details(meter_id):
        dorm_id = meter_model.get_dorm_id_from_meter_id(meter_id)
        if not dorm_id:
            return None, None, None
        dorm_details = dormitory_model.get_dorm_details_by_id(dorm_id)
        meter_details = meter_model.get_single_meter_details(meter_id)
        return dorm_id, dorm_details, meter_details

    dorm_id, dorm_details, meter_details = get_context_details(selected_meter_id)
    
    if not dorm_id or not dorm_details or not meter_details:
        st.error("發生錯誤：找不到此錶號關聯的宿舍或錶號本身資料。")
        return
        
    st.markdown("---")
    with st.container(border=True):
        st.subheader(f"目前操作對象: {meter_options[selected_meter_id]}")
        col1, col2 = st.columns(2)
        col1.info(f"**宿舍編號:** {dorm_details.get('legacy_dorm_code') or '未設定'}")
        col2.info(f"**變動費用備註:** {dorm_details.get('utility_bill_notes') or '無'}")
    
    # --- 選項準備 ---
    bill_type_options_add = ["電費", "水費", "天然氣", "網路費", "子母車", "清潔", "瓦斯費"]
    payer_options_add = ["我司", "雇主", "工人"]
    default_payer = dorm_details.get('utilities_payer', '我司')
    try:
        default_payer_index = payer_options_add.index(default_payer)
    except ValueError:
        default_payer_index = 0

    # 根據錶號類型決定預設費用類型
    meter_type_to_bill_type_map = {
        "電錶": "電費",
        "水錶": "水費",
        "天然氣": "天然氣",
        "電信": "網路費"
    }
    current_meter_type = meter_details.get("meter_type")
    default_bill_type = meter_type_to_bill_type_map.get(current_meter_type, bill_type_options_add[0])
    try:
        default_bill_type_idx = bill_type_options_add.index(default_bill_type)
    except ValueError:
        default_bill_type_idx = 0

    st.markdown("---")

    # ==========================================
    # 3. 快速新增區塊 (移至下方，並改為整數)
    # ==========================================
    st.subheader("➕ 快速新增最新一筆帳單")

    # --- Callback: 自動計算結束日 ---
    def update_end_date_meter():
        start_date = st.session_state.get('add_meter_start_v4')
        bill_type = st.session_state.get('add_meter_type_v4')
        if start_date and bill_type in ["電費", "水費"]:
            try:
                st.session_state.add_meter_end_v4 = start_date + relativedelta(months=2)
            except Exception:
                st.session_state.add_meter_end_v4 = date.today()

    # --- Callback: 自動加總度數 (整數版) ---
    def auto_sum_usage_meter():
        # 使用 get 並給定預設值 0
        p = st.session_state.get('add_meter_peak_v4') or 0
        op = st.session_state.get('add_meter_off_v4') or 0
        sp = st.session_state.get('add_meter_sat_sp_v4') or 0 
        
        # 只要任一欄位有值，就自動計算總和
        if p > 0 or op > 0 or sp > 0:
            st.session_state.add_meter_usage_v4 = int(p + op + sp)

    # --- Session State 初始化 (使用整數 0) ---
    if 'add_meter_type_v4' not in st.session_state: st.session_state.add_meter_type_v4 = bill_type_options_add[default_bill_type_idx]
    if 'add_meter_start_v4' not in st.session_state: st.session_state.add_meter_start_v4 = None
    if 'add_meter_end_v4' not in st.session_state: st.session_state.add_meter_end_v4 = date.today()
    
    # 數值初始化為 int
    if 'add_meter_peak_v4' not in st.session_state: st.session_state.add_meter_peak_v4 = 0
    if 'add_meter_sat_sp_v4' not in st.session_state: st.session_state.add_meter_sat_sp_v4 = 0
    if 'add_meter_off_v4' not in st.session_state: st.session_state.add_meter_off_v4 = 0
    if 'add_meter_usage_v4' not in st.session_state: st.session_state.add_meter_usage_v4 = 0

    st.caption(f"目前鎖定錶號：{meter_options[selected_meter_id]}")  # 將提示移至上方，節省欄位空間

    # --- 第一排：基本帳單資訊 (5欄) ---
    r1c1, r1c2, r1c3, r1c4, r1c5 = st.columns(5)
    with r1c1:
        new_bill_type = st.selectbox("費用類型*", options=bill_type_options_add, key="add_meter_type_v4", on_change=update_end_date_meter)
    with r1c2:
        new_amount = st.number_input("帳單金額*", min_value=0, step=100, value=None, placeholder="請輸入...", key="add_meter_amount_v4")
    with r1c3:
        new_start_date = st.date_input("帳單起始日*", value=st.session_state.add_meter_start_v4, key="add_meter_start_v4", on_change=update_end_date_meter)
    with r1c4:
        new_end_date = st.date_input("帳單結束日*", key="add_meter_end_v4")
    with r1c5:
        new_payer = st.selectbox("支付方*", options=payer_options_add, index=default_payer_index, key="add_meter_payer_v4")

    # --- 第二排：用量與其他 (改成 6 欄以容納新欄位) ---
    # 順序：尖峰 -> 週六半尖峰 -> 離峰 -> 總用量 -> 備註 -> 代收代付
    r2c1, r2c2, r2c3, r2c4, r2c5, r2c6 = st.columns(6) 
    
    with r2c1:
        new_peak = st.number_input("尖峰 (整數)", min_value=0, step=1, key="add_meter_peak_v4", on_change=auto_sum_usage_meter)
    with r2c2:
        # 【新增】週六半尖峰
        new_sat_sp = st.number_input("週六半尖峰", min_value=0, step=1, key="add_meter_sat_sp_v4", on_change=auto_sum_usage_meter)
    with r2c3:
        new_off_peak = st.number_input("離峰 (整數)", min_value=0, step=1, key="add_meter_off_v4", on_change=auto_sum_usage_meter)
    with r2c4:
        new_usage = st.number_input("總用量 (整)*", min_value=0, step=1, key="add_meter_usage_v4", help="自動加總")
    with r2c5:
        new_notes = st.text_input("備註", key="add_meter_notes_v4") 
    with r2c6:
        st.write("") # 排版用
        st.write("")
        new_pass = st.checkbox("代收?", value=False, key="add_meter_pass_v4")

    if st.button("儲存新帳單", type="primary"):
        # 驗證
        if not new_bill_type or new_amount is None or not new_start_date or not new_end_date:
            st.error("「費用類型」、「帳單金額」、「起始日」、「結束日」為必填欄位！")
        elif new_start_date > new_end_date:
            st.error("「起始日」不能晚於「結束日」！")
        else:
            details = {
                "dorm_id": dorm_id,
                "meter_id": selected_meter_id,
                "bill_type": new_bill_type,
                "amount": int(new_amount),
                "usage_amount": new_usage if new_usage > 0 else None,
                "peak_usage": new_peak if new_peak > 0 else None,
                "sat_half_peak_usage": new_sat_sp if new_sat_sp > 0 else None,
                "off_peak_usage": new_off_peak if new_off_peak > 0 else None,
                "bill_start_date": new_start_date,
                "bill_end_date": new_end_date,
                "payer": new_payer,
                "is_pass_through": new_pass,
                "is_invoiced": False,
                "notes": new_notes
            }
            with st.spinner("正在新增..."):
                success, message, _ = finance_model.add_bill_record(details)
            
            if success:
                st.success(message)
                st.cache_data.clear()
                # 清除 session
                keys_to_clear = [
                    'add_meter_type_v4', 'add_meter_amount_v4', 'add_meter_start_v4', 'add_meter_end_v4',
                    'add_meter_peak_v4', 'add_meter_sat_sp_v4', 'add_meter_off_v4', 'add_meter_usage_v4', 
                    'add_meter_payer_v4', 'add_meter_pass_v4', 'add_meter_notes_v4'
                ]
                for k in keys_to_clear:
                    if k in st.session_state: del st.session_state[k]
                st.rerun()
            else:
                st.error(message)
    st.markdown("---")
    # ==========================================
    # 4. 帳單總覽與批次編輯
    # ==========================================
    st.subheader("帳單總覽 (可批次編輯/刪除)")
    @st.cache_data
    def get_bills_for_editor(meter_id):
        # 呼叫後端函式
        return finance_model.get_bills_for_editor(meter_id)

    bills_df = get_bills_for_editor(selected_meter_id)
    # ==================== [排序邏輯] ====================
    if not bills_df.empty and 'bill_start_date' in bills_df.columns:
        # 依照「帳單起始日」排序
        # ascending=False : 降冪排序 (日期越新的在越上面，推薦使用)
        # ascending=True  : 升冪排序 (日期越舊的在越上面)
        bills_df = bills_df.sort_values(by='bill_start_date', ascending=False)
    # =======================================================

    with st.form("bill_editor_form"):
        edited_df = st.data_editor(
            bills_df,
            key=f"bill_editor_{selected_meter_id}",
            width="stretch",
            hide_index=True,
            num_rows="dynamic", 
            column_config={
                "id": st.column_config.NumberColumn("ID", disabled=True),
                "bill_type": st.column_config.SelectboxColumn("類型", options=bill_type_options_add, required=True),
                "amount": st.column_config.NumberColumn("金額", min_value=0, step=100, format="%d", required=True),
                
                "peak_usage": st.column_config.NumberColumn("尖峰", min_value=0.0, format="%.2f"),
                "sat_half_peak_usage": st.column_config.NumberColumn("半尖峰", min_value=0.0, format="%.2f"),
                "off_peak_usage": st.column_config.NumberColumn("離峰", min_value=0.0, format="%.2f"),
                "usage_amount": st.column_config.NumberColumn("總用量", min_value=0.0, format="%.2f"),
                
                "bill_start_date": st.column_config.DateColumn("起始日", format="YYYY-MM-DD", required=True),
                "bill_end_date": st.column_config.DateColumn("結束日", format="YYYY-MM-DD", required=True),
                "payer": st.column_config.SelectboxColumn("支付方", options=payer_options_add, default="我司", required=True),
                "is_pass_through": st.column_config.CheckboxColumn("代收代付?", default=False),
                "is_invoiced": st.column_config.CheckboxColumn("已請款?", default=False),
                "notes": st.column_config.TextColumn("備註")
            },
            column_order=[
                "id", "bill_type", "amount", 
                "peak_usage", "sat_half_peak_usage", "off_peak_usage", "usage_amount", 
                "bill_start_date", "bill_end_date", 
                "payer", "is_pass_through", "is_invoiced", "notes"
            ]
        )
        
        submitted = st.form_submit_button("🚀 儲存表格變更") 
        if submitted:
            with st.spinner("正在同步帳單資料..."):
                success, message = finance_model.batch_sync_bills(
                    selected_meter_id, 
                    dorm_id, 
                    edited_df
                )
            
            if success:
                st.success(message)
                st.cache_data.clear() 
                st.rerun()
            else:
                st.error(message)
    st.info(
        """
        - **編輯**：直接在表格中修改資料。
        - **刪除**：點擊該列最左側的 `▢` 並於右上角選擇 `🗑`。
        """
    ) 

