# 檔案: views/expense_view.py
# (v2.0 - DataEditor 模式)

import streamlit as st
import pandas as pd
from datetime import datetime, date
from data_models import finance_model, dormitory_model, meter_model
import numpy as np # <-- 【請確保此行存在】

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
        key="selected_dorm_id_expense" # 使用一個獨立的 key
    )

    if not selected_dorm_id:
        return

    st.markdown("---")

    # --- 【核心修改】---
    st.subheader(f"帳單紀錄: {dorm_options.get(selected_dorm_id)}")
    st.info(
        """
        - **編輯**：直接在表格中修改資料。
        - **新增**：點擊表格底部的 `+` 按鈕新增一列。
        - **刪除**：點擊該列最左側的 `▢` 並於右上角選擇 `🗑`。
        """
    )
    if st.button("🔄 重新整理帳單列表"):
        st.cache_data.clear()
        st.rerun()

    # 載入 data_editor 所需的資料
    @st.cache_data
    def get_bills_data_for_editor(dorm_id):
        # 呼叫我們新增的函式
        return finance_model.get_bills_for_dorm_editor(dorm_id)

    bills_df = get_bills_data_for_editor(selected_dorm_id)

    # 準備下拉選單的選項
    @st.cache_data
    def get_meter_options(dorm_id):
        meters_for_selection = meter_model.get_meters_for_selection(dorm_id)
        # 建立 {id: '類型 (錶號)'} 的字典
        return {m['id']: m.get('display_name', '未知錶號') for m in meters_for_selection}
    
    meter_options = get_meter_options(selected_dorm_id)
    
    @st.cache_data
    def get_dorm_payer(dorm_id):
        dorm_details = dormitory_model.get_dorm_details_by_id(dorm_id)
        # 取得宿舍預設的水電支付方
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
            num_rows="dynamic", # 允許新增和刪除
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
                    default=default_payer, # 使用宿舍的預設值
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
        
        submitted = st.form_submit_button("🚀 儲存所有帳單變更")
        if submitted:
            with st.spinner("正在同步宿舍所有帳單資料..."):
                # 呼叫新的後端函式
                success, message = finance_model.batch_sync_dorm_bills(selected_dorm_id, edited_df)
            
            if success:
                st.success(message)
                st.cache_data.clear() # 清除所有快取
                st.rerun()
            else:
                st.error(message)