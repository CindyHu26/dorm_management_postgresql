# 檔案: views/expense_view.py
# (v5.0 - 版面調整：總覽在上、新增在下；度數改為整數)

import streamlit as st
import pandas as pd
from datetime import datetime, date
from data_models import finance_model, dormitory_model, meter_model
import numpy as np 
from dateutil.relativedelta import relativedelta 

def render():
    """渲染「費用管理」頁面 (DataEditor 模式)"""
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

    # ==========================================
    # 1. 帳單總覽與批次編輯 (移至上方)
    # ==========================================
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
                "peak_usage": st.column_config.NumberColumn(
                    "尖峰度數", min_value=0.0, format="%.2f"
                ),
                "sat_half_peak_usage": st.column_config.NumberColumn(
                    "週六半尖峰", min_value=0.0, format="%.2f"
                ),
                "off_peak_usage": st.column_config.NumberColumn(
                    "離峰度數", min_value=0.0, format="%.2f"
                ),
                "usage_amount": st.column_config.NumberColumn(
                    "總用量(度/噸)", min_value=0.0, format="%.2f", help="若有輸入尖峰/離峰，此為加總值"
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
            },
            column_order=[
                "id", "meter_id", "bill_type", "amount", 
                "peak_usage", "sat_half_peak_usage", "off_peak_usage", "usage_amount", 
                "bill_start_date", "bill_end_date", "payer", 
                "is_pass_through", "is_invoiced", "notes"
            ]
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

    st.markdown("---")

    # ==========================================
    # 2. 快速新增區塊 (移至下方)
    # ==========================================
    st.subheader("➕ 快速新增最新一筆帳單") 

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

    # --- 定義回呼函式 (Callbacks) ---

    def update_end_date():
        """當「費用類型」或「起始日」改變時，自動計算預設結束日期"""
        start_date = st.session_state.get('add_start_date_v6')
        bill_type = st.session_state.get('add_bill_type_v6')
        
        if start_date and bill_type in ["電費", "水費"]:
            try:
                # 預設 +2 個月
                st.session_state.add_end_date_v6 = start_date + relativedelta(months=2)
            except Exception as e:
                print(f"Error calculating end date: {e}")
                st.session_state.add_end_date_v6 = date.today()

    def auto_sum_usage():
        """當尖峰或離峰度數改變時，自動更新總用量"""
        p = st.session_state.get('add_peak_v6') or 0
        op = st.session_state.get('add_off_peak_v6') or 0
        sp = st.session_state.get('add_sat_sp_v6') or 0
        
        # 只要任一欄位有值，就自動計算總和
        if p > 0 or op > 0 or sp > 0:
            st.session_state.add_usage_v6 = int(p + op + sp)

    # --- 初始化 Session State (如果不存在) ---
    if 'add_bill_type_v6' not in st.session_state: st.session_state.add_bill_type_v6 = bill_type_options_add[0]
    if 'add_start_date_v6' not in st.session_state: st.session_state.add_start_date_v6 = None
    if 'add_end_date_v6' not in st.session_state: st.session_state.add_end_date_v6 = date.today()
    
    # 新增尖峰/離峰的 state (預設為 0 整數)
    if 'add_peak_v6' not in st.session_state: st.session_state.add_peak_v6 = 0
    if 'add_sat_sp_v6' not in st.session_state: st.session_state.add_sat_sp_v6 = 0
    if 'add_off_peak_v6' not in st.session_state: st.session_state.add_off_peak_v6 = 0
    if 'add_usage_v6' not in st.session_state: st.session_state.add_usage_v6 = 0


    # --- 渲染元件 ---
    
    # 第一排：基本資訊
    c1, c2, c3 = st.columns(3)
    
    new_bill_type = c1.selectbox(
        "費用類型*", 
        options=bill_type_options_add, 
        key="add_bill_type_v6", 
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

    # 第二排：日期
    c4, c5 = st.columns(2)
    new_start_date = c4.date_input(
        "帳單起始日*", 
        value=st.session_state.add_start_date_v6, 
        key="add_start_date_v6",
        on_change=update_end_date
    )
    new_end_date = c5.date_input("帳單結束日*", key="add_end_date_v6")
    
    # 第三排：用量資訊 (改為整數輸入)
    st.markdown("##### 用量資訊 (整數)")
    u1, u2, u3 = st.columns(3)
    
    new_peak = u1.number_input(
        "尖峰度數", min_value=0, step=1, 
        key="add_peak_v6", on_change=auto_sum_usage
    )
    new_sat_sp = u2.number_input(
        "週六半尖峰", min_value=0, step=1, 
        key="add_sat_sp_v6", on_change=auto_sum_usage
    )
    new_off_peak = u2.number_input(
        "離峰度數", min_value=0, step=1, 
        key="add_off_peak_v6", on_change=auto_sum_usage
    )
    
    new_usage = u3.number_input(
        "總用量 (度/噸)*", min_value=0, step=1, 
        key="add_usage_v6", help="若填寫尖峰/離峰，此欄位會自動加總，也可手動修改。"
    )

    # 第四排：其他資訊
    st.markdown("##### 其他資訊")
    c6, c7, c8 = st.columns(3)
    new_payer = c6.selectbox("支付方*", options=payer_options_add, index=default_payer_index_add, key="add_payer_v6")
    new_pass_through = c7.checkbox("代收代付?", value=False, help="此帳單是否僅為代收，不計入損益", key="add_pass_through_v6")
    # c8 留空或放其他
    
    new_notes = st.text_area("備註 (選填)", key="add_notes_v6")

    new_submitted = st.button("儲存新帳單", type="primary")
    
    if new_submitted:
        # --- 讀取 session_state 中的值 ---
        bill_type_val = st.session_state.add_bill_type_v6
        amount_val = st.session_state.add_amount_v6
        meter_id_val = st.session_state.add_meter_id_v6
        
        usage_val = st.session_state.add_usage_v6
        peak_val = st.session_state.add_peak_v6
        sat_sp_val = st.session_state.add_sat_sp_v6
        off_peak_val = st.session_state.add_off_peak_v6
        
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
                
                # 轉為 float 存入資料庫 (雖然前端限制整數，但後端欄位是 numeric)
                "usage_amount": float(usage_val) if usage_val > 0 else None,
                "peak_usage": float(peak_val) if peak_val > 0 else None,
                "sat_half_peak_usage": float(sat_sp_val) if sat_sp_val > 0 else None,
                "off_peak_usage": float(off_peak_val) if off_peak_val > 0 else None,
                
                "bill_start_date": start_date_val,
                "bill_end_date": end_date_val,
                "payer": payer_val,
                "is_pass_through": bool(pass_through_val),
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
                    'add_bill_type_v6', 'add_amount_v6', 'add_meter_id_v6', 
                    'add_usage_v6', 'add_peak_v6', 'add_sat_sp_v6', 'add_off_peak_v6',
                    'add_start_date_v6', 'add_end_date_v6', 'add_payer_v6', 
                    'add_pass_through_v6', 'add_notes_v6'
                ]
                for key in keys_to_delete:
                    if key in st.session_state:
                        del st.session_state[key]
                st.rerun()
            else:
                st.error(message)