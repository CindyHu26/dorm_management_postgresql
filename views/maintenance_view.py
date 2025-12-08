# views/maintenance_view.py

import streamlit as st
import pandas as pd
from datetime import date
from data_models import maintenance_model, dormitory_model, vendor_model, equipment_model
import os

# 用於高效取得所有維修紀錄
@st.cache_data
def get_all_logs_for_selection():
    # 這裡呼叫後端函式，但不傳入任何狀態過濾器 (filters=None)，即可取得所有紀錄
    return maintenance_model.get_logs_for_view(filters=None)

def render():
    st.header("維修追蹤管理")
    st.info("用於登記、追蹤和管理宿舍的各項維修申報與進度，並可上傳現場照片、報價單(PDF)等相關文件。")

    # --- 進度追蹤區塊 ---
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

    # --- 準備下拉選單用的資料 ---
    dorms = dormitory_model.get_dorms_for_selection()
    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms} if dorms else {}
    
    vendors = vendor_model.get_vendors_for_view()
    vendor_options = {v['id']: f"{v['服務項目']} - {v['廠商名稱']}" for _, v in vendors.iterrows()} if not vendors.empty else {}
    
    status_options = ["待處理", "待尋廠商", "進行中", "待付款", "已完成"]
    item_type_options = ["維修", "定期保養", "更換耗材", "水電", "包通", "飲水機", "冷氣", "消防", "金城", "監視器", "水質檢測", "清運", "裝潢", "其他", "其他(手動輸入)"]

    # --- 新增紀錄 ---
    with st.expander("➕ 新增維修紀錄"):
        with st.form("new_log_form", clear_on_submit=True):
            st.subheader("案件資訊")
            c1, c2, c3 = st.columns(3)
            dorm_id = c1.selectbox("宿舍地址*", options=list(dorm_options.keys()), format_func=lambda x: dorm_options.get(x, "未選擇"), index=None, placeholder="請選擇宿舍...")
            
            equipment_in_dorm = equipment_model.get_equipment_for_view({"dorm_id": dorm_id}) if dorm_id else pd.DataFrame()
            equip_options = {row['id']: f"{row['設備名稱']} ({row.get('位置', 'N/A')})" for _, row in equipment_in_dorm.iterrows()} if not equipment_in_dorm.empty else {}
            
            equipment_id = c2.selectbox("關聯設備 (選填)", options=[None] + list(equip_options.keys()), format_func=lambda x: "無 (非特定設備)" if x is None else equip_options.get(x))
            
            notification_date = c3.date_input("收到通知日期*", value=date.today())
            reported_by = c1.text_input("公司內部提報人")

            st.subheader("維修詳情")
            c4, c5 = st.columns(2)
            
            with c4:
                selected_item_type = st.selectbox("項目類型", options=item_type_options)
                custom_item_type = st.text_input("自訂項目類型", help="若上方選擇「其他(手動輸入)」，請在此處填寫")
            
            description = c5.text_area("修理細項說明*")
            
            uploaded_files = st.file_uploader(
                "上傳照片或文件 (可多選)",
                type=['jpg', 'jpeg', 'png', 'pdf'],
                accept_multiple_files=True
            )
            
            st.subheader("廠商與進度")
            c6, c7, c8, c9_status = st.columns(4)
            vendor_id = c6.selectbox("維修廠商", options=[None] + list(vendor_options.keys()), format_func=lambda x: "未指定" if x is None else vendor_options.get(x))
            contacted_vendor_date = c7.date_input("聯絡廠商日期", value=None)
            completion_date = c8.date_input("廠商回報完成日期", value=None)
            status = c9_status.selectbox("案件狀態*", options=status_options, help="若尚無合適廠商，請選擇「待尋廠商」以便追蹤。")

            key_info = st.text_input("鑰匙/備註 (如: 需房東帶、鑰匙在警衛室)")
            
            st.subheader("費用與款項")
            c9, c10, c11, c12 = st.columns(4)
            cost = c9.number_input("維修費用", min_value=0, step=100)
            payer = c10.selectbox("付款人", ["", "我司", "工人", "雇主"])
            invoice_date = c11.date_input("請款日期", value=None)

            dorm_details_for_new = dormitory_model.get_dorm_details_by_id(dorm_id) if dorm_id else {}
            default_invoice_info_new = dorm_details_for_new.get('invoice_info', '')
            invoice_info = c12.text_input("發票資訊 (如: 抬頭、統編)", value=default_invoice_info_new)

            notes = st.text_area("其他備註")

            if st.form_submit_button("儲存紀錄"):
                final_item_type = custom_item_type if selected_item_type == "其他(手動輸入)" else selected_item_type
                
                if not dorm_id or not description:
                    st.error("「宿舍地址」和「修理細項說明」為必填欄位！")
                elif selected_item_type == "其他(手動輸入)" and not custom_item_type:
                    st.error("您選擇了「其他(手動輸入)」，請務必填寫「自訂項目類型」！")
                else:
                    file_paths = []
                    if uploaded_files:
                        file_info_dict = {
                            "date": notification_date.strftime('%Y%m%d'),
                            "address": dorm_options.get(dorm_id, 'UnknownAddr'),
                            "reporter": reported_by,
                            "type": final_item_type
                        }
                        for file in uploaded_files:
                            path = maintenance_model.save_uploaded_photo(file, file_info_dict)
                            file_paths.append(path)
                    
                    details = {
                        'dorm_id': dorm_id, 
                        'equipment_id': equipment_id,
                        'vendor_id': vendor_id, 
                        'status': status,
                        'notification_date': notification_date,
                        'reported_by': reported_by, 
                        'item_type': final_item_type, 
                        'description': description,
                        'contacted_vendor_date': contacted_vendor_date, 
                        'completion_date': completion_date,
                        'key_info': key_info, 
                        'cost': cost, 
                        'payer': payer, 
                        'invoice_date': invoice_date,
                        'invoice_info': invoice_info, 
                        'notes': notes,
                        'photo_paths': file_paths 
                    }
                    success, message = maintenance_model.add_log(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

    st.markdown("---")
    st.subheader("批次轉入年度費用")
    st.info("此區塊會列出所有已完成或待付款，且尚未歸檔的「我司」支付項目，方便您一次性轉入年度攤銷。")

    @st.cache_data
    def get_archivable_data():
        return maintenance_model.get_archivable_logs()

    archivable_df = get_archivable_data()

    if archivable_df.empty:
        st.success("目前沒有符合條件可批次轉入的維修費用。")
    else:
        # --- 全選/取消全選按鈕 ---
        # 初始化 session state
        if 'maint_archive_reset_counter' not in st.session_state:
             st.session_state.maint_archive_reset_counter = 0
        if 'maint_archive_default_val' not in st.session_state:
             st.session_state.maint_archive_default_val = False

        col_tools1, col_tools2 = st.columns(2)
        if col_tools1.button("✅ 全選"):
            st.session_state.maint_archive_default_val = True
            st.session_state.maint_archive_reset_counter += 1
            st.rerun()
        if col_tools2.button("⬜ 取消全選"):
            st.session_state.maint_archive_default_val = False
            st.session_state.maint_archive_reset_counter += 1
            st.rerun()

        archivable_df_with_selection = archivable_df.copy()
        # 根據 session state 設定預設值
        archivable_df_with_selection.insert(0, "選取", st.session_state.maint_archive_default_val)
        
        # 使用 dynamic key 強制重置 data_editor 狀態
        editor_key = f"archive_editor_{st.session_state.maint_archive_reset_counter}"

        edited_df = st.data_editor(
            archivable_df_with_selection,
            hide_index=True,
            column_config={"選取": st.column_config.CheckboxColumn(required=True)},
            disabled=archivable_df.columns,
            key=editor_key
        )
        
        selected_rows = edited_df[edited_df.選取]
        
        if st.button("🚀 批次轉入選取的項目", type="primary", disabled=selected_rows.empty):
            ids_to_archive = selected_rows['id'].tolist()
            with st.spinner(f"正在批次處理 {len(ids_to_archive)} 筆資料..."):
                success_count, failure_count = maintenance_model.batch_archive_logs(ids_to_archive)
            
            if success_count > 0:
                st.success(f"成功將 {success_count} 筆費用轉入年度攤銷！")
            if failure_count > 0:
                st.error(f"有 {failure_count} 筆費用處理失敗，請檢查後台日誌。")
            
            # 操作完成後，重置全選狀態並清除快取
            st.session_state.maint_archive_default_val = False
            st.session_state.maint_archive_reset_counter += 1
            st.cache_data.clear()
            st.rerun()

    # --- 總覽與篩選 ---
    st.markdown("---")
    st.subheader("維修紀錄總覽")
    st.markdown("##### 篩選條件")
    filter1, filter2, filter3 = st.columns(3)
    filter_status = filter1.selectbox("依狀態篩選", options=[""] + status_options, index=0, help="篩選案件目前的處理進度。")
    filter_dorm = filter2.selectbox("依宿舍篩選", options=[None] + list(dorm_options.keys()), format_func=lambda x: "全部宿舍" if x is None else dorm_options.get(x))
    filter_vendor = filter3.selectbox("依廠商篩選", options=[None] + list(vendor_options.keys()), format_func=lambda x: "全部廠商" if x is None else vendor_options.get(x))
    filter4, filter5 = st.columns(2)
    filter_start_date = filter4.date_input("完成日期 (起)", value=None)
    filter_end_date = filter5.date_input("完成日期 (迄)", value=None)
    filters = {}
    if filter_status: filters["status"] = filter_status
    if filter_dorm: filters["dorm_id"] = filter_dorm
    if filter_vendor: filters["vendor_id"] = filter_vendor
    if filter_start_date: filters["start_date"] = filter_start_date
    if filter_end_date: filters["end_date"] = filter_end_date
    log_df = maintenance_model.get_logs_for_view(filters)
    if not log_df.empty and (filter_vendor or filter_start_date or filter_end_date):
        total_cost = log_df['維修費用'].sum()
        st.success(f"篩選結果總計 {len(log_df)} 筆案件，費用總額為： NT$ {total_cost:,}")
    st.dataframe(log_df, width='stretch', hide_index=True, column_config={"id": None})
    
    # --- 編輯與刪除 ---
    st.markdown("---")
    st.subheader("編輯 / 刪除單筆維修紀錄")
# 取得所有紀錄
    all_logs_df = get_all_logs_for_selection()

    if all_logs_df.empty:
        st.info("目前沒有任何可供編輯或刪除的維修紀錄。")
        return
    
    # 搜尋功能
    search_key = st.text_input(
        "輸入關鍵字搜尋紀錄 (ID, 地址, 說明, 狀態, 提報人, 維修廠商)", 
        key="maint_log_search_key"
    )

    filtered_search_df = all_logs_df.copy()

    # 執行搜尋過濾
    if search_key:
        search_key_lower = search_key.lower()
        
        # 篩選邏輯：在 ID, 宿舍地址, 細項說明, 狀態, 提報人, 維修廠商中尋找
        search_mask = (
            filtered_search_df['id'].astype(str).str.contains(search_key_lower, case=False, na=False) |
            filtered_search_df['宿舍地址'].str.contains(search_key_lower, case=False, na=False) |
            filtered_search_df['細項說明'].str.contains(search_key_lower, case=False, na=False) |
            filtered_search_df['狀態'].str.contains(search_key_lower, case=False, na=False) |
            filtered_search_df['內部提報人'].str.contains(search_key_lower, case=False, na=False) |
            # 【核心修改】新增 維修廠商
            filtered_search_df['維修廠商'].str.contains(search_key_lower, case=False, na=False) 
        )
        
        filtered_search_df = filtered_search_df[search_mask]
    
    # 建立下拉選單的選項
    if filtered_search_df.empty:
         st.warning(f"找不到符合「{search_key}」的維修紀錄。")
         selected_log_id = None
    else:
        # 排序：讓最新通報的紀錄排在前面
        filtered_search_df = filtered_search_df.sort_values(by=['通報日期', 'id'], ascending=[False, False])
        
        options_dict = {
            row['id']: (
                f"[ID:{row['id']}] {row['狀態']} / "
                f"{row['宿舍地址']} {row['細項說明']} / "
                f"通報:{row['通報日期']}"
            )
            for _, row in filtered_search_df.iterrows()
        }
        
        selected_log_id = st.selectbox(
            f"選擇要操作的紀錄 (共 {len(filtered_search_df)} 筆符合)", 
            options=[None] + list(options_dict.keys()), 
            format_func=lambda x: "請選擇..." if x is None else options_dict.get(x), 
            key="selectbox_log_selection"
        )

    if selected_log_id:
        details = maintenance_model.get_single_log_details(selected_log_id)
        
        st.markdown("##### 已上傳的檔案")
        existing_files = details.get('photo_paths') or []
        
        if not existing_files:
            st.info("此紀錄沒有已上傳的檔案。")
        else:
            valid_images = []
            missing_files = []

            for f in existing_files:
                if os.path.exists(f):
                    if f.lower().endswith(('.png', '.jpg', '.jpeg')):
                        valid_images.append(f)
                else:
                    missing_files.append(f)

            if valid_images:
                st.image(valid_images, width=150, caption=[os.path.basename(f) for f in valid_images])
            
            if missing_files:
                st.warning(f"⚠️ 注意：有 {len(missing_files)} 個檔案在伺服器上找不到 (可能已被手動刪除或備份未完整)。")

            pdf_files = [f for f in existing_files if f.lower().endswith('.pdf')]
            
            if pdf_files:
                st.write("PDF 文件：")
                for pdf_path in pdf_files:
                    if os.path.exists(pdf_path):
                        with open(pdf_path, "rb") as pdf_file:
                            st.download_button(
                                label=f"下載 {os.path.basename(pdf_path)}",
                                data=pdf_file,
                                file_name=os.path.basename(pdf_path),
                                key=f"download_{pdf_path}"
                            )
                    else:
                        st.warning(f"檔案遺失: {os.path.basename(pdf_path)}")

        with st.form(f"edit_log_form_{selected_log_id}"):
            st.subheader("案件資訊")
            ec1, ec2, ec3, ec4 = st.columns(4)
            
            current_dorm_id = details.get('dorm_id')
            dorm_keys = list(dorm_options.keys())
            try:
                current_dorm_index = dorm_keys.index(current_dorm_id)
            except ValueError:
                temp_dorm_details = dormitory_model.get_dorm_details_by_id(current_dorm_id)
                if temp_dorm_details:
                    dorm_name = temp_dorm_details.get('original_address', f"ID {current_dorm_id}")
                    dorm_options[current_dorm_id] = f"(其他) {dorm_name}"
                    dorm_keys = list(dorm_options.keys())
                    current_dorm_index = dorm_keys.index(current_dorm_id)
                else:
                    current_dorm_index = 0
            
            e_dorm_id = ec1.selectbox(
                "宿舍地址", 
                options=dorm_keys, 
                format_func=lambda x: dorm_options.get(x, "未知宿舍"), 
                index=current_dorm_index,
                key=f"edit_dorm_id_{selected_log_id}"
            )
            
            record_dorm_id = details.get('dorm_id')
            equipment_in_dorm_edit = equipment_model.get_equipment_for_view({"dorm_id": record_dorm_id}) if record_dorm_id else pd.DataFrame()
            equip_options_edit = {row['id']: f"{row['設備名稱']} ({row.get('位置', 'N/A')})" for _, row in equipment_in_dorm_edit.iterrows()} if not equipment_in_dorm_edit.empty else {}
            current_equip_id = details.get('equipment_id')
            
            e_equipment_id = ec2.selectbox("關聯設備 (選填)", options=[None] + list(equip_options_edit.keys()), format_func=lambda x: "無 (非特定設備)" if x is None else equip_options_edit.get(x), index=([None] + list(equip_options_edit.keys())).index(current_equip_id) if current_equip_id in [None] + list(equip_options_edit.keys()) else 0)
            
            e_notification_date = ec3.date_input("收到通知日期", value=details.get('notification_date'))
            e_reported_by = ec4.text_input("公司內部提報人", value=details.get('reported_by'))
            
            st.subheader("維修詳情")
            edc1, edc2 = st.columns(2)

            with edc1:
                current_item_type = details.get('item_type', '')
                if current_item_type in item_type_options:
                    default_index = item_type_options.index(current_item_type)
                    default_custom_value = ""
                else:
                    default_index = item_type_options.index("其他(手動輸入)")
                    default_custom_value = current_item_type
                e_selected_item_type = st.selectbox("項目類型", options=item_type_options, index=default_index, key=f"edit_item_type_{selected_log_id}")
                e_custom_item_type = st.text_input("自訂項目類型", value=default_custom_value, help="若上方選擇「其他(手動輸入)」，請在此處填寫", key=f"edit_custom_item_type_{selected_log_id}")

            e_description = edc2.text_area("修理細項說明", value=details.get('description'))
            
            st.markdown("##### 檔案管理")
            st.caption("🔴 注意：若要刪除已儲存的檔案，請在下方勾選後，按下表單最底部的「儲存變更」按鈕。")
            files_to_delete = st.multiselect("勾選要刪除的舊檔案：", options=existing_files, format_func=lambda f: os.path.basename(f))
            new_files = st.file_uploader(
                "上傳新檔案 (可多選)",
                type=['jpg', 'jpeg', 'png', 'pdf'],
                accept_multiple_files=True,
                key=f"edit_uploader_{selected_log_id}"
            )
            
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
            
            dorm_details_for_edit = dormitory_model.get_dorm_details_by_id(record_dorm_id) if record_dorm_id else {}
            default_invoice_info_edit = dorm_details_for_edit.get('invoice_info', '')
            current_invoice_info = details.get('invoice_info', '')
            e_invoice_info = ec12.text_input("發票資訊", value=current_invoice_info or default_invoice_info_edit)

            e_notes = st.text_area("其他備註", value=details.get('notes'))

            if st.form_submit_button("儲存變更"):
                e_final_item_type = e_custom_item_type if e_selected_item_type == "其他(手動輸入)" else e_selected_item_type
                
                if e_selected_item_type == "其他(手動輸入)" and not e_custom_item_type:
                    st.error("您選擇了「其他(手動輸入)」，請務必填寫「自訂項目類型」！")
                else:
                    final_status = e_status
                    pre_completion_states = ["待處理", "待尋廠商", "進行中"]
                    if e_completion_date and (details.get('status') in pre_completion_states):
                        final_status = "待付款"
                        st.toast("偵測到已填寫完成日期，案件狀態將自動更新為「待付款」。")

                    final_file_paths = [p for p in existing_files if p not in files_to_delete]
                    if new_files:
                        file_info_dict = {
                            "date": e_notification_date.strftime('%Y%m%d'),
                            "address": dorm_options.get(details.get('dorm_id'), 'UnknownAddr'),
                            "reporter": e_reported_by,
                            "type": e_final_item_type
                        }
                        for file in new_files:
                            path = maintenance_model.save_uploaded_photo(file, file_info_dict)
                            final_file_paths.append(path)

                    update_data = {
                        'dorm_id': e_dorm_id,
                        'equipment_id': e_equipment_id,
                        'status': final_status, 
                        'vendor_id': e_vendor_id, 'notification_date': e_notification_date,
                        'reported_by': e_reported_by, 'item_type': e_final_item_type, 'description': e_description,
                        'contacted_vendor_date': e_contacted_vendor_date, 'completion_date': e_completion_date,
                        'key_info': e_key_info, 'cost': e_cost, 'payer': e_payer, 'invoice_date': e_invoice_date,
                        'invoice_info': e_invoice_info, 'notes': e_notes,
                        'photo_paths': final_file_paths 
                    }
                    
                    success, message = maintenance_model.update_log(selected_log_id, update_data, paths_to_delete=files_to_delete)
                    
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)
            
            st.markdown("---")
            st.markdown("##### 結案操作")
            
            if details.get('status') == '待付款':
                st.info("確認款項支付後，請點擊下方按鈕將案件結案。")
                if st.button("✓ 標示為已付款並結案", type="primary"):
                    success, message = maintenance_model.mark_as_paid_and_complete(selected_log_id)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)
            else:
                st.write("需將案件狀態設為「待付款」才能執行結案操作。")

            st.markdown("---")
            st.markdown("##### 財務操作")
            if details.get('is_archived_as_expense'):
                st.success("✔️ 此筆維修費用已轉入年度費用。")
            elif (details.get('status') in ['待付款', '已完成']) and (details.get('cost') or 0) > 0 and (details.get('payer') == '我司'):
                if st.button("💰 轉入年度費用進行攤銷", help="點擊後，系統會自動建立一筆對應的年度費用紀錄，預設攤銷12個月。"):
                    success, message = maintenance_model.archive_log_as_annual_expense(selected_log_id)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)
            else:
                st.info("需將案件狀態設為「待付款」或「已完成」，且「維修費用」大於0、「付款人」為「我司」，才能轉入年度費用。")

            st.markdown("---")
            st.markdown("##### 危險操作區")
            if st.checkbox(f"我確認要刪除 ID:{selected_log_id} 這筆維修紀錄"):
                if st.button("🗑️ 刪除此筆紀錄", type="primary"):
                    success, message = maintenance_model.delete_log(selected_log_id)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)