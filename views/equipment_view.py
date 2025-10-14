# 檔案路徑: views/equipment_view.py

import streamlit as st
import pandas as pd
from datetime import date
from dateutil.relativedelta import relativedelta
from data_models import equipment_model, dormitory_model, maintenance_model, vendor_model, finance_model

def render():
    """渲染「設備管理」頁面"""
    st.header("我司管理宿舍 - 設備管理")
    st.info("用於登錄、追蹤宿舍內的消防、電器、飲水等各類設備及其完整的生命週期紀錄。")

    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍。")
        return

    dorm_options = {d['id']: d['original_address'] for d in my_dorms}
    selected_dorm_id = st.selectbox(
        "請選擇要管理的宿舍：",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options.get(x, "未知宿舍")
    )

    if not selected_dorm_id:
        return

    st.markdown("---")

    with st.expander("➕ 新增一筆設備紀錄"):
        with st.form("new_equipment_form", clear_on_submit=True):
            st.subheader("設備基本資料")
            c1, c2, c3 = st.columns(3)
            equipment_name = c1.text_input("設備名稱 (必填)", placeholder="例如: 2F飲水機")
            equipment_category = c2.selectbox("設備分類", ["消防設備", "電器用品", "飲水設備", "傢俱", "其他"])
            location = c3.text_input("放置位置", placeholder="例如: 2F走廊, A01房")

            c4, c5, c6 = st.columns(3)
            brand_model = c4.text_input("品牌/型號")
            serial_number = c5.text_input("序號/批號")
            installation_date = c6.date_input("安裝/啟用日期", value=None)
            
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
            notes = st.text_area("設備備註")

            submitted = st.form_submit_button("儲存設備紀錄")
            if submitted:
                if not equipment_name:
                    st.error("「設備名稱」為必填欄位！")
                else:
                    details = {
                        "dorm_id": selected_dorm_id, "equipment_name": equipment_name,
                        "equipment_category": equipment_category, "location": location,
                        "brand_model": brand_model, "serial_number": serial_number,
                        "purchase_cost": purchase_cost,
                        "installation_date": installation_date,
                        "maintenance_interval_months": maintenance_interval if maintenance_interval > 0 else None,
                        "compliance_interval_months": compliance_interval if compliance_interval > 0 else None,
                        "last_maintenance_date": last_maintenance_date,
                        "next_maintenance_date": next_maintenance_date,
                        "status": status, "notes": notes
                    }
                    success, message, _ = equipment_model.add_equipment_record(details)
                    if success:
                        st.success(message); st.cache_data.clear(); st.rerun()
                    else:
                        st.error(message)

    st.markdown("---")
    
    st.subheader(f"現有設備總覽: {dorm_options.get(selected_dorm_id)}")
    
    if st.button("🔄 重新整理設備列表"):
        st.cache_data.clear()

    @st.cache_data
    def get_equipment(dorm_id):
        return equipment_model.get_equipment_for_dorm_as_df(dorm_id)

    equipment_df = get_equipment(selected_dorm_id)

    if equipment_df.empty:
        st.info("此宿舍尚無任何設備紀錄。")
    else:
        st.dataframe(equipment_df, width="stretch", hide_index=True)
        
        st.markdown("---")
        st.subheader("檢視設備詳細資料與歷史紀錄")
        
        options_dict = {row['id']: f"ID:{row['id']} - {row['設備名稱']} ({row.get('位置', '')})" for _, row in equipment_df.iterrows()}
        selected_id = st.selectbox("請選擇要操作的設備：", [None] + list(options_dict.keys()), format_func=lambda x: "請選擇..." if x is None else options_dict.get(x))

        if selected_id:
            tab1, tab2, tab3 = st.tabs(["📝 編輯基本資料", "🔧 維修/保養歷史", "📜 合規紀錄"])

            with tab1:
                details = equipment_model.get_single_equipment_details(selected_id)
                if details:
                    with st.form(f"edit_equipment_form_{selected_id}"):
                        st.markdown(f"##### 正在編輯 ID: {details['id']} 的設備")
                        ec1, ec2, ec3 = st.columns(3)
                        e_equipment_name = ec1.text_input("設備名稱", value=details.get('equipment_name', ''))
                        e_equipment_category = ec2.selectbox("設備分類", ["消防設備", "電器用品", "飲水設備", "傢俱", "其他"], index=["消防設備", "電器用品", "飲水設備", "傢俱", "其他"].index(details.get('equipment_category')) if details.get('equipment_category') in ["消防設備", "電器用品", "飲水設備", "傢俱", "其他"] else 4)
                        e_location = ec3.text_input("放置位置", value=details.get('location', ''))
                        ec4, ec5, ec6 = st.columns(3)
                        e_brand_model = ec4.text_input("品牌/型號", value=details.get('brand_model', ''))
                        e_serial_number = ec5.text_input("序號/批號", value=details.get('serial_number', ''))
                        e_installation_date = ec6.date_input("安裝/啟用日期", value=details.get('installation_date'))

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
                        edit_submitted = st.form_submit_button("儲存變更")
                        if edit_submitted:
                            update_data = { "equipment_name": e_equipment_name, "equipment_category": e_equipment_category, "location": e_location, "brand_model": e_brand_model, "serial_number": e_serial_number, "installation_date": e_installation_date, "maintenance_interval_months": e_maintenance_interval if e_maintenance_interval > 0 else None, "compliance_interval_months": e_compliance_interval if e_compliance_interval > 0 else None, "last_maintenance_date": e_last_maintenance_date, "next_maintenance_date": e_next_maintenance_date, "status": e_status, "notes": e_notes }
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

            with tab2:
                st.markdown("##### 新增維修/保養紀錄")
                st.info("可在此快速為這台設備建立一筆維修或保養紀錄。")
                vendors = vendor_model.get_vendors_for_view()
                vendor_options = {v['id']: f"{v['服務項目']} - {v['廠商名稱']}" for _, v in vendors.iterrows()} if not vendors.empty else {}
                with st.form(f"quick_add_maintenance_{selected_id}", clear_on_submit=True):
                    m_c1, m_c2 = st.columns(2)
                    item_type = m_c1.selectbox("項目類型", ["定期保養", "更換耗材", "維修"])
                    description = m_c2.text_input("細項說明 (必填)", placeholder="例如: 更換RO膜濾心")
                    cost = st.number_input("本次費用", min_value=0, step=100)
                    vendor_id = st.selectbox("執行廠商 (選填)", options=[None] + list(vendor_options.keys()), format_func=lambda x: "未指定" if x is None else vendor_options.get(x))
                    submitted = st.form_submit_button("新增紀錄")
                    if submitted:
                        if not description: st.error("「細項說明」為必填欄位！")
                        else:
                            log_details = { 'dorm_id': selected_dorm_id, 'equipment_id': selected_id, 'notification_date': date.today(), 'item_type': item_type, 'description': description, 'cost': cost if cost > 0 else None, 'vendor_id': vendor_id, 'status': '進行中' }
                            success, message = maintenance_model.add_log(log_details)
                            if success: st.success(message); st.cache_data.clear(); st.rerun()
                            else: st.error(message)
                st.markdown("##### 歷史紀錄")
                maintenance_history = equipment_model.get_related_maintenance_logs(selected_id)
                
                edited_df = st.data_editor(
                    maintenance_history, width="stretch", hide_index=True,
                    column_config={
                        "id": st.column_config.CheckboxColumn(
                            "完成此項?",
                            help="勾選狀態為「進行中」的保養紀錄，並點擊下方按鈕來完成它。",
                            default=False,
                        )
                    },
                    key=f"maintenance_table_{selected_id}"
                )
                
                # --- 【核心修正】使用 .get() 安全地訪問 session_state ---
                selected_log_ids = [row['id'] for i, row in edited_df.iterrows() if row['id']]

                if st.button("✓ 將勾選的紀錄標示為完成", disabled=not selected_log_ids):
                    completed_count = 0
                    for log_id in selected_log_ids:
                        success, msg = equipment_model.complete_maintenance_and_schedule_next(log_id)
                        if success:
                            completed_count += 1
                        else:
                            st.error(f"更新紀錄 ID {log_id} 失敗: {msg}")
                    if completed_count > 0:
                        st.success(f"成功將 {completed_count} 筆紀錄標示為完成，並已自動更新保養排程！")
                        st.cache_data.clear()
                        st.rerun()
            
            with tab3:
                st.info("此區塊用於記錄需政府或第三方單位認證的紀錄，例如飲水機的水質檢測報告。")
                with st.expander("➕ 新增合規紀錄 (如: 水質檢測)"):
                    with st.form(f"new_compliance_form_{selected_id}", clear_on_submit=True):
                        st.markdown("##### 檢測資訊")
                        co1, co2, co3 = st.columns(3)
                        declaration_item = co1.text_input("申報項目", value="水質檢測")
                        certificate_date = co2.date_input("收到憑證/完成日期", value=date.today())
                        
                        compliance_interval = details.get('compliance_interval_months')
                        calculated_next_compliance_date = None
                        if certificate_date and compliance_interval and compliance_interval > 0:
                            calculated_next_compliance_date = certificate_date + relativedelta(months=compliance_interval)

                        next_declaration_start = co3.date_input(
                            "下次申報/檢測日期", 
                            value=calculated_next_compliance_date, 
                            help="若設備已設定合規檢測週期，此欄位會自動計算。"
                        )
                        
                        st.markdown("##### 相關費用 (選填)")
                        co4, co5 = st.columns(2)
                        payment_date = co4.date_input("支付日期", value=None)
                        total_amount = co5.number_input("總金額", min_value=0, step=100)
                        
                        compliance_submitted = st.form_submit_button("儲存檢測紀錄")
                        if compliance_submitted:
                            record_details = {
                                "dorm_id": selected_dorm_id, "equipment_id": selected_id,
                                "details": { "declaration_item": declaration_item, "certificate_date": certificate_date, "next_declaration_start": next_declaration_start }
                            }
                            expense_details = {
                                "dorm_id": selected_dorm_id, "expense_item": f"{declaration_item}",
                                "payment_date": payment_date, "total_amount": total_amount,
                                "amortization_start_month": payment_date.strftime('%Y-%m') if payment_date else None,
                                "amortization_end_month": payment_date.strftime('%Y-%m') if payment_date else None,
                            }
                            success, message, _ = finance_model.add_compliance_record('水質檢測', record_details, expense_details if total_amount > 0 else None)
                            if success:
                                st.success(message); st.cache_data.clear(); st.rerun()
                            else:
                                st.error(message)

                st.markdown("##### 歷史紀錄")
                compliance_history = equipment_model.get_related_compliance_records(selected_id)
                st.dataframe(compliance_history, width="stretch", hide_index=True)