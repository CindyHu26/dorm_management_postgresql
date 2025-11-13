# views/meter_expense_view.py

import streamlit as st
import pandas as pd
from datetime import date
from data_models import finance_model, dormitory_model, meter_model

def render():
    """渲染「錶號費用管理」頁面 (DataEditor 模式)"""
    st.header("錶號費用管理")
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
    @st.cache_data
    def get_context_details(meter_id):
        dorm_id = meter_model.get_dorm_id_from_meter_id(meter_id)
        if not dorm_id:
            return None, None
        dorm_details = dormitory_model.get_dorm_details_by_id(dorm_id)
        # --- 在這裡同時獲取錶號的詳細資料 ---
        meter_details = meter_model.get_single_meter_details(meter_id)
        return dorm_id, dorm_details, meter_details

    dorm_id, dorm_details, meter_details = get_context_details(selected_meter_id) # <--- 取得 meter_details
    
    if not dorm_id or not dorm_details or not meter_details:
        st.error("發生錯誤：找不到此錶號關聯的宿舍或錶號本身資料。")
        return
        
    st.markdown("---")
    with st.container(border=True):
        st.subheader(f"目前操作對象: {meter_options[selected_meter_id]}")
        col1, col2 = st.columns(2)
        col1.info(f"**宿舍編號:** {dorm_details.get('legacy_dorm_code') or '未設定'}")
        col2.info(f"**變動費用備註:** {dorm_details.get('utility_bill_notes') or '無'}")

    st.markdown("---")
    
    # 準備選項
    bill_type_options_add = ["電費", "水費", "天然氣", "網路費", "子母車", "清潔", "瓦斯費"]
    payer_options_add = ["我司", "雇主", "工人"]
    default_payer = dorm_details.get('utilities_payer', '我司')
    try:
        default_payer_index = payer_options_add.index(default_payer)
    except ValueError:
        default_payer_index = 0

    # --- 根據錶號類型決定預設費用類型 ---
    meter_type_to_bill_type_map = {
        "電錶": "電費",
        "水錶": "水費",
        "天然氣": "天然氣",
        "電信": "網路費"
    }
    current_meter_type = meter_details.get("meter_type")
    default_bill_type = meter_type_to_bill_type_map.get(current_meter_type, bill_type_options_add[0]) # 預設電費
    
    try:
        default_bill_type_index = bill_type_options_add.index(default_bill_type)
    except ValueError:
        default_bill_type_index = 0 # 預設電費

    with st.expander("➕ 快速新增最新一筆帳單 (推薦)"):
        with st.form("new_bill_form_v3", clear_on_submit=False):

            # 準備一個只有一行的 DataFrame
            new_bill_template = pd.DataFrame(
                [
                    {
                        "bill_type": bill_type_options_add[default_bill_type_index],
                        "amount": None,
                        "usage_amount": None,
                        "bill_start_date": None,
                        "bill_end_date": date.today(),
                        "payer": payer_options_add[default_payer_index],
                        "is_pass_through": False,
                        "notes": ""
                    }
                ]
            )

            # 使用 st.data_editor 顯示這一行
            new_bill_editor_data = st.data_editor(
                new_bill_template,
                key=f"new_bill_editor_{selected_meter_id}",
                hide_index=True,
                num_rows="fixed", # 固定只有一行
                column_config={
                    "bill_type": st.column_config.SelectboxColumn(
                        "費用類型*", options=bill_type_options_add, required=True
                    ),
                    "amount": st.column_config.NumberColumn(
                        "帳單金額*", min_value=0, step=100, format="%d", required=True
                    ),
                    "usage_amount": st.column_config.NumberColumn(
                        "用量(度/噸)", min_value=0.0, format="%.2f"
                    ),
                    "bill_start_date": st.column_config.DateColumn(
                        "帳單起始日*", format="YYYY-MM-DD", required=True
                    ),
                    "bill_end_date": st.column_config.DateColumn(
                        "帳單結束日*", format="YYYY-MM-DD", required=True
                    ),
                    "payer": st.column_config.SelectboxColumn(
                        "支付方*", options=payer_options_add, required=True
                    ),
                    "is_pass_through": st.column_config.CheckboxColumn("代收代付?"),
                    "notes": st.column_config.TextColumn("備註")
                }
            )

            new_submitted = st.form_submit_button("儲存新帳單")
            if new_submitted:
                new_row = new_bill_editor_data.iloc[0]
                
                raw_start_date = new_row["bill_start_date"]
                raw_end_date = new_row["bill_end_date"]

                if pd.isna(new_row["bill_type"]) or pd.isna(new_row["amount"]) or pd.isna(raw_start_date) or pd.isna(raw_end_date):
                    st.error("「費用類型」、「帳單金額」、「起始日」、「結束日」為必填欄位！")
                else:
                    try:
                        start_date_obj = pd.to_datetime(raw_start_date).date()
                        end_date_obj = pd.to_datetime(raw_end_date).date()
                        
                        if start_date_obj > end_date_obj:
                            st.error("「起始日」不能晚於「結束日」！")
                        else:
                            details = {
                                "dorm_id": dorm_id,
                                "meter_id": selected_meter_id,
                                "bill_type": new_row["bill_type"],
                                "amount": int(new_row["amount"]),
                                "usage_amount": float(new_row["usage_amount"]) if pd.notna(new_row["usage_amount"]) else None,
                                "bill_start_date": start_date_obj,
                                "bill_end_date": end_date_obj,
                                "payer": new_row["payer"],
                                "is_pass_through": bool(new_row["is_pass_through"]),
                                "is_invoiced": False, 
                                "notes": new_row["notes"]
                            }
                            
                            with st.spinner("正在新增..."):
                                success, message, _ = finance_model.add_bill_record(details) 
                            
                            if success:
                                st.success(message)
                                st.cache_data.clear() 
                                st.rerun()
                            else:
                                st.error(message)
                    except Exception as e:
                        st.error(f"日期格式錯誤或轉換失敗：{e}")

    st.markdown("---")
    
    # --- 3. 帳單總覽 (維持不變) ---
    st.subheader("帳單總覽 (可批次編輯/刪除)")
    st.info(
        """
        - **編輯**：直接在表格中修改資料。
        - **新增**：點擊表格底部的 `+` 按鈕新增一列。
        - **刪除**：點擊該列最左側的 `▢` 並於右上角選擇 `🗑`。
        """
    ) 

    @st.cache_data
    def get_bills_for_editor(meter_id):
        return finance_model.get_bills_for_editor(meter_id)

    bills_df = get_bills_for_editor(selected_meter_id)

    bill_type_options = ["電費", "水費", "天然氣", "網路費", "子母車", "清潔", "瓦斯費"]
    payer_options = ["我司", "雇主", "工人"]

    with st.form("bill_editor_form"):
        edited_df = st.data_editor(
            bills_df,
            key=f"bill_editor_{selected_meter_id}",
            width="stretch",
            hide_index=True,
            num_rows="dynamic", 
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
        
        submitted = st.form_submit_button("🚀 儲存下方表格的所有變更") 
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