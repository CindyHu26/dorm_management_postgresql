# views/inventory_view.py

import streamlit as st
import pandas as pd
from datetime import date
from data_models import inventory_model, dormitory_model

def render():
    """渲染「資產與庫存管理」頁面"""
    st.info("此頁面用於管理公司的庫存品項（如床墊、鑰匙），並追蹤其採購、發放、借還的流動紀錄。")

    dorms = dormitory_model.get_dorms_for_selection()
    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms} if dorms else {}

    tab1, tab2, tab3 = st.tabs(["📦 品項總覽與庫存管理", "📜 歷史異動紀錄", "⚡ 批次帳務處理"])

    with tab1:
        with st.expander("➕ 新增庫存品項"):
            with st.form("new_item_form", clear_on_submit=True):
                st.subheader("新品項基本資料")
                c1, c2, c3 = st.columns(3)
                item_name = c1.text_input("品項名稱 (必填，如: 單人床墊)")
                item_category = c2.text_input("分類 (如: 傢俱, 鑰匙, 消耗品)")
                dorm_id = c3.selectbox("關聯宿舍 (選填，如鑰匙)", options=[None] + list(dorm_options.keys()), format_func=lambda x: "無 (通用資產)" if x is None else dorm_options.get(x))
                
                c4, c5, c6 = st.columns(3)
                unit_cost = c4.number_input("成本單價 (選填)", min_value=0, value=None, step=1, format="%d", help="若不確定成本可留空")
                selling_price = c5.number_input("建議售價 (選填)", min_value=0, value=None, step=1, format="%d", help="若此物品不出售可留空")
                specifications = c6.text_input("規格/型號")
                
                notes = st.text_area("品項備註")

                if st.form_submit_button("儲存新品項"):
                    if not item_name:
                        st.error("「品項名稱」為必填欄位！")
                    else:
                        details = {
                            'item_name': item_name, 'item_category': item_category,
                            'dorm_id': dorm_id,
                            'unit_cost': unit_cost,
                            'selling_price': selling_price,
                            'specifications': specifications, 'notes': notes
                        }
                        success, message = inventory_model.add_inventory_item(details)
                        if success: st.success(message); st.rerun()
                        else: st.error(message)

        st.markdown("---")
        st.subheader("庫存品項總覽")
        search_term = st.text_input("搜尋品項 (可輸入名稱、分類或宿舍地址)")
        
        items_df = inventory_model.get_all_inventory_items(search_term)
        st.dataframe(items_df, width='stretch', hide_index=True, column_config={
            "id": None,
            "成本單價": st.column_config.NumberColumn(format="NT$ %d"),
            "建議售價": st.column_config.NumberColumn(format="NT$ %d"),
        })
        
        st.markdown("---")
        st.subheader("編輯 / 刪除單筆品項")
        if not items_df.empty:
            options_dict = {row['id']: f"ID:{row['id']} - {row['品項名稱']} (庫存: {row['目前庫存']})" for _, row in items_df.iterrows()}
            selected_item_id_edit = st.selectbox("選擇要操作的品項", options=[None] + list(options_dict.keys()), format_func=lambda x: "請選擇..." if x is None else options_dict.get(x))

            if selected_item_id_edit:
                details = inventory_model.get_single_item_details(selected_item_id_edit)
                with st.form(f"edit_item_form_{selected_item_id_edit}"):
                    st.markdown(f"###### 正在編輯 ID: {selected_item_id_edit} 的品項")
                    ec1, ec2, ec3 = st.columns(3)
                    e_item_name = ec1.text_input("品項名稱", value=details.get('item_name'))
                    e_item_category = ec2.text_input("分類", value=details.get('item_category'))
                    current_dorm_id = details.get('dorm_id')
                    e_dorm_id = ec3.selectbox("關聯宿舍 (選填)", options=[None] + list(dorm_options.keys()), format_func=lambda x: "無 (通用資產)" if x is None else dorm_options.get(x), index=([None] + list(dorm_options.keys())).index(current_dorm_id) if current_dorm_id in [None] + list(dorm_options.keys()) else 0)
                    
                    ec4, ec5, ec6 = st.columns(3)
                    current_unit_cost = details.get('unit_cost') # 可能為 None 或 0 或 其他數字
                    e_unit_cost = ec4.number_input("成本單價", min_value=0, value=current_unit_cost, step=1, format="%d", help="若不確定成本可留空或填0")
                    current_selling_price = details.get('selling_price')
                    e_selling_price = ec5.number_input("建議售價", min_value=0, value=current_selling_price, step=1, format="%d", help="若此物品不出售可留空或填0")
                    e_specifications = ec6.text_input("規格/型號", value=details.get('specifications'))
                    
                    e_notes = st.text_area("品項備註", value=details.get('notes'))

                    if st.form_submit_button("儲存變更"):
                        update_data = {
                            'item_name': e_item_name, 'item_category': e_item_category,
                            'dorm_id': e_dorm_id,
                            'unit_cost': e_unit_cost, 
                            'selling_price': e_selling_price,
                            'specifications': e_specifications, 'notes': e_notes
                        }
                        success, message = inventory_model.update_inventory_item(selected_item_id_edit, update_data)
                        if success: st.success(message); st.rerun()
                        else: st.error(message)

                if st.checkbox(f"我確認要刪除 ID:{selected_item_id_edit} 這個品項及其所有歷史紀錄"):
                    if st.button("刪除此品項", type="primary"):
                        success, message = inventory_model.delete_inventory_item(selected_item_id_edit)
                        if success: st.success(message); st.rerun()
                        else: st.error(message)
    
    with tab2:
        st.subheader("新增庫存異動")
        
        all_items_df_for_log = inventory_model.get_all_inventory_items()
        if all_items_df_for_log.empty:
            st.warning("請先在「品項總覽」頁籤建立至少一個庫存品項，才能新增異動紀錄。")
        else:
            item_options = {row['id']: row['品項名稱'] for _, row in all_items_df_for_log.iterrows()}
            
            with st.form("new_log_form", clear_on_submit=True):
                st.info(
                    """
                    - **採購**：若品項已設定「成本單價」，系統將自動新增一筆費用紀錄至「年度費用」中。
                    - **售出**：若品項已設定「建議售價」，稍後可將此紀錄一鍵轉為「其他收入」。
                    - **關聯宿舍**：若為總務採購進貨至總倉，此處請留空，成本將歸屬於公司總部。
                    """
                )
                c1, c2, c3 = st.columns(3)
                log_item_id = c1.selectbox("選擇品項", options=item_options.keys(), format_func=lambda x: item_options.get(x), index=None, placeholder="請選擇...")

                log_type = c2.selectbox("異動類型", ["採購", "發放", "售出", "借出", "歸還", "報廢"])
                log_date = c3.date_input("異動日期", value=date.today())
                log_quantity = st.number_input("數量", min_value=1, step=1)
                log_dorm_id = st.selectbox("關聯宿舍 (選填)", options=[None] + list(dorm_options.keys()), format_func=lambda x: "不指定 (歸屬總公司)" if x is None else dorm_options.get(x), help="在「採購」、「發放」或「售出」時可指定宿舍。")
                log_person = st.text_input("收受/經手人 (選填)", help="在「發放」、「售出」、「借出」、「歸還」或「採購」時可填寫相關人員。")
                log_notes = st.text_area("異動備註")

                if st.form_submit_button("儲存異動紀錄"):
                    if not log_item_id: st.error("請務必選擇一個品項！")
                    else:
                        quantity_change = log_quantity if log_type in ["採購", "歸還"] else -log_quantity
                        details = {
                            'item_id': log_item_id, 'transaction_type': log_type,
                            'quantity': quantity_change, 'transaction_date': log_date,
                            'dorm_id': log_dorm_id, 'person_in_charge': log_person,
                            'notes': log_notes
                        }
                        success, message = inventory_model.add_inventory_log(details)
                        if success: st.success(message); st.cache_data.clear(); st.rerun()
                        else: st.error(message)

            st.markdown("---")
            st.subheader("查詢歷史紀錄")
            
            log_filter_item_id = st.selectbox("篩選品項以查看其歷史紀錄", options=[None] + list(item_options.keys()), format_func=lambda x: "顯示所有品項" if x is None else item_options.get(x))
            
            if log_filter_item_id: log_df = inventory_model.get_logs_for_item(log_filter_item_id)
            else: log_df = inventory_model.get_all_inventory_logs()

            if not log_df.empty:
                if '已轉費用' in log_df.columns: log_df['已轉費用'] = log_df['已轉費用'].apply(lambda x: f"費用ID: {int(x)}" if pd.notna(x) else "")
                if '已轉收入' in log_df.columns: log_df['已轉收入'] = log_df['已轉收入'].apply(lambda x: f"收入ID: {int(x)}" if pd.notna(x) else "")
            
            st.dataframe(log_df, width='stretch', hide_index=True)

            if not log_df.empty:
                st.markdown("---")
                st.subheader("編輯 / 刪除 / 操作單筆紀錄")
                log_options_dict = {row['id']: f"ID:{row['id']} - {row['異動日期']} {row.get('品項名稱', '')} {row['異動類型']} (數量: {row['數量']})" for _, row in log_df.iterrows()}
                selected_log_id = st.selectbox("選擇要操作的紀錄", options=[None] + list(log_options_dict.keys()), format_func=lambda x: "請選擇..." if x is None else log_options_dict.get(x))
                
                if selected_log_id:
                    details = inventory_model.get_single_log_details(selected_log_id)
                    with st.form(f"edit_log_form_{selected_log_id}"):
                        st.markdown(f"###### 正在編輯 ID: {selected_log_id} 的紀錄")
                        ec1, ec2, ec3 = st.columns(3)
                        current_item_id = details.get('item_id')
                        e_item_id = ec1.selectbox("品項", options=item_options.keys(), format_func=lambda x: item_options.get(x), index=list(item_options.keys()).index(current_item_id) if current_item_id in item_options else 0)
                        # --- 編輯時也加入「售出」選項 ---
                        e_log_type = ec2.selectbox("異動類型", ["採購", "發放", "售出", "借出", "歸還", "報廢"], index=["採購", "發放", "售出", "借出", "歸還", "報廢"].index(details.get('transaction_type')))
                        e_log_date = ec3.date_input("異動日期", value=details.get('transaction_date'))
                        e_quantity = st.number_input("數量", min_value=1, step=1, value=abs(details.get('quantity', 1)))
                        e_dorm_id = st.selectbox("關聯宿舍 (選填)", options=[None] + list(dorm_options.keys()), format_func=lambda x: "不指定" if x is None else dorm_options.get(x), index=([None] + list(dorm_options.keys())).index(details.get('dorm_id')) if details.get('dorm_id') in [None] + list(dorm_options.keys()) else 0, help="在「採購」或「發放」時可指定宿舍。")
                        e_person = st.text_input("收受/經手人 (選填)", value=details.get('person_in_charge') or "", help="在「發放」、「售出」、「借出」、「歸還」或「採購」時可填寫相關人員。")
                        e_notes = st.text_area("異動備註", value=details.get('notes') or "")
                        if st.form_submit_button("儲存變更"):
                            quantity_change = e_quantity if e_log_type in ["採購", "歸還"] else -e_quantity
                            update_details = {'item_id': e_item_id, 'transaction_type': e_log_type, 'quantity': quantity_change, 'transaction_date': e_log_date, 'dorm_id': e_dorm_id, 'person_in_charge': e_person, 'notes': e_notes}
                            success, message = inventory_model.update_inventory_log(selected_log_id, update_details)
                            if success: st.success(message); st.cache_data.clear(); st.rerun()
                            else: st.error(message)

                    st.markdown("---")
                    st.markdown("##### 其他操作")
                    log_details_from_df = log_df.loc[log_df['id'] == selected_log_id].iloc[0]
                    item_id_to_lookup = int(log_details_from_df['item_id'])
                    item_details = inventory_model.get_single_item_details(item_id_to_lookup)

                    is_archived = (log_details_from_df['已轉費用'] != "") or (log_details_from_df['已轉收入'] != "")
                    
                    if is_archived:
                        st.success(f"✔️ 此筆紀錄已被處理 ({log_details_from_df['已轉費用']}{log_details_from_df['已轉收入']})。")
                    else:
                        # --- 拆分判斷邏輯 ---
                        transaction_type = log_details_from_df['異動類型']
                        
                        # 處理「售出」
                        if transaction_type == '售出':
                            if item_details and (item_details.get('selling_price') or 0) > 0:
                                if st.button("💰 將此筆銷售轉為其他收入"):
                                    success, message = inventory_model.archive_log_as_other_income(selected_log_id)
                                    if success: st.success(message); st.cache_data.clear(); st.rerun()
                                    else: st.error(message)
                            else:
                                st.warning("此品項未設定「建議售價」，無法轉為收入。請先至「品項總覽」編輯此品項。")
                        
                        # 處理「發放」
                        elif transaction_type == '發放':
                            if pd.notna(log_details_from_df['關聯宿舍']):
                                if st.button("💸 將此筆發放轉入年度費用"):
                                    success, message = inventory_model.archive_inventory_log_as_annual_expense(selected_log_id)
                                    if success: st.success(message); st.cache_data.clear(); st.rerun()
                                    else: st.error(message)
                            else:
                                st.warning("此筆「發放」紀錄未關聯宿舍，無法轉為費用。")
                        
                        else:
                            st.info("只有「發放」或「售出」類型的紀錄才能進行銷帳。")
                    
                    st.error("危險操作")
                    if st.checkbox(f"我確認要刪除 ID:{selected_log_id} 這筆異動紀錄"):
                        if st.button("🗑️ 刪除此筆紀錄", type="primary"):
                            success, message = inventory_model.delete_inventory_log(selected_log_id)
                            if success: st.success(message); st.cache_data.clear(); st.rerun()
                            else: st.error(message)

    with tab3:
        st.subheader("⚡ 批次轉入費用/收入")
        st.info("此處列出尚未歸檔的「發放」與「售出」紀錄，可勾選後一次性轉入帳務系統。")
        
        # 1. 取得資料
        pending_df = inventory_model.get_pending_accounting_logs()
        
        if pending_df.empty:
            st.success("目前沒有待處理的庫存帳務紀錄。")
        else:
            # 2. 設定預設勾選邏輯
            # 邏輯：如果是「發放」且「有關聯宿舍」(original_address非空)，則預設 True，否則 False
            pending_df['選取'] = pending_df.apply(
                lambda row: True if (row['異動類型'] == '發放' and pd.notna(row['關聯宿舍']) and row['關聯宿舍'] != "") else False, 
                axis=1
            )
            
            # 3. 顯示 Data Editor
            edited_df = st.data_editor(
                pending_df,
                column_config={
                    "選取": st.column_config.CheckboxColumn(required=True),
                    "id": st.column_config.NumberColumn(disabled=True),
                    "異動日期": st.column_config.DateColumn(disabled=True),
                    "品項名稱": st.column_config.TextColumn(disabled=True),
                    "異動類型": st.column_config.TextColumn(disabled=True),
                    "數量": st.column_config.NumberColumn(disabled=True),
                    "關聯宿舍": st.column_config.TextColumn(disabled=True),
                    "成本": st.column_config.NumberColumn(format="NT$ %d", disabled=True),
                    "售價": st.column_config.NumberColumn(format="NT$ %d", disabled=True),
                },
                hide_index=True,
                use_container_width=True,
                key="batch_inventory_editor"
            )
            
            # 4. 篩選出被選取的行
            selected_rows = edited_df[edited_df['選取']]
            
            c_btn1, c_btn2 = st.columns(2)
            
            # 5. 按鈕邏輯
            with c_btn1:
                # 篩選出「發放」類型的 ID
                expense_ids = selected_rows[selected_rows['異動類型'] == '發放']['id'].tolist()
                btn_expense_label = f"💸 將選取項目轉入「年度費用」 ({len(expense_ids)} 筆)"
                
                if st.button(btn_expense_label, type="primary", disabled=len(expense_ids)==0):
                    with st.spinner("正在批次處理費用..."):
                        s_count, f_count = inventory_model.batch_process_logs_to_expense(expense_ids)
                    if f_count == 0:
                        st.success(f"成功轉入 {s_count} 筆費用！")
                    else:
                        st.warning(f"完成 {s_count} 筆，失敗 {f_count} 筆 (請檢查是否缺少關聯宿舍或成本設定)。")
                    st.cache_data.clear()
                    st.rerun()
            
            with c_btn2:
                # 篩選出「售出」類型的 ID
                income_ids = selected_rows[selected_rows['異動類型'] == '售出']['id'].tolist()
                btn_income_label = f"💰 將選取項目轉入「其他收入」 ({len(income_ids)} 筆)"
                
                if st.button(btn_income_label, disabled=len(income_ids)==0):
                    with st.spinner("正在批次處理收入..."):
                        s_count, f_count = inventory_model.batch_process_logs_to_income(income_ids)
                    if f_count == 0:
                        st.success(f"成功轉入 {s_count} 筆收入！")
                    else:
                        st.warning(f"完成 {s_count} 筆，失敗 {f_count} 筆 (請檢查售價設定)。")
                    st.cache_data.clear()
                    st.rerun()