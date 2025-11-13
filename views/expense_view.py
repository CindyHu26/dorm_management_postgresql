# 檔案: views/expense_view.py
# (v2.0 - DataEditor 模式)
# (v3.0 - 快速新增表單改為 V6 - 移除 Expander 和 Form，實現動態連動)

import streamlit as st
import pandas as pd
from datetime import datetime, date
from data_models import finance_model, dormitory_model, meter_model
import numpy as np 
from dateutil.relativedelta import relativedelta 

def render():
    """渲染「費用管理」頁面 (DataEditor 模式)"""
    st.header("我司管理宿舍 - 費用帳單管理")
    st.info("用於登錄每一筆獨立的水電、網路等費用帳單，系統將根據帳單起訖日自動計算每月攤分費用。")

    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍。")
        return

    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}
    
    selected_dorm_id = st.selectbox(
        "請選擇要管理的宿舍：",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options.get(x, "未知宿舍"),
        key="selected_dorm_id_expense" 
    )

    if not selected_dorm_id:
        return

    st.markdown("---")

    # --- 1. 準備選項與回呼函式 ---
    st.subheader("➕ 快速新增最新一筆帳單") # <-- 移除 Expander

    bill_type_options_add = ["電費", "水費", "天然氣", "網路費", "子母車", "清潔", "瓦斯費"]
    payer_options_add = ["我司", "雇主", "工人"]

    @st.cache_data
    def get_meter_list_raw(dorm_id):
        return meter_model.get_meters_for_selection(dorm_id)
    
    meter_list_raw = get_meter_list_raw(selected_dorm_id)

    @st.cache_data
    def get_dorm_payer_for_add(dorm_id):
        dorm_details = dormitory_model.get_dorm_details_by_id(dorm_id)
        return dorm_details.get('utilities_payer', '我司') if dorm_details else '我司'

    default_payer_add = get_dorm_payer_for_add(selected_dorm_id)
    try:
        default_payer_index_add = payer_options_add.index(default_payer_add)
    except ValueError:
        default_payer_index_add = 0

    # --- 2. 定義日期自動計算的回呼 (Callback) ---
    def update_end_date():
        """
        當「費用類型」或「起始日」改變時觸發此函式。
        自動計算結束日期。
        """
        start_date = st.session_state.get('add_start_date_v6')
        bill_type = st.session_state.get('add_bill_type_v6')
        
        if start_date and bill_type in ["電費", "水費"]:
            try:
                # 計算：起始日 + 2個月
                st.session_state.add_end_date_v6 = start_date + relativedelta(months=2)
            except Exception as e:
                print(f"Error calculating end date: {e}")
                st.session_state.add_end_date_v6 = date.today()
        # (如果不是電費或水費，我們不主動修改結束日期，讓使用者自行填寫)

    # --- 3. 初始化 Session State (如果不存在) ---
    # (使用 v6 結尾以避免與舊 session 衝突)
    if 'add_bill_type_v6' not in st.session_state:
        st.session_state.add_bill_type_v6 = bill_type_options_add[0]
    if 'add_start_date_v6' not in st.session_state:
        st.session_state.add_start_date_v6 = None
    if 'add_end_date_v6' not in st.session_state:
        st.session_state.add_end_date_v6 = date.today()


    # --- 4. 直接渲染元件 (不使用 st.form) ---
    
    c1, c2, c3 = st.columns(3)
    
    # 費用類型 (會觸發回呼)
    new_bill_type = c1.selectbox(
        "費用類型*", 
        options=bill_type_options_add, 
        key="add_bill_type_v6", # 使用新 key
        on_change=update_end_date 
    )
    
    new_amount = c2.number_input("帳單金額*", min_value=0, step=100, value=None, placeholder="請輸入金額...", key="add_amount_v6")

    # 動態過濾電水錶選項
    selected_bill_type_from_state = st.session_state.add_bill_type_v6
    
    if selected_bill_type_from_state == "電費":
        meter_map_key = '電錶'
    elif selected_bill_type_from_state == "水費":
        meter_map_key = '水錶'
    else:
        meter_map_key = None 

    if meter_map_key:
        filtered_meters = {m['id']: m['display_name'] for m in meter_list_raw if m['meter_type'] == meter_map_key}
        st.caption(f"已自動篩選「{meter_map_key}」類型的錶號。")
    else:
        filtered_meters = {m['id']: m['display_name'] for m in meter_list_raw}

    new_meter_id = c3.selectbox(
        "對應電水錶 (選填)", 
        options=[None] + list(filtered_meters.keys()),
        format_func=lambda x: "無 (整棟總計)" if x is None else filtered_meters.get(x, "未知錶號"),
        key="add_meter_id_v6"
    )

    c4, c5 = st.columns(2)
    
    # 起始日 (會觸發回呼)
    new_start_date = c4.date_input(
        "帳單起始日*", 
        value=st.session_state.add_start_date_v6, 
        key="add_start_date_v6",
        on_change=update_end_date
    )
    
    # 結束日 (會被回呼更新)
    new_end_date = c5.date_input(
        "帳單結束日*", 
        key="add_end_date_v6" 
    )
    
    c6, c7, c8 = st.columns(3)
    new_usage = c6.number_input("用量(度/噸)", min_value=0.0, step=0.01, value=None, placeholder="選填...", key="add_usage_v6")
    new_payer = c7.selectbox("支付方*", options=payer_options_add, index=default_payer_index_add, key="add_payer_v6")
    new_pass_through = c8.checkbox("代收代付?", value=False, help="此帳單是否僅為代收，不計入損益", key="add_pass_through_v6")
    
    new_notes = st.text_area("備註 (選填)", key="add_notes_v6")

    new_submitted = st.button("儲存新帳單", type="primary")
    
    if new_submitted:
        # --- 讀取 session_state 中的值 ---
        bill_type_val = st.session_state.add_bill_type_v6
        amount_val = st.session_state.add_amount_v6
        meter_id_val = st.session_state.add_meter_id_v6
        usage_val = st.session_state.add_usage_v6
        start_date_val = st.session_state.add_start_date_v6
        end_date_val = st.session_state.add_end_date_v6
        payer_val = st.session_state.add_payer_v6
        pass_through_val = st.session_state.add_pass_through_v6
        notes_val = st.session_state.add_notes_v6
        
        # --- 驗證 ---
        if not bill_type_val or amount_val is None or not start_date_val or not end_date_val:
            st.error("「費用類型」、「帳單金額」、「起始日」、「結束日」為必填欄位！")
        elif start_date_val > end_date_val:
            st.error("「起始日」不能晚於「結束日」！")
        else:
            details = {
                "dorm_id": selected_dorm_id,
                "meter_id": meter_id_val, 
                "bill_type": bill_type_val,
                "amount": amount_val,
                "usage_amount": usage_val,
                "bill_start_date": start_date_val,
                "bill_end_date": end_date_val,
                "payer": payer_val,
                "is_pass_through": bool(pass_through_val), # 修復 numpy.bool 錯誤
                "is_invoiced": False, 
                "notes": notes_val
            }
            
            with st.spinner("正在新增..."):
                success, message, _ = finance_model.add_bill_record(details) 
            
            if success:
                st.success(message)
                st.cache_data.clear() 
                # 清除 session state
                keys_to_delete = [
                    'add_bill_type_v6', 'add_amount_v6', 'add_meter_id_v6', 'add_usage_v6',
                    'add_start_date_v6', 'add_end_date_v6', 'add_payer_v6', 
                    'add_pass_through_v6', 'add_notes_v6'
                ]
                for key in keys_to_delete:
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()
            else:
                st.error(message)

    st.subheader(f"帳單總覽: {dorm_options.get(selected_dorm_id)}")
    st.info(
        """
        - **編輯**：直接在表格中修改資料。
        - **新增**：點擊表格底部的 `+` 按鈕新增一列。(日期選單為中文)
        - **刪除**：點擊該列最左側的 `▢` 並於右上角選擇 `🗑`。
        """
    ) 
    if st.button("🔄 重新整理帳單列表"):
        st.cache_data.clear()
        st.rerun()

    # 載入 data_editor 所需的資料
    @st.cache_data
    def get_bills_data_for_editor(dorm_id):
        return finance_model.get_bills_for_dorm_editor(dorm_id)

    bills_df = get_bills_data_for_editor(selected_dorm_id)

    # 準備下拉選單的選項
    @st.cache_data
    def get_meter_options(dorm_id):
        meters_for_selection = meter_model.get_meters_for_selection(dorm_id)
        return {m['id']: m.get('display_name', '未知錶號') for m in meters_for_selection}
    
    meter_options = get_meter_options(selected_dorm_id)
    
    @st.cache_data
    def get_dorm_payer(dorm_id):
        dorm_details = dormitory_model.get_dorm_details_by_id(dorm_id)
        return dorm_details.get('utilities_payer', '我司') if dorm_details else '我司'

    default_payer = get_dorm_payer(selected_dorm_id)
    
    bill_type_options = ["電費", "水費", "天然氣", "網路費", "子母車", "清潔", "瓦斯費"]
    payer_options = ["我司", "雇主", "工人"]

    with st.form("dorm_bill_editor_form"):
        edited_df = st.data_editor(
            bills_df,
            key=f"dorm_bill_editor_{selected_dorm_id}",
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "id": st.column_config.NumberColumn(
                    "ID", 
                    disabled=True,
                    help="由系統自動產生"
                ),
                "meter_id": st.column_config.SelectboxColumn(
                    "對應電水錶",
                    options=list(meter_options.keys()),
                    format_func=lambda x: meter_options.get(int(x), "無 (整棟總計)") if pd.notna(x) and x != 0 else "無 (整棟總計)",
                    required=False,
                    help="可選。將此帳單關聯到一個特定錶號。"
                ),
                "bill_type": st.column_config.SelectboxColumn(
                    "費用類型",
                    options=bill_type_options,
                    required=True,
                    help="若為 '其他'，請直接輸入文字"
                ),
                "amount": st.column_config.NumberColumn(
                    "帳單金額",
                    min_value=0, step=100, format="%d", required=True
                ),
                "usage_amount": st.column_config.NumberColumn(
                    "用量(度/噸)", min_value=0.0, format="%.2f", help="選填"
                ),
                "bill_start_date": st.column_config.DateColumn(
                    "帳單起始日", format="YYYY-MM-DD", required=True
                ),
                "bill_end_date": st.column_config.DateColumn(
                    "帳單結束日", format="YYYY-MM-DD", required=True
                ),
                "payer": st.column_config.SelectboxColumn(
                    "支付方",
                    options=payer_options,
                    default=default_payer, 
                    required=True
                ),
                "is_pass_through": st.column_config.CheckboxColumn(
                    "代收代付?", default=False
                ),
                "is_invoiced": st.column_config.CheckboxColumn(
                    "已請款?", default=False
                ),
                "notes": st.column_config.TextColumn("備註")
            }
        )
        
        submitted = st.form_submit_button("🚀 儲存下方表格的所有變更")
        if submitted:
            with st.spinner("正在同步宿舍所有帳單資料..."):
                success, message = finance_model.batch_sync_dorm_bills(selected_dorm_id, edited_df)
            
            if success:
                st.success(message)
                st.cache_data.clear() 
                st.rerun()
            else:
                st.error(message)