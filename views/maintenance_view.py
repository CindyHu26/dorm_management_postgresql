# views/maintenance_view.py

import streamlit as st
import pandas as pd
from datetime import date
from data_models import maintenance_model, dormitory_model, vendor_model, equipment_model
import os

# 用於高效取得所有維修紀錄
@st.cache_data
def get_all_logs_for_selection():
    return maintenance_model.get_logs_for_view(filters=None)

# -----------------------------------------------------------------------------
# 子功能渲染函式 (為了讓主程式碼整潔，將各區塊封裝)
# -----------------------------------------------------------------------------

def render_add_new_record(dorm_options, vendor_options, item_type_options, status_options):
    """渲染：新增維修紀錄 (修改版：解決成功訊息閃退問題)"""
    st.subheader("➕ 新增維修紀錄")

    # --- 【修改點 1】檢查是否有「待顯示」的成功訊息 (放在最前面) ---
    if "maint_success_msg" in st.session_state:
        st.success(st.session_state.maint_success_msg)
        # 顯示完後刪除，避免下次進來還一直顯示
        del st.session_state["maint_success_msg"]

    # -------------------------------------------------------
    # 第一排：基本資訊 (5欄)
    # -------------------------------------------------------
    c1, c2, c3, c4, c5 = st.columns(5)
    
    with c1:
        dorm_keys = list(dorm_options.keys())
        new_dorm_id = st.selectbox(
            "宿舍 (連動設備)*", 
            options=dorm_keys, 
            format_func=lambda x: dorm_options.get(x, "未選擇"),
            key="add_m_dorm"
        )

    with c2:
        if new_dorm_id:
            equipment_in_dorm = equipment_model.get_equipment_for_view({"dorm_id": new_dorm_id})
            if not equipment_in_dorm.empty:
                equip_options_new = {row['id']: f"{row['設備名稱']} ({row.get('位置', 'N/A')})" for _, row in equipment_in_dorm.iterrows()}
                new_equipment_id = st.selectbox(
                    "關聯設備 (選填)", 
                    options=[None] + list(equip_options_new.keys()), 
                    format_func=lambda x: "無" if x is None else equip_options_new.get(x),
                    key="add_m_equip"
                )
            else:
                st.selectbox("關聯設備", options=["該宿舍無設備資料"], disabled=True, key="add_m_equip_fake")
                new_equipment_id = None
        else:
            new_equipment_id = None

    with c3:
        new_report_date = st.date_input("收到通知日期*", value=date.today(), key="add_m_date")
    
    with c4:
        new_status = st.selectbox("案件狀態*", options=status_options, key="add_m_status")
    
    with c5:
        new_category_sel = st.selectbox("維修類別", options=item_type_options, key="add_m_cat")
        
        custom_category = None
        if new_category_sel == "其他(手動輸入)":
            custom_category = st.text_input(
                "請輸入自訂類型*", 
                placeholder="例如: 網路費",
                help="請輸入具體的維修或費用項目名稱",
                key="add_m_cat_custom"
            )

    # -------------------------------------------------------
    # 第二排：費用與廠商 (5欄)
    # -------------------------------------------------------
    c6, c7, c8, c9, c10 = st.columns(5)
    
    with c6:
        new_cost = st.number_input("維修費用", min_value=0, step=100, key="add_m_cost")
    with c7:
        new_vendor = st.selectbox("廠商", options=[None]+list(vendor_options.keys()), format_func=lambda x: "未指定" if x is None else vendor_options.get(x), key="add_m_vendor")
    with c8:
        new_payer = st.selectbox("付款人", ["", "我司", "工人", "雇主"], key="add_m_payer")
    with c9:
        new_finish_date = st.date_input("完成日期", value=None, key="add_m_finish")
    with c10:
        st.write("") 
        st.write("")
        new_is_paid_check = st.checkbox("已付款?", value=False, key="add_m_paid_check")

    # -------------------------------------------------------
    # 詳細說明
    # -------------------------------------------------------
    new_description = st.text_area(
        "修理細項說明* (可換行)", 
        height=150, 
        placeholder="請詳細描述故障情形、維修內容或更換零件...", 
        key="add_m_desc"
    )
    
    # -------------------------------------------------------
    # 其他細項欄位
    # -------------------------------------------------------
    c_sub1, c_sub2, c_sub3, c_sub4 = st.columns(4)
    new_reporter = c_sub1.text_input("提報人", placeholder="內部人員", key="add_m_reporter")
    new_key_info = c_sub2.text_input("鑰匙資訊", placeholder="如:警衛室", key="add_m_key_info")
    new_invoice_info = c_sub3.text_input("發票資訊", placeholder="抬頭/統編", key="add_m_invoice")
    new_notes = c_sub4.text_input("其他備註", placeholder="其他事項", key="add_m_notes")

    # -------------------------------------------------------
    # 附件上傳
    # -------------------------------------------------------
    uploaded_files = st.file_uploader(
        "📷 上傳照片/報價單 (可多選: jpg, png, pdf)",
        type=['jpg', 'jpeg', 'png', 'pdf'],
        accept_multiple_files=True,
        key="add_m_uploader"
    )

    # -------------------------------------------------------
    # 儲存按鈕
    # -------------------------------------------------------
    if st.button("💾 儲存維修案件", type="primary", use_container_width=True):
        
        final_category = custom_category if new_category_sel == "其他(手動輸入)" else new_category_sel

        if not new_dorm_id or not new_description:
            st.error("「宿舍」和「修理細項說明」為必填欄位！")
        elif new_category_sel == "其他(手動輸入)" and not custom_category:
            st.error("您選擇了「其他(手動輸入)」，請務必填寫自訂類型名稱！")
        else:
            # 1. 處理檔案
            file_paths = []
            if uploaded_files:
                file_info_dict = {
                    "date": new_report_date.strftime('%Y%m%d'),
                    "address": dorm_options.get(new_dorm_id, 'UnknownAddr'),
                    "reporter": new_reporter,
                    "type": final_category
                }
                for file in uploaded_files:
                    path = maintenance_model.save_uploaded_photo(file, file_info_dict)
                    file_paths.append(path)
            
            # 2. 準備資料
            final_status = new_status
            if new_finish_date and new_status in ["待處理", "待尋廠商", "進行中"]:
                final_status = "待付款"
            
            details = {
                'dorm_id': new_dorm_id, 
                'equipment_id': new_equipment_id,
                'vendor_id': new_vendor, 
                'status': final_status,
                'notification_date': new_report_date,
                'reported_by': new_reporter, 
                'item_type': final_category,
                'description': new_description,
                'contacted_vendor_date': None, 
                'completion_date': new_finish_date,
                'key_info': new_key_info,    
                'cost': new_cost, 
                'payer': new_payer, 
                'invoice_date': None,        
                'invoice_info': new_invoice_info, 
                'notes': new_notes,          
                'photo_paths': file_paths 
            }
            
            # 3. 呼叫後端
            success, message = maintenance_model.add_log(details)
            
            if success:
                # --- 【修改點 2】存入 Session State，而不是直接顯示 ---
                st.session_state.maint_success_msg = f"儲存成功！ {message}"
                st.cache_data.clear()
                
                # 4. 手動清空欄位
                keys_to_clear = [
                    "add_m_dorm", "add_m_equip", "add_m_date", "add_m_status", "add_m_cat",
                    "add_m_cost", "add_m_vendor", "add_m_payer", "add_m_finish", "add_m_paid_check",
                    "add_m_desc", "add_m_uploader", "add_m_reporter", "add_m_key_info", 
                    "add_m_invoice", "add_m_notes", "add_m_cat_custom"
                ]
                for k in keys_to_clear:
                    if k in st.session_state:
                        del st.session_state[k]
                
                # 刷新頁面 (刷新後會自動執行上面的 【修改點 1】 來顯示訊息)
                st.rerun()
            else:
                st.error(message)

def render_progress_tracking():
    """渲染：進度追蹤"""
    st.subheader("⏳ 進度追蹤 (未完成案件)")
    
    @st.cache_data
    def get_unfinished_logs():
        return maintenance_model.get_unfinished_maintenance_logs()

    unfinished_logs_df = get_unfinished_logs()

    if unfinished_logs_df.empty:
        st.success("🎉 恭喜！目前所有維修案件皆已完成。")
    else:
        st.warning(f"目前有 {len(unfinished_logs_df)} 筆維修案件正在進行中或等待處理。")
        st.dataframe(unfinished_logs_df, width='stretch', hide_index=True)

def render_edit_delete(dorm_options, vendor_options, item_type_options, status_options):
    """渲染：編輯與刪除"""
    st.subheader("✏️ 編輯 / 刪除單筆維修紀錄")
    all_logs_df = get_all_logs_for_selection()

    if all_logs_df.empty:
        st.info("目前沒有任何可供編輯或刪除的維修紀錄。")
        return
    
    # 搜尋功能
    search_key = st.text_input(
        "輸入關鍵字搜尋紀錄 (ID, 地址, 說明, 狀態...) - 多條件請用空格隔開", 
        key="maint_log_search_key"
    )

    filtered_search_df = all_logs_df.copy()

    if search_key:
        keywords = search_key.lower().split()
        filtered_search_df['searchable_text'] = (
            filtered_search_df['id'].astype(str) + " " +
            filtered_search_df['宿舍地址'] + " " +
            filtered_search_df['細項說明'] + " " +
            filtered_search_df['狀態'] + " " +
            filtered_search_df['內部提報人'].fillna('') + " " +
            filtered_search_df['維修廠商'].fillna('') + " " +
            filtered_search_df['項目類型'].fillna('') 
        ).str.lower()
        
        mask = filtered_search_df['searchable_text'].apply(lambda x: all(k in x for k in keywords))
        filtered_search_df = filtered_search_df[mask].copy()
        filtered_search_df.drop(columns=['searchable_text'], inplace=True)
    
    if filtered_search_df.empty:
         st.warning(f"找不到符合「{search_key}」的維修紀錄。")
         selected_log_id = None
    else:
        filtered_search_df['通報日期'] = pd.to_datetime(filtered_search_df['通報日期'])
        filtered_search_df = filtered_search_df.sort_values(by=['通報日期', 'id'], ascending=[False, False])
        
        options_dict = {
            row['id']: (
                f"[ID:{row['id']}] {row['狀態']} / {row['宿舍地址']} {row['細項說明']} / 通報:{row['通報日期'].strftime('%Y-%m-%d')}"
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
        
        # 顯示既有檔案
        st.markdown("##### 已上傳的檔案")
        existing_files = details.get('photo_paths') or []
        if valid_images := [f for f in existing_files if os.path.exists(f) and f.lower().endswith(('.png', '.jpg', '.jpeg'))]:
            st.image(valid_images, width=150, caption=[os.path.basename(f) for f in valid_images])
        
        if pdf_files := [f for f in existing_files if os.path.exists(f) and f.lower().endswith('.pdf')]:
            st.write("PDF 文件：")
            for pdf_path in pdf_files:
                with open(pdf_path, "rb") as pdf_file:
                    st.download_button(label=f"下載 {os.path.basename(pdf_path)}", data=pdf_file, file_name=os.path.basename(pdf_path), key=f"dl_{pdf_path}")

        with st.form(f"edit_log_form_{selected_log_id}"):
            st.subheader("案件資訊")
            ec1, ec2, ec3, ec4 = st.columns(4)
            
            # 宿舍處理
            current_dorm_id = details.get('dorm_id')
            dorm_keys = list(dorm_options.keys())
            current_dorm_index = dorm_keys.index(current_dorm_id) if current_dorm_id in dorm_keys else 0
            
            e_dorm_id = ec1.selectbox("宿舍地址", options=dorm_keys, format_func=lambda x: dorm_options.get(x, "未知"), index=current_dorm_index)
            
            # 設備處理
            equipment_in_dorm_edit = equipment_model.get_equipment_for_view({"dorm_id": current_dorm_id}) if current_dorm_id else pd.DataFrame()
            equip_options_edit = {row['id']: f"{row['設備名稱']} ({row.get('位置', 'N/A')})" for _, row in equipment_in_dorm_edit.iterrows()}
            current_equip_id = details.get('equipment_id')
            
            # 處理設備選單 index
            equip_keys_list = [None] + list(equip_options_edit.keys())
            try:
                equip_index = equip_keys_list.index(current_equip_id)
            except ValueError:
                equip_index = 0

            e_equipment_id = ec2.selectbox("關聯設備", options=equip_keys_list, format_func=lambda x: "無" if x is None else equip_options_edit.get(x), index=equip_index)
            e_notification_date = ec3.date_input("收到通知日期", value=details.get('notification_date'))
            e_reported_by = ec4.text_input("公司內部提報人", value=details.get('reported_by'))
            
            st.subheader("維修詳情")
            edc1, edc2 = st.columns(2)

            current_item_type = details.get('item_type', '')
            if current_item_type in item_type_options:
                default_index = item_type_options.index(current_item_type)
                custom_val = ""
            else:
                default_index = item_type_options.index("其他(手動輸入)") if "其他(手動輸入)" in item_type_options else 0
                custom_val = current_item_type

            e_selected_item_type = edc1.selectbox("項目類型", options=item_type_options, index=default_index)
            e_custom_item_type = edc1.text_input("自訂項目類型 (若選其他)", value=custom_val)
            e_description = edc2.text_area("修理細項說明", value=details.get('description'))
            
            st.markdown("##### 檔案管理")
            files_to_delete = st.multiselect("勾選要刪除的舊檔案：", options=existing_files, format_func=lambda f: os.path.basename(f))
            new_files = st.file_uploader("上傳新檔案", type=['jpg', 'jpeg', 'png', 'pdf'], accept_multiple_files=True)
            
            st.subheader("廠商與進度")
            ec6, ec7, ec8 = st.columns(3)
            status_idx = status_options.index(details.get('status')) if details.get('status') in status_options else 0
            e_status = ec6.selectbox("案件狀態", options=status_options, index=status_idx)
            
            vendor_keys = [None] + list(vendor_options.keys())
            vendor_idx = vendor_keys.index(details.get('vendor_id')) if details.get('vendor_id') in vendor_keys else 0
            e_vendor_id = ec7.selectbox("維修廠商", options=vendor_keys, format_func=lambda x: "未指定" if x is None else vendor_options.get(x), index=vendor_idx)
            e_contacted_vendor_date = ec7.date_input("聯絡廠商日期", value=details.get('contacted_vendor_date'))
            
            with ec8:
                e_completion_date = st.date_input("廠商回報完成日期", value=details.get('completion_date'))
            
            e_key_info = st.text_input("鑰匙/備註", value=details.get('key_info', ''))

            st.subheader("費用與款項")
            ec9, ec10, ec11, ec12 = st.columns(4)
            e_cost = ec9.number_input("維修費用", min_value=0, step=100, value=details.get('cost') or 0)
            
            payer_opts = ["", "我司", "工人", "雇主"]
            payer_idx = payer_opts.index(details.get('payer')) if details.get('payer') in payer_opts else 0
            e_payer = ec10.selectbox("付款人", payer_opts, index=payer_idx)
            e_invoice_date = ec11.date_input("請款日期", value=details.get('invoice_date'))
            e_invoice_info = ec12.text_input("發票資訊", value=details.get('invoice_info', ''))

            e_notes = st.text_area("其他備註", value=details.get('notes'))

            if st.form_submit_button("儲存變更"):
                final_type = e_custom_item_type if e_selected_item_type == "其他(手動輸入)" else e_selected_item_type
                
                final_file_paths = [p for p in existing_files if p not in files_to_delete]
                if new_files:
                    file_info_dict = {"date": e_notification_date.strftime('%Y%m%d'), "address": dorm_options.get(e_dorm_id, 'UnknownAddr'), "reporter": e_reported_by, "type": final_type}
                    for file in new_files:
                        path = maintenance_model.save_uploaded_photo(file, file_info_dict)
                        final_file_paths.append(path)

                update_data = {
                    'dorm_id': e_dorm_id, 'equipment_id': e_equipment_id, 'status': e_status, 
                    'vendor_id': e_vendor_id, 'notification_date': e_notification_date,
                    'reported_by': e_reported_by, 'item_type': final_type, 'description': e_description,
                    'contacted_vendor_date': e_contacted_vendor_date, 'completion_date': e_completion_date,
                    'key_info': e_key_info, 'cost': e_cost, 'payer': e_payer, 'invoice_date': e_invoice_date,
                    'invoice_info': e_invoice_info, 'notes': e_notes, 'photo_paths': final_file_paths 
                }
                
                success, message = maintenance_model.update_log(selected_log_id, update_data, paths_to_delete=files_to_delete)
                if success:
                    st.success(f"儲存成功！ {message}")
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(message)

        # 額外功能區塊 (不放在 Form 內)
        c_extra1, c_extra2, c_extra3 = st.columns(3)
        with c_extra1:
            if details.get('status') == '待付款':
                if st.button("✓ 結案 (已付款)", key="btn_complete"):
                    maintenance_model.mark_as_paid_and_complete(selected_log_id)
                    st.cache_data.clear()
                    st.rerun()
        with c_extra2:
            if not details.get('is_archived_as_expense') and details.get('status') in ['待付款', '已完成'] and (details.get('cost') or 0) > 0 and details.get('payer') == '我司':
                if st.button("💰 轉入年度費用", key="btn_archive"):
                    maintenance_model.archive_log_as_annual_expense(selected_log_id)
                    st.cache_data.clear()
                    st.rerun()
        with c_extra3:
             if st.button("🗑️ 刪除紀錄", key="btn_del", type="primary"):
                 maintenance_model.delete_log(selected_log_id)
                 st.cache_data.clear()
                 st.rerun()

def render_overview(dorm_options, vendor_options, status_options):
    """渲染：維修紀錄總覽"""
    st.subheader("📊 維修紀錄總覽")
    
    # 篩選器
    c1, c2, c3 = st.columns(3)
    f_status = c1.selectbox("狀態篩選", [""] + status_options, key="ov_status")
    f_dorm = c2.selectbox("宿舍篩選", [None] + list(dorm_options.keys()), format_func=lambda x: "全部" if x is None else dorm_options.get(x), key="ov_dorm")
    f_vendor = c3.selectbox("廠商篩選", [None] + list(vendor_options.keys()), format_func=lambda x: "全部" if x is None else vendor_options.get(x), key="ov_vendor")
    
    c4, c5 = st.columns(2)
    f_start = c4.date_input("完成日期 (起)", value=None, key="ov_start")
    f_end = c5.date_input("完成日期 (迄)", value=None, key="ov_end")

    filters = {}
    if f_status: filters["status"] = f_status
    if f_dorm: filters["dorm_id"] = f_dorm
    if f_vendor: filters["vendor_id"] = f_vendor
    if f_start: filters["start_date"] = f_start
    if f_end: filters["end_date"] = f_end

    log_df = maintenance_model.get_logs_for_view(filters)
    
    if not log_df.empty:
        if f_vendor or f_start or f_end:
             st.success(f"篩選總計: {len(log_df)} 筆, 費用總額: NT$ {log_df['維修費用'].sum():,}")
        st.dataframe(log_df, width='stretch', hide_index=True)
    else:
        st.info("無符合條件的資料")

def render_batch_archive():
    """渲染：批次轉入年度費用"""
    st.subheader("📦 批次轉入年度費用")
    st.info("列出已完成/待付款且為「我司」支付，但尚未歸檔的項目。")

    @st.cache_data
    def get_archivable_data():
        return maintenance_model.get_archivable_logs()

    archivable_df = get_archivable_data()

    if archivable_df.empty:
        st.success("目前沒有可批次轉入的項目。")
        return

    # 全選功能
    if 'maint_archive_default' not in st.session_state: st.session_state.maint_archive_default = False
    if 'maint_archive_reset' not in st.session_state: st.session_state.maint_archive_reset = 0

    c_tools1, c_tools2 = st.columns(2)
    if c_tools1.button("✅ 全選"):
        st.session_state.maint_archive_default = True
        st.session_state.maint_archive_reset += 1
        st.rerun()
    if c_tools2.button("⬜ 取消全選"):
        st.session_state.maint_archive_default = False
        st.session_state.maint_archive_reset += 1
        st.rerun()

    df_with_select = archivable_df.copy()
    df_with_select.insert(0, "選取", st.session_state.maint_archive_default)
    
    edited_df = st.data_editor(
        df_with_select,
        hide_index=True,
        column_config={"選取": st.column_config.CheckboxColumn(required=True)},
        disabled=archivable_df.columns,
        key=f"archive_editor_{st.session_state.maint_archive_reset}"
    )
    
    selected_rows = edited_df[edited_df.選取]
    
    if st.button("🚀 執行批次轉入", type="primary", disabled=selected_rows.empty):
        ids = selected_rows['id'].tolist()
        with st.spinner(f"處理 {len(ids)} 筆資料..."):
            s_count, f_count = maintenance_model.batch_archive_logs(ids)
        
        if s_count: st.success(f"成功轉入 {s_count} 筆！")
        if f_count: st.error(f"失敗 {f_count} 筆。")
        
        st.session_state.maint_archive_default = False
        st.session_state.maint_archive_reset += 1
        st.cache_data.clear()
        st.rerun()

# -----------------------------------------------------------------------------
# 主渲染函式 (單層 Radio 版)
# -----------------------------------------------------------------------------

def render():
    st.header("維修追蹤管理")
    st.info("用於登記、追蹤和管理宿舍的各項維修申報與進度，並可上傳現場照片、報價單(PDF)等相關文件。")
    
    # --- 準備共用資料 (維持不變) ---
    dorms = dormitory_model.get_dorms_for_selection()
    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dorms} if dorms else {}
    
    vendors = vendor_model.get_vendors_for_view()
    vendor_options = {v['id']: f"{v['服務項目']} - {v['廠商名稱']}" for _, v in vendors.iterrows()} if not vendors.empty else {}
    
    status_options = ["待處理", "待尋廠商", "進行中", "待付款", "已完成"]
    item_type_options = ["維修", "定期保養", "更換耗材", "水電", "包通", "飲水機", "冷氣", "消防", "金城", "監視器", "水質檢測", "清運", "裝潢", "油漆", "蝦皮", "其他(手動輸入)"]

    # =========================================================================
    # 導覽列：直接列出 5 個模組 (單層 Radio)
    # =========================================================================
    
    # 這裡我們加上 emoji 讓選項更直觀
    app_mode = st.radio(
        "請選擇操作項目：",
        [
            "➕ 新增維修紀錄",
            "⏳ 未完成案件追蹤",
            "✏️ 編輯 / 刪除單筆維修紀錄",
            "📊 維修紀錄總覽",
            "📦 批次轉入年度費用"
        ],
        horizontal=True,  # 橫向排列，節省垂直空間
        key="maintenance_main_nav"
    )
    
    st.markdown("---")

    # =========================================================================
    # 內容渲染：根據選擇呼叫對應的子函式
    # =========================================================================
    
    if app_mode == "➕ 新增維修紀錄":
        # 呼叫剛剛寫好的新增函式
        render_add_new_record(dorm_options, vendor_options, item_type_options, status_options)
    
    elif app_mode == "⏳ 未完成案件追蹤":
        render_progress_tracking()
        
    elif app_mode == "✏️ 編輯 / 刪除單筆維修紀錄":
        render_edit_delete(dorm_options, vendor_options, item_type_options, status_options)
        
    elif app_mode == "📊 維修紀錄總覽":
        render_overview(dorm_options, vendor_options, status_options)
        
    elif app_mode == "📦 批次轉入年度費用":
        render_batch_archive()