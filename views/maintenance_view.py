# views/maintenance_view.py (優化項目類型的完整版)

import streamlit as st
import pandas as pd
from datetime import date
from data_models import maintenance_model, dormitory_model, vendor_model

def render():
    st.header("維修追蹤管理")
    st.info("用於登記、追蹤和管理宿舍的各項維修申報與進度。")

    # --- 在頁面頂部新增「進度追蹤」區塊 ---
    st.markdown("---")
    st.subheader("進度追蹤 (未完成案件)")
    
    @st.cache_data
    def get_unfinished_logs():
        return maintenance_model.get_unfinished_maintenance_logs()

    unfinished_logs_df = get_unfinished_logs()

    if unfinished_logs_df.empty:
        st.success("🎉 恭喜！目前所有維修案件皆已完成。")
    else:
        st.warning(f"目前有 {len(unfinished_logs_df)} 筆維修案件正在進行中或等待處理。")
        st.dataframe(unfinished_logs_df, width='stretch', hide_index=True)
    st.markdown("---")

    # 準備下拉選單用的資料
    dorms = dormitory_model.get_dorms_for_selection()
    dorm_options = {d['id']: f"{d.get('legacy_dorm_code', '')} {d['original_address']}" for d in dorms} if dorms else {}
    
    vendors = vendor_model.get_vendors_for_view()
    vendor_options = {v['id']: f"{v['服務項目']} - {v['廠商名稱']}" for _, v in vendors.iterrows()} if not vendors.empty else {}
    
    status_options = ["待處理", "進行中", "待付款", "已完成"]
    
    # --- 將您的常用選項定義成一個列表 ---
    item_type_options = ["水電", "包通", "飲水機", "冷氣", "消防", "金城", "監視器", "水質檢測", "清運", "裝潢", "其他", "其他...(手動輸入)"]


    # --- 新增紀錄 ---
    with st.expander("➕ 新增維修紀錄"):
        with st.form("new_log_form", clear_on_submit=True):
            st.subheader("案件資訊")
            c1, c2, c3 = st.columns(3)
            dorm_id = c1.selectbox("宿舍地址", options=dorm_options.keys(), format_func=lambda x: dorm_options.get(x, "未選擇"), index=None, placeholder="請選擇宿舍...")
            notification_date = c2.date_input("收到通知日期", value=date.today())
            reported_by = c3.text_input("公司內部提報人")

            st.subheader("維修詳情")
            c4, c5 = st.columns(2)
            
            # --- 使用下拉選單 + 條件式輸入框 ---
            with c4:
                selected_item_type = st.selectbox("項目類型", options=item_type_options)
                custom_item_type = st.text_input("自訂項目類型", help="若上方選擇「其他...」，請在此處填寫")
            
            description = c5.text_area("修理細項說明")
            
            st.subheader("廠商與進度")
            c6, c7, c8 = st.columns(3)
            vendor_id = c6.selectbox("維修廠商", options=[None] + list(vendor_options.keys()), format_func=lambda x: "未指定" if x is None else vendor_options.get(x))
            contacted_vendor_date = c7.date_input("聯絡廠商日期", value=None)
            completion_date = c8.date_input("廠商回報完成日期", value=None)
            key_info = st.text_input("鑰匙/備註 (如: 需房東帶、鑰匙在警衛室)")

            st.subheader("費用與款項")
            c9, c10, c11, c12 = st.columns(4)
            cost = c9.number_input("維修費用", min_value=0, step=100)
            payer = c10.selectbox("付款人", ["", "我司", "工人", "雇主"])
            invoice_date = c11.date_input("請款日期", value=None)
            invoice_info = c12.text_input("發票資訊 (如: 抬頭、統編)")

            notes = st.text_area("其他備註")

            if st.form_submit_button("儲存紀錄"):
                # 決定最終要儲存的項目類型
                final_item_type = custom_item_type if selected_item_type == "其他..." else selected_item_type
                
                if not dorm_id or not description:
                    st.error("「宿舍地址」和「修理細項說明」為必填欄位！")
                elif selected_item_type == "其他..." and not custom_item_type:
                    st.error("您選擇了「其他...」，請務必填寫「自訂項目類型」！")
                else:
                    details = {
                        'dorm_id': dorm_id, 'vendor_id': vendor_id, 'notification_date': notification_date,
                        'reported_by': reported_by, 'item_type': final_item_type, 'description': description,
                        'contacted_vendor_date': contacted_vendor_date, 'completion_date': completion_date,
                        'key_info': key_info, 'cost': cost, 'payer': payer, 'invoice_date': invoice_date,
                        'invoice_info': invoice_info, 'notes': notes
                    }
                    success, message = maintenance_model.add_log(details)
                    if success: st.success(message); st.rerun()
                    else: st.error(message)


    st.markdown("---")
    st.markdown("##### 篩選條件")
    filter1, filter2, filter3 = st.columns(3)
    filter_status = filter1.selectbox("依狀態篩選", options=[""] + status_options, index=0, help="篩選案件目前的處理進度。")
    filter_dorm = filter2.selectbox("依宿舍篩選", options=[None] + list(dorm_options.keys()), format_func=lambda x: "全部宿舍" if x is None else dorm_options.get(x))
    filter_vendor = filter3.selectbox("依廠商篩選", options=[None] + list(vendor_options.keys()), format_func=lambda x: "全部廠商" if x is None else vendor_options.get(x))

    filter4, filter5 = st.columns(2)
    filter_start_date = filter4.date_input("完成日期 (起)", value=None)
    filter_end_date = filter5.date_input("完成日期 (迄)", value=None)

    # 組合篩選條件
    filters = {}
    if filter_status: filters["status"] = filter_status
    if filter_dorm: filters["dorm_id"] = filter_dorm
    if filter_vendor: filters["vendor_id"] = filter_vendor
    if filter_start_date: filters["start_date"] = filter_start_date
    if filter_end_date: filters["end_date"] = filter_end_date
    
    log_df = maintenance_model.get_logs_for_view(filters)
    
    # --- 新增總計金額顯示 ---
    if not log_df.empty and (filter_vendor or filter_start_date or filter_end_date):
        total_cost = log_df['維修費用'].sum()
        st.success(f"篩選結果總計 {len(log_df)} 筆案件，費用總額為： NT$ {total_cost:,}")

    st.dataframe(log_df, width='stretch', hide_index=True, column_config={"id": None})

    # --- 編輯與刪除 ---
    st.markdown("---")
    st.subheader("編輯 / 刪除單筆維修紀錄")
    if not log_df.empty:
        options_dict = {row['id']: f"ID:{row['id']} - {row['宿舍地址']} ({row['項目類型']})" for _, row in log_df.iterrows()}
        selected_log_id = st.selectbox("選擇要操作的紀錄", options=[None] + list(options_dict.keys()), format_func=lambda x: "請選擇..." if x is None else options_dict.get(x))

        if selected_log_id:
            details = maintenance_model.get_single_log_details(selected_log_id)
            with st.form(f"edit_log_form_{selected_log_id}"):
                st.subheader("案件資訊")
                ec1, ec2, ec3 = st.columns(3)
                ec1.text_input("宿舍地址", value=dorm_options.get(details.get('dorm_id')), disabled=True)
                e_notification_date = ec2.date_input("收到通知日期", value=details.get('notification_date'))
                e_reported_by = ec3.text_input("公司內部提報人", value=details.get('reported_by'))
                
                st.subheader("維修詳情")
                ec4, ec5 = st.columns(2)

                # --- 【核心修改 3】編輯時也使用同樣的邏輯 ---
                with ec4:
                    current_item_type = details.get('item_type', '')
                    # 判斷當前的項目是否在預設選項中
                    if current_item_type in item_type_options:
                        default_index = item_type_options.index(current_item_type)
                        default_custom_value = ""
                    else:
                        default_index = item_type_options.index("其他...")
                        default_custom_value = current_item_type

                    e_selected_item_type = st.selectbox("項目類型", options=item_type_options, index=default_index, key=f"edit_item_type_{selected_log_id}")
                    e_custom_item_type = st.text_input("自訂項目類型", value=default_custom_value, help="若上方選擇「其他...」，請在此處填寫", key=f"edit_custom_item_type_{selected_log_id}")

                e_description = ec5.text_area("修理細項說明", value=details.get('description'))
                
                st.subheader("廠商與進度")
                ec6, ec7, ec8 = st.columns(3)
                e_status = ec6.selectbox("案件狀態", options=status_options, index=status_options.index(details.get('status')) if details.get('status') in status_options else 0)
                e_vendor_id = ec7.selectbox("維修廠商", options=[None] + list(vendor_options.keys()), format_func=lambda x: "未指定" if x is None else vendor_options.get(x), index=([None] + list(vendor_options.keys())).index(details.get('vendor_id')) if details.get('vendor_id') in [None] + list(vendor_options.keys()) else 0)
                e_contacted_vendor_date = ec7.date_input("聯絡廠商日期", value=details.get('contacted_vendor_date'))
                
                with ec8:
                    e_completion_date = st.date_input("廠商回報完成日期", value=details.get('completion_date'))
                
                e_key_info = st.text_input("鑰匙/備註 (如: 需房東帶、鑰匙在警衛室)", value=details.get('key_info', ''))

                st.subheader("費用與款項")
                ec9, ec10, ec11, ec12 = st.columns(4)
                e_cost = ec9.number_input("維修費用", min_value=0, step=100, value=details.get('cost') or 0)
                e_payer = ec10.selectbox("付款人", ["", "我司", "工人", "雇主"], index=(["", "我司", "工人", "雇主"]).index(details.get('payer')) if details.get('payer') in ["", "我司", "工人", "雇主"] else 0)
                e_invoice_date = ec11.date_input("請款日期", value=details.get('invoice_date'))
                e_invoice_info = ec12.text_input("發票資訊", value=details.get('invoice_info'))

                e_notes = st.text_area("其他備註", value=details.get('notes'))

                if st.form_submit_button("儲存變更"):
                    # 決定最終要儲存的項目類型
                    e_final_item_type = e_custom_item_type if e_selected_item_type == "其他..." else e_selected_item_type
                    
                    if e_selected_item_type == "其他..." and not e_custom_item_type:
                        st.error("您選擇了「其他...」，請務必填寫「自訂項目類型」！")
                    else:
                        update_data = {
                            'status': e_status, 'vendor_id': e_vendor_id, 'notification_date': e_notification_date,
                            'reported_by': e_reported_by, 'item_type': e_final_item_type, 'description': e_description,
                            'contacted_vendor_date': e_contacted_vendor_date, 'completion_date': e_completion_date,
                            'key_info': e_key_info, 'cost': e_cost, 'payer': e_payer, 'invoice_date': e_invoice_date,
                            'invoice_info': e_invoice_info, 'notes': e_notes
                        }
                        success, message = maintenance_model.update_log(selected_log_id, update_data)
                        if success: st.success(message); st.rerun()
                        else: st.error(message)
            
            st.markdown("---")
            st.markdown("##### 財務操作")
            
            if details.get('is_archived_as_expense'):
                st.success("✔️ 此筆維修費用已轉入年度費用。")
            elif (details.get('status') in ['待付款', '已完成']) and (details.get('cost') or 0) > 0 and (details.get('payer') == '我司'):
                if st.button("💰 轉入年度費用進行攤銷", help="點擊後，系統會自動建立一筆對應的年度費用紀錄，預設攤銷12個月。"):
                    success, message = maintenance_model.archive_log_as_annual_expense(selected_log_id)
                    if success:
                        st.success(message); st.rerun()
                    else:
                        st.error(message)
            else:
                st.info("需將案件狀態設為「待付款」或「已完成」，且「維修費用」大於0、「付款人」為「我司」，才能轉入年度費用。")

            st.markdown("---")
            st.markdown("##### 危險操作區")
            if st.checkbox(f"我確認要刪除 ID:{selected_log_id} 這筆維修紀錄"):
                if st.button("🗑️ 刪除此筆紀錄", type="primary"):
                    success, message = maintenance_model.delete_log(selected_log_id)
                    if success: st.success(message); st.rerun()
                    else: st.error(message)
    else:
        st.info("目前沒有可供操作的紀錄。")