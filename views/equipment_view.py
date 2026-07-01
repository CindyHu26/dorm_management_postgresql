# views/equipment_view.py (v18 - 總覽欄位擴充)

import streamlit as st
import pandas as pd
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from data_models import equipment_model, dormitory_model, maintenance_model, vendor_model, finance_model

def render():
    """渲染「設備管理」頁面"""
    st.info("用於登錄、追蹤宿舍內的消防、電器、飲水等各類設備及其完整的生命週期紀錄。")

    today = date.today()
    fifteen_years_ago = today - relativedelta(years=15)

    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍。")
        return

    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}
    
    vendors = vendor_model.get_vendors_for_view()
    vendor_options = {v['id']: f"{v['服務項目']} - {v['廠商名稱']}" for _, v in vendors.iterrows()} if not vendors.empty else {}

    # --- 批次操作區塊 ---
    with st.expander("⚙️ 批次更新保養紀錄"):
        st.info("此功能用於一次性為同一宿舍、同一類別的多台設備（例如：所有飲水機）登記保養紀錄。")
        batch_c1, batch_c2 = st.columns(2)
        batch_dorm_id = batch_c1.selectbox("步驟一：選擇宿舍*", options=[None] + list(dorm_options.keys()), format_func=lambda x: "請選擇..." if x is None else dorm_options.get(x), key="batch_dorm")
        categories_for_batch = equipment_model.get_distinct_equipment_categories()
        batch_category = batch_c2.selectbox("步驟二：選擇設備分類*", options=[None] + categories_for_batch, format_func=lambda x: "請選擇..." if x is None else x, key="batch_category")
        equipment_to_batch = pd.DataFrame()
        if batch_dorm_id and batch_category:
            equipment_to_batch = equipment_model.get_equipment_for_view({"dorm_id": batch_dorm_id, "category": batch_category})
        if not equipment_to_batch.empty:
            with st.form("batch_maintenance_form"):
                st.markdown("##### 步驟三：勾選要更新的設備")
                equipment_to_batch.insert(0, "選取", True)
                edited_df = st.data_editor(equipment_to_batch, hide_index=True, disabled=equipment_to_batch.columns.drop("選取"), key="batch_editor")
                st.markdown("---")
                st.markdown("##### 步驟四：填寫共同的保養資訊")
                batch_info_c1, batch_info_c2 = st.columns(2)
                batch_item_type = batch_info_c1.selectbox("項目類型", ["定期保養", "更換耗材", "維修"], key="batch_item_type")
                batch_description = batch_info_c1.text_input("細項說明 (必填)", placeholder="例如: 更換第一道RO濾心")
                batch_completion_date = batch_info_c2.date_input("完成日期*", value=date.today(), key="batch_date")
                batch_total_cost = batch_info_c2.number_input("總費用 (選填)", min_value=0, step=100, help="此金額將會平均分攤到所有選取的設備上。")
                batch_vendor_id = st.selectbox("執行廠商 (選填)", options=[None] + list(vendor_options.keys()), format_func=lambda x: "未指定" if x is None else vendor_options.get(x), key="batch_vendor")
                batch_submitted = st.form_submit_button("🚀 執行批次更新")
                if batch_submitted:
                    selected_equipment = edited_df[edited_df["選取"]]
                    if selected_equipment.empty:
                        st.error("請至少選取一台設備！")
                    elif not batch_description:
                        st.error("請填寫「細項說明」！")
                    else:
                        equipment_ids = selected_equipment['id'].tolist()
                        maintenance_info = {"dorm_id": batch_dorm_id, "vendor_id": batch_vendor_id, "item_type": batch_item_type, "description": batch_description, "completion_date": batch_completion_date, "cost": batch_total_cost}
                        with st.spinner(f"正在為 {len(equipment_ids)} 台設備更新紀錄..."):
                            success, message = equipment_model.batch_add_maintenance_logs(equipment_ids, maintenance_info)
                        if success:
                            st.success(message); st.cache_data.clear(); st.rerun()
                        else:
                            st.error(message)
        elif batch_dorm_id and batch_category:
            st.warning("在此宿舍中找不到符合此分類的設備。")
    
    with st.expander("📜 批次新增合規紀錄 (如: 水質檢測)"):
        st.info("此功能用於一次性為同一宿舍、同一類別的多台設備登記合規檢測紀錄。")
        batch_comp_c1, batch_comp_c2 = st.columns(2)
        batch_comp_dorm_id = batch_comp_c1.selectbox("步驟一：選擇宿舍*", options=[None] + list(dorm_options.keys()), format_func=lambda x: "請選擇..." if x is None else dorm_options.get(x), key="batch_comp_dorm")
        categories_for_batch_comp = equipment_model.get_distinct_equipment_categories()
        batch_comp_category = batch_comp_c2.selectbox("步驟二：選擇設備分類*", options=[None] + categories_for_batch_comp, format_func=lambda x: "請選擇..." if x is None else x, key="batch_comp_category")
        equipment_to_batch_comp = pd.DataFrame()
        if batch_comp_dorm_id and batch_comp_category:
            equipment_to_batch_comp = equipment_model.get_equipment_for_view({"dorm_id": batch_comp_dorm_id, "category": batch_comp_category})
        if not equipment_to_batch_comp.empty:
            with st.form("batch_compliance_form"):
                st.markdown("##### 步驟三：勾選要更新的設備")
                equipment_to_batch_comp.insert(0, "選取", True)
                edited_comp_df = st.data_editor(equipment_to_batch_comp, hide_index=True, disabled=equipment_to_batch_comp.columns.drop("選取"), key="batch_comp_editor")
                st.markdown("---")
                st.markdown("##### 步驟四：填寫共同的檢測資訊")
                comp_info_c1, comp_info_c2, comp_info_c3 = st.columns(3)
                batch_comp_item = comp_info_c1.text_input("申報/檢測項目*", placeholder="例如: 114年Q4水質檢測")
                batch_comp_cert_date = comp_info_c1.date_input("收到憑證/完成日期*", value=date.today(), key="batch_comp_date")
                batch_comp_next_date = comp_info_c2.date_input("下次申報/檢測日期 (選填)", value=None, key="batch_comp_next_date", help="若留空，系統將依各設備週期自動計算。若填寫，則所有設備皆使用此日期。")
                batch_comp_total_cost = comp_info_c3.number_input("總費用 (選填)", min_value=0, step=100, help="此金額將會平均分攤到所有選取的設備上。")
                batch_comp_payment_date = comp_info_c3.date_input("支付日期 (選填)", value=date.today(), key="batch_comp_payment")
                batch_comp_submitted = st.form_submit_button("🚀 執行批次新增")
                if batch_comp_submitted:
                    selected_equipment_comp = edited_comp_df[edited_comp_df["選取"]]
                    if selected_equipment_comp.empty:
                        st.error("請至少選取一台設備！")
                    elif not batch_comp_item:
                        st.error("請填寫「申報/檢測項目」！")
                    else:
                        equipment_ids = selected_equipment_comp['id'].tolist()
                        compliance_info = {"dorm_id": batch_comp_dorm_id, "declaration_item": batch_comp_item, "certificate_date": batch_comp_cert_date, "next_declaration_start": batch_comp_next_date, "total_amount": batch_comp_total_cost, "payment_date": batch_comp_payment_date, "record_type": batch_comp_category}
                        with st.spinner(f"正在為 {len(equipment_ids)} 台設備新增合規紀錄..."):
                            success, message = equipment_model.batch_add_compliance_logs(equipment_ids, compliance_info)
                        if success:
                            st.success(message); st.cache_data.clear(); st.rerun()
                        else:
                            st.error(message)
        elif batch_comp_dorm_id and batch_comp_category:
            st.warning("在此宿舍中找不到符合此分類的設備。")

    with st.expander("🔢 批次新增編號設備"):
        with st.form("batch_create_numbered_form", clear_on_submit=True):
            st.markdown("##### 步驟一：選擇位置與命名規則")
            bc_c1, bc_c2, bc_c3, bc_c4 = st.columns(4)
            batch_create_dorm_id = bc_c1.selectbox( "選擇宿舍*", options=list(dorm_options.keys()), format_func=lambda x: dorm_options.get(x, "未知宿舍"), key="bc_dorm" )
            batch_create_base_name = bc_c2.text_input("設備基本名稱*", placeholder="例如: 飲水機")
            batch_create_quantity = bc_c3.number_input("數量*", min_value=1, step=1, value=1)
            batch_create_start_num = bc_c4.number_input("起始編號*", min_value=1, step=1, value=1)
            st.markdown("##### 步驟二：填寫共同的設備資訊")
            bc_c5, bc_c6, bc_c7 = st.columns(3)
            batch_create_category = bc_c5.selectbox("設備分類", ["消防設備", "電器用品", "飲水設備", "傢俱", "其他"], key="bc_category")
            batch_create_location = bc_c6.text_input("共同放置位置", placeholder="例如: 2F走廊")
            batch_create_vendor_id = bc_c7.selectbox("供應廠商", options=[None] + list(vendor_options.keys()), format_func=lambda x: "未指定" if x is None else vendor_options.get(x), key="bc_vendor")
            bc_c8, bc_c9, bc_c10 = st.columns(3)
            batch_create_cost = bc_c8.number_input("單台採購金額 (選填)", min_value=0, step=100, help="這是「每一台」設備的成本，系統會為每台設備建立一筆費用紀錄。")
            batch_create_install_date = bc_c9.date_input("安裝/啟用日期", value=None, min_value=fifteen_years_ago)
            batch_last_maintenance_date = bc_c10.date_input("上次保養日期 (選填)", value=None)
            st.markdown("##### 步驟三：設定週期 (選填)")
            bc_c11, bc_c12 = st.columns(2)
            batch_maintenance_interval = bc_c11.number_input("一般保養週期 (月)", min_value=0, step=1, help="例如更換濾心。填 0 代表不需定期保養。")
            batch_compliance_interval = bc_c12.number_input("合規檢測週期 (月)", min_value=0, step=1, help="例如水質檢測週期。填 0 代表不需定期檢測。")
            batch_create_notes = st.text_area("設備備註 (選填)", key="bc_notes")
            bc_submitted = st.form_submit_button("🚀 執行批次新增")
            if bc_submitted:
                if not batch_create_base_name:
                    st.error("請填寫「設備基本名稱」！")
                else:
                    next_maintenance_date = None
                    if batch_last_maintenance_date and batch_maintenance_interval > 0:
                        next_maintenance_date = batch_last_maintenance_date + relativedelta(months=batch_maintenance_interval)
                    base_details = { "dorm_id": batch_create_dorm_id, "equipment_name": batch_create_base_name, "equipment_category": batch_create_category, "location": batch_create_location, "vendor_id": batch_create_vendor_id, "purchase_cost": batch_create_cost, "installation_date": batch_create_install_date, "status": "正常", "maintenance_interval_months": batch_maintenance_interval if batch_maintenance_interval > 0 else None, "compliance_interval_months": batch_compliance_interval if batch_compliance_interval > 0 else None, "last_maintenance_date": batch_last_maintenance_date, "next_maintenance_date": next_maintenance_date, "notes": batch_create_notes }
                    with st.spinner(f"正在批次新增 {batch_create_quantity} 台設備..."):
                        success_count, message = equipment_model.batch_create_numbered_equipment( base_details, batch_create_quantity, batch_create_start_num )
                    if success_count > 0:
                        st.success(message); st.cache_data.clear(); st.rerun()
                    else:
                        st.error(message)

    with st.expander("➕ 新增一筆設備紀錄"):
        selected_dorm_id_for_add = st.selectbox("請選擇要新增設備的宿舍：", options=list(dorm_options.keys()), format_func=lambda x: dorm_options.get(x, "未知宿舍"), key="add_dorm_select")
        if selected_dorm_id_for_add:
            with st.form("new_equipment_form", clear_on_submit=True):
                st.subheader("設備基本資料")
                c1, c2, c3 = st.columns(3)
                equipment_name = c1.text_input("設備名稱 (必填)", placeholder="例如: 2F飲水機")
                equipment_category = c2.selectbox("設備分類", ["消防設備", "電器用品", "飲水設備", "傢俱", "其他"])
                location = c3.text_input("放置位置", placeholder="例如: 2F走廊, A01房")
                c4, c5, c6 = st.columns(3)
                brand_model = c4.text_input("品牌/型號")
                serial_number = c5.text_input("序號/批號")
                vendor_id = c6.selectbox("供應廠商 (選填)", options=[None] + list(vendor_options.keys()), format_func=lambda x: "未指定" if x is None else vendor_options.get(x), key="single_add_vendor")
                installation_date = st.date_input("安裝/啟用日期", value=None, min_value=fifteen_years_ago)
                purchase_cost = st.number_input("採購金額 (選填)", min_value=0, step=100, help="若填寫此金額，系統將自動新增一筆對應的單次費用紀錄。")
                st.subheader("保養與狀態")
                c7, c8, c9 = st.columns(3)
                maintenance_interval = c7.number_input("一般保養週期 (月)", min_value=0, step=1, help="例如更換濾心。填 0 代表不需定期保養。")
                last_maintenance_date = c8.date_input("上次保養日期", value=None)
                calculated_next_date = None
                if last_maintenance_date and maintenance_interval > 0:
                    calculated_next_date = last_maintenance_date + relativedelta(months=maintenance_interval)
                next_maintenance_date = c9.date_input("下次保養/檢查日期", value=calculated_next_date, help="若有填寫上次保養日和週期，此欄位會自動計算。")
                compliance_interval = st.number_input("合規檢測週期 (月)", min_value=0, step=1, help="例如水質檢測週期。填 0 代表不需定期檢測。")
                status = st.selectbox("目前狀態", ["正常", "需保養", "維修中", "已報廢"])
                notes = st.text_area("設備備註", key="single_notes")
                submitted = st.form_submit_button("儲存設備紀錄")
                if submitted:
                    if not equipment_name:
                        st.error("「設備名稱」為必填欄位！")
                    else:
                        details = { "dorm_id": selected_dorm_id_for_add, "equipment_name": equipment_name, "vendor_id": vendor_id, "equipment_category": equipment_category, "location": location, "brand_model": brand_model, "serial_number": serial_number, "purchase_cost": purchase_cost, "installation_date": installation_date, "maintenance_interval_months": maintenance_interval if maintenance_interval > 0 else None, "compliance_interval_months": compliance_interval if compliance_interval > 0 else None, "last_maintenance_date": last_maintenance_date, "next_maintenance_date": next_maintenance_date, "status": status, "notes": notes }
                        success, message, _ = equipment_model.add_equipment_record(details)
                        if success:
                            st.success(message); st.cache_data.clear(); st.rerun()
                        else:
                            st.error(message)

    st.markdown("---")
    
    st.subheader("現有設備總覽")
    f_col1, f_col2 = st.columns(2)
    selected_dorm_id_filter = f_col1.selectbox( "依宿舍篩選：", options=[None] + list(dorm_options.keys()), format_func=lambda x: "所有宿舍" if x is None else dorm_options.get(x))
    categories = equipment_model.get_distinct_equipment_categories()
    selected_category_filter = f_col2.selectbox("依設備分類篩選：", options=[None] + categories, format_func=lambda x: "所有分類" if x is None else x)
    if st.button("🔄 重新整理設備列表"):
        st.cache_data.clear()
    filters = {}
    if selected_dorm_id_filter: filters["dorm_id"] = selected_dorm_id_filter
    if selected_category_filter: filters["category"] = selected_category_filter
    @st.cache_data
    def get_equipment(filters):
        return equipment_model.get_equipment_for_view(filters)
    equipment_df = get_equipment(filters)

    if equipment_df.empty:
        st.info("在目前的篩選條件下，找不到任何設備紀錄。")
    else:
        # --- 【核心修改】在此處加入 column_config ---
        st.dataframe(
            equipment_df, 
            width="stretch", 
            hide_index=True,
            column_config={
                "id": None, # 隱藏 id 欄位
                "保養週期(月)": st.column_config.NumberColumn(
                    "保養週期",
                    help="一般保養的間隔月數",
                    format="%d 月"
                ),
                "合規週期(月)": st.column_config.NumberColumn(
                    "合規週期",
                    help="合規檢測的間隔月數",
                    format="%d 月"
                ),
                "下次保養/檢查日": st.column_config.DateColumn(
                    "下次保養/檢查日",
                    format="YYYY-MM-DD"
                )
            }
        )
        st.markdown("---")
        st.subheader("檢視設備詳細資料與歷史紀錄")
        options_dict = {row['id']: f"ID:{row['id']} - {row['宿舍地址']} / {row['設備名稱']} ({row.get('位置', '')})" for _, row in equipment_df.iterrows()}
        selected_id = st.selectbox("請從上方總覽列表選擇要操作的設備：", [None] + list(options_dict.keys()), format_func=lambda x: "請選擇..." if x is None else options_dict.get(x))
        
        # --- 編輯區塊 (維持不變) ---
        if selected_id:
            if 'active_tab' not in st.session_state: st.session_state.active_tab = "📝 編輯基本資料"
            tab_names = ["📝 編輯基本資料", "🔧 維修/保養歷史", "📜 合規紀錄"]
            selected_tab = st.radio("管理選項:", tab_names, key="active_tab", horizontal=True, label_visibility="collapsed")

            if selected_tab == "📝 編輯基本資料":
                details = equipment_model.get_single_equipment_details(selected_id)
                if details:
                    with st.form(f"edit_equipment_form_{selected_id}"):
                        st.markdown(f"##### 正在編輯 ID: {details['id']} 的設備")
                        current_dorm_id = details.get('dorm_id')
                        dorm_keys = list(dorm_options.keys())
                        try:
                            current_index = dorm_keys.index(current_dorm_id)
                        except ValueError:
                            current_index = 0
                        e_dorm_id = st.selectbox("宿舍地址", options=dorm_keys, format_func=lambda x: dorm_options.get(x), index=current_index)
                        ec1, ec2, ec3 = st.columns(3)
                        e_equipment_name = ec1.text_input("設備名稱", value=details.get('equipment_name', ''))
                        e_equipment_category = ec2.selectbox("設備分類", ["消防設備", "電器用品", "飲水設備", "傢俱", "其他"], index=["消防設備", "電器用品", "飲水設備", "傢俱", "其他"].index(details.get('equipment_category')) if details.get('equipment_category') in ["消防設備", "電器用品", "飲水設備", "傢俱", "其他"] else 4)
                        e_location = ec3.text_input("放置位置", value=details.get('location', ''))
                        ec4, ec5, ec6 = st.columns(3)
                        e_brand_model = ec4.text_input("品牌/型號", value=details.get('brand_model', ''))
                        e_serial_number = ec5.text_input("序號/批號", value=details.get('serial_number', ''))
                        current_vendor_id = details.get('vendor_id')
                        vendor_keys = [None] + list(vendor_options.keys())
                        vendor_index = vendor_keys.index(current_vendor_id) if current_vendor_id in vendor_keys else 0
                        e_vendor_id = ec6.selectbox("供應廠商 (選填)", options=vendor_keys, format_func=lambda x: "未指定" if x is None else vendor_options.get(x), index=vendor_index)
                        e_installation_date = st.date_input("安裝/啟用日期", value=details.get('installation_date'), min_value=fifteen_years_ago)
                        st.number_input("採購金額", value=details.get('purchase_cost') or 0, disabled=True, help="採購金額於新增時決定，若需調整請至年度費用頁面修改對應的費用紀錄。")
                        st.subheader("保養與狀態")
                        ec7, ec8, ec9 = st.columns(3)
                        e_maintenance_interval = ec7.number_input("一般保養週期 (月)", min_value=0, step=1, value=details.get('maintenance_interval_months') or 0)
                        e_last_maintenance_date = ec8.date_input("上次保養日期", value=details.get('last_maintenance_date'))
                        e_calculated_next_date = None
                        if e_last_maintenance_date and e_maintenance_interval > 0:
                            e_calculated_next_date = e_last_maintenance_date + relativedelta(months=e_maintenance_interval)
                        e_next_maintenance_date = ec9.date_input("下次保養/檢查日期", value=e_calculated_next_date or details.get('next_maintenance_date'))
                        e_compliance_interval = st.number_input("合規檢測週期 (月)", min_value=0, step=1, value=details.get('compliance_interval_months') or 0, help="例如水質檢測週期。")
                        e_status = st.selectbox("目前狀態", ["正常", "需保養", "維修中", "已報廢"], index=["正常", "需保養", "維修中", "已報廢"].index(details.get('status')) if details.get('status') in ["正常", "需保養", "維修中", "已報廢"] else 0)
                        e_notes = st.text_area("設備備註", value=details.get('notes', ''))
                        
                        if st.form_submit_button("儲存變更"):
                            update_data = { "dorm_id": e_dorm_id, "vendor_id": e_vendor_id, "equipment_name": e_equipment_name, "equipment_category": e_equipment_category, "location": e_location, "brand_model": e_brand_model, "serial_number": e_serial_number, "installation_date": e_installation_date, "maintenance_interval_months": e_maintenance_interval if e_maintenance_interval > 0 else None, "compliance_interval_months": e_compliance_interval if e_compliance_interval > 0 else None, "last_maintenance_date": e_last_maintenance_date, "next_maintenance_date": e_next_maintenance_date, "status": e_status, "notes": e_notes }
                            success, message = equipment_model.update_equipment_record(selected_id, update_data)
                            if success: st.success(message); st.cache_data.clear(); st.rerun()
                            else: st.error(message)
                    st.markdown("---")
                    st.markdown("##### 危險操作區")
                    confirm_delete = st.checkbox("我了解並確認要刪除此筆設備紀錄", key=f"delete_confirm_{selected_id}")
                    if st.button("🗑️ 刪除此紀錄", type="primary", disabled=not confirm_delete, key=f"delete_button_{selected_id}"):
                        success, message = equipment_model.delete_equipment_record(selected_id)
                        if success: st.success(message); st.cache_data.clear(); st.rerun()
                        else: st.error(message)

            elif selected_tab == "🔧 維修/保養歷史":
                st.subheader("🔧 維修/保養歷史")
                maintenance_history = equipment_model.get_related_maintenance_logs(selected_id)
                st.dataframe(maintenance_history, width="stretch", hide_index=True, column_config={"id": None})
                st.markdown("---")
                st.markdown("##### 新增 / 編輯 / 刪除 歷史紀錄")
                log_options = {row['id']: f"ID:{row['id']} - {row['通報日期']} {row['項目類型']}" for _, row in maintenance_history.iterrows()}
                selected_log_id = st.selectbox("選擇一筆紀錄進行操作，或新增一筆：", [None] + list(log_options.keys()), format_func=lambda x: "➕ 新增一筆紀錄" if x is None else f"✏️ 編輯 {log_options[x]}", key="maintenance_log_selector")
                if selected_log_id:
                    log_details = maintenance_model.get_single_log_details(selected_log_id)
                    with st.form(f"edit_maintenance_log_{selected_log_id}"):
                        st.markdown(f"###### 正在編輯 ID: {selected_log_id}")
                        emc1, emc2, emc3 = st.columns(3)
                        e_ml_date = emc1.date_input("通報/完成日期", value=log_details.get('notification_date'))
                        e_ml_type = emc2.selectbox("項目類型", ["定期保養", "更換耗材", "維修"], index=["定期保養", "更換耗材", "維修"].index(log_details.get('item_type')) if log_details.get('item_type') in ["定期保養", "更換耗材", "維修"] else 0)
                        e_ml_status = emc3.selectbox("狀態", ["待處理", "進行中", "已完成"], index=["待處理", "進行中", "已完成"].index(log_details.get('status')) if log_details.get('status') in ["待處理", "進行中", "已完成"] else 2)
                        e_ml_desc = st.text_input("細項說明", value=log_details.get('description'))
                        emc4, emc5 = st.columns(2)
                        e_ml_cost = emc4.number_input("費用", min_value=0, value=log_details.get('cost') or 0)
                        e_ml_vendor = emc5.selectbox("執行廠商", options=[None] + list(vendor_options.keys()), format_func=lambda x: "未指定" if x is None else vendor_options.get(x), index=([None] + list(vendor_options.keys())).index(log_details.get('vendor_id')) if log_details.get('vendor_id') in [None] + list(vendor_options.keys()) else 0)
                        col_edit, col_delete = st.columns(2)
                        if col_edit.form_submit_button("儲存變更"):
                            update_data = {"notification_date": e_ml_date, "completion_date": e_ml_date, "item_type": e_ml_type, "status": e_ml_status, "description": e_ml_desc, "cost": e_ml_cost, "vendor_id": e_ml_vendor}
                            success, message = maintenance_model.update_log(selected_log_id, update_data)
                            if success: st.success(message); st.cache_data.clear(); st.rerun()
                            else: st.error(message)
                        if col_delete.form_submit_button("🗑️ 刪除此筆紀錄", type="secondary"):
                            success, message = maintenance_model.delete_log(selected_log_id)
                            if success: st.success(message); st.cache_data.clear(); st.rerun()
                            else: st.error(message)
                else:
                    with st.form(f"add_maintenance_log_{selected_id}", clear_on_submit=True):
                        st.markdown("###### 正在新增一筆紀錄")
                        details = equipment_model.get_single_equipment_details(selected_id)
                        amc1, amc2, amc3 = st.columns(3)
                        a_ml_date = amc1.date_input("通報/完成日期", value=date.today())
                        a_ml_type = amc2.selectbox("項目類型", ["定期保養", "更換耗材", "維修"])
                        a_ml_desc = st.text_input("細項說明", placeholder="例如: 更換RO膜濾心")
                        amc4, amc5 = st.columns(2)
                        a_ml_cost = amc4.number_input("費用", min_value=0, step=100)
                        a_ml_vendor = amc5.selectbox("執行廠商 (選填)", options=[None] + list(vendor_options.keys()), format_func=lambda x: "未指定" if x is None else vendor_options.get(x))
                        if st.form_submit_button("新增紀錄"):
                            if not a_ml_desc: st.error("請填寫「細項說明」！")
                            else:
                                log_details = { 'dorm_id': details['dorm_id'], 'equipment_id': selected_id, 'notification_date': a_ml_date, 'completion_date': a_ml_date, 'item_type': a_ml_type, 'description': a_ml_desc, 'cost': a_ml_cost if a_ml_cost > 0 else None, 'vendor_id': a_ml_vendor, 'status': '已完成' }
                                success, message = maintenance_model.add_log(log_details)
                                if success: st.success(message); st.cache_data.clear(); st.rerun()
                                else: st.error(message)
            
            elif selected_tab == "📜 合規紀錄":
                st.subheader("📜 合規紀錄")
                st.info("此區塊用於記錄需政府或第三方單位認證的紀錄，例如飲水機的水質檢測報告。")
                compliance_history = equipment_model.get_related_compliance_records(selected_id)
                st.dataframe(compliance_history, width="stretch", hide_index=True, column_config={"id": None})
                st.markdown("---")
                st.markdown("##### 新增 / 編輯 / 刪除 合規紀錄")
                comp_options = {row['id']: f"ID:{row['id']} - {row.get('支付日期')} {row.get('申報項目')}" for _, row in compliance_history.iterrows()}
                selected_comp_id = st.selectbox("選擇一筆紀錄進行操作，或新增一筆：", [None] + list(comp_options.keys()), format_func=lambda x: "➕ 新增一筆紀錄" if x is None else f"✏️ 編輯 {comp_options[x]}", key="compliance_log_selector")
                if selected_comp_id:
                    comp_details = finance_model.get_single_compliance_details(selected_comp_id)
                    expense_details = finance_model.get_expense_details_by_compliance_id(selected_comp_id)
                    with st.form(f"edit_compliance_log_{selected_comp_id}"):
                        st.markdown(f"###### 正在編輯 ID: {selected_comp_id}")
                        ecc1, ecc2, ecc3 = st.columns(3)
                        e_cl_item = ecc1.text_input("申報項目", value=comp_details.get('declaration_item', ''))
                        e_cl_cert_date = ecc2.date_input("收到憑證/完成日期", value=comp_details.get('certificate_date'))
                        e_cl_next_date = ecc3.date_input("下次申報/檢測日期", value=comp_details.get('next_declaration_start'))
                        ecc4, ecc5 = st.columns(2)
                        e_cl_cost = ecc4.number_input("相關費用", min_value=0, value=expense_details.get('total_amount', 0) if expense_details else 0)
                        e_cl_pay_date = ecc5.date_input("支付日期", value=expense_details.get('payment_date') if expense_details else None)
                        col_edit_comp, col_delete_comp = st.columns(2)
                        if col_edit_comp.form_submit_button("儲存變更"):
                            updated_expense_data = {"payment_date": e_cl_pay_date, "total_amount": e_cl_cost}
                            updated_compliance_data = {"declaration_item": e_cl_item, "certificate_date": e_cl_cert_date, "next_declaration_start": e_cl_next_date}
                            success, message = finance_model.update_compliance_expense_record(expense_details['id'] if expense_details else None, updated_expense_data, selected_comp_id, updated_compliance_data, comp_details.get('record_type', '合規紀錄'))
                            if success: 
                                st.success(message); st.cache_data.clear(); st.rerun()
                            else: 
                                st.error(message)
                        if col_delete_comp.form_submit_button("🗑️ 刪除此筆紀錄", type="secondary"):
                            success, message = finance_model.delete_compliance_expense_record(selected_comp_id)
                            if success: st.success(message); st.cache_data.clear(); st.rerun()
                            else: st.error(message)
                else:
                    with st.form(f"add_compliance_log_{selected_id}", clear_on_submit=True):
                        st.markdown("###### 正在新增一筆紀錄")
                        details = equipment_model.get_single_equipment_details(selected_id)
                        acc1, acc2, acc3 = st.columns(3)
                        a_cl_item = acc1.text_input("申報項目", placeholder="例如: 114年Q4水質檢測")
                        a_cl_cert_date = acc2.date_input("收到憑證/完成日期", value=None)
                        compliance_interval = details.get('compliance_interval_months')
                        calculated_next_date = None
                        if a_cl_cert_date and compliance_interval and compliance_interval > 0:
                            calculated_next_date = a_cl_cert_date + relativedelta(months=compliance_interval)
                        a_cl_next_date = acc3.date_input("下次申報/檢測日期", value=calculated_next_date, help="若設備已設定合規檢測週期，此欄位會自動計算。")
                        acc4, acc5 = st.columns(2)
                        a_cl_cost = acc4.number_input("相關費用 (選填)", min_value=0, step=100)
                        a_cl_pay_date = acc5.date_input("支付日期 (選填)", value=None)
                        
                        if st.form_submit_button("新增紀錄"):
                            if not a_cl_item:
                                st.error("請填寫「申報項目」！")
                            elif not a_cl_cert_date:
                                st.error("請填寫「收到憑證/完成日期」！")
                            else:
                                record_details = { "dorm_id": details['dorm_id'], "equipment_id": selected_id, "details": { "declaration_item": a_cl_item, "certificate_date": a_cl_cert_date, "next_declaration_start": a_cl_next_date } }
                                expense_details = None
                                if a_cl_cost > 0:
                                    expense_details = { "dorm_id": details['dorm_id'], "expense_item": f"{details['equipment_name']}-{a_cl_item}", "payment_date": a_cl_pay_date, "total_amount": a_cl_cost, "amortization_start_month": a_cl_pay_date.strftime('%Y-%m'), "amortization_end_month": a_cl_pay_date.strftime('%Y-%m') }
                                success, message, _ = finance_model.add_compliance_record(details['equipment_category'], record_details, expense_details)
                                if success:
                                    st.success(message); st.cache_data.clear(); st.rerun()
                                else:
                                    st.error(message)