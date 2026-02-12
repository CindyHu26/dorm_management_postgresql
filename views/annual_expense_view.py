import streamlit as st
import pandas as pd
import json
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from data_models import finance_model, dormitory_model, vendor_model 

def render():
    st.title("💰 年度/攤銷費用管理")

    # === 新增：模式切換 ===
    mode = st.radio(
        "檢視模式", 
        ["🏢 依宿舍檢視/管理 (原始功能)", "📋 依項目彙總檢視 (跨宿舍)"], 
        horizontal=True
    )
    st.markdown("---")

    if mode == "🏢 依宿舍檢視/管理 (原始功能)":
        render_by_dorm_view() # 呼叫原本的邏輯
    else:
        render_by_item_view() # 呼叫新功能

def render_by_dorm_view():
    """渲染「年度費用管理」頁面"""
    st.header("我司管理宿舍 - 長期攤銷費用管理")

    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前資料庫中沒有主要管理人為「我司」的宿舍。")
        return

    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}
    selected_dorm_id = st.selectbox(
        "請選擇要管理的宿舍：",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options.get(x, "未知宿舍")
    )
    if not selected_dorm_id: return
    st.markdown("---")

    st.subheader(f"歷史費用總覽: {dorm_options.get(selected_dorm_id)}")
    if st.button("🔄 重新整理費用列表"):
        st.cache_data.clear()
        st.rerun()

    @st.cache_data
    def get_all_annual_expenses(dorm_id):
        return finance_model.get_all_annual_expenses_for_dorm(dorm_id)

    all_expenses_df = get_all_annual_expenses(selected_dorm_id)

    if all_expenses_df.empty:
        st.info("此宿舍尚無任何長期費用紀錄。")
    else:
        selection = st.dataframe(
            all_expenses_df,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="multi-row"
        )
        selected_rows = all_expenses_df.iloc[selection.selection.rows]
        if not selected_rows.empty:
            st.markdown("---")
            st.subheader(f"批次操作已選取的 {len(selected_rows)} 筆紀錄")
            confirm_batch_delete = st.checkbox("我了解並確認要刪除所有選取的費用紀錄")
            if st.button("🗑️ 刪除選取項目", type="primary", disabled=not confirm_batch_delete):
                ids_to_delete = selected_rows['id'].tolist()
                success, message = finance_model.batch_delete_annual_expenses(ids_to_delete)
                if success:
                    st.success(message)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(message)

        st.markdown("---")
        
        # === 批次編輯區塊 (改用 Checkbox) ===
        st.subheader("⚡ 批次編輯攤銷期間 (Data Editor)")
        
        # 使用 checkbox 取代 expander，確保篩選後不會自動縮回
        show_batch_editor = st.checkbox("👉 點此顯示/隱藏 編輯表格", value=False, key="toggle_batch_editor")
        
        if show_batch_editor:
            st.info("💡 提示：可直接在表格中修改「攤提月份」與「金額」，修改完畢請務必點擊下方的「儲存變更」按鈕。")
            
            # 1. 費用類型篩選器
            expense_types = ["全部"] + sorted(list(all_expenses_df['費用類型'].unique()))
            selected_type_filter = st.selectbox("篩選費用類型", expense_types, key="batch_edit_type_filter")
            
            # 2. 準備編輯資料
            if selected_type_filter != "全部":
                df_to_edit = all_expenses_df[all_expenses_df['費用類型'] == selected_type_filter].copy()
            else:
                df_to_edit = all_expenses_df.copy()
            
            # 3. 顯示 Data Editor
            edited_df = st.data_editor(
                df_to_edit,
                key=f"annual_expense_editor_{selected_dorm_id}",
                hide_index=True,
                column_config={
                    "id": st.column_config.NumberColumn("ID", disabled=True),
                    "費用類型": st.column_config.TextColumn(disabled=True),
                    "備註": st.column_config.TextColumn("系統摘要 (唯讀)", disabled=True),
                    "內部備註": st.column_config.TextColumn("內部備註 (可編輯)", help="可在此輸入自訂備註"),
                    
                    "費用項目": st.column_config.TextColumn("費用項目", required=True),
                    "支付日期": st.column_config.DateColumn("支付日期", format="YYYY-MM-DD", required=True),
                    "總金額": st.column_config.NumberColumn("總金額", format="$%d", required=True),
                    
                    "攤提起始月": st.column_config.TextColumn(
                        "攤提起始月", 
                        help="格式：YYYY-MM (例如 2025-01)",
                        required=True,
                        validate=r"^\d{4}-\d{2}$"
                    ),
                    "攤提結束月": st.column_config.TextColumn(
                        "攤提結束月", 
                        help="格式：YYYY-MM (例如 2025-12)",
                        required=True,
                        validate=r"^\d{4}-\d{2}$"
                    ),
                },
                column_order=[
                    "id", "費用類型", "費用項目", "支付日期", "總金額", 
                    "攤提起始月", "攤提結束月", "內部備註", "備註"
                ],
                disabled=["id", "費用類型", "備註"]
            )
            
            col_save, col_dummy = st.columns([1, 4])
            if col_save.button("💾 儲存變更", type="primary", key="btn_save_batch_expenses"):
                with st.spinner("正在儲存變更..."):
                    success, message = finance_model.batch_update_annual_expenses(edited_df)
                
                if success:
                    st.success(message)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(message)

    st.markdown("---")
    st.subheader("✏️ 編輯單筆費用紀錄")

    if all_expenses_df.empty:
        st.info("目前沒有可供編輯的費用紀錄。")
    else:
        options_dict = {
            row['id']: f"ID:{row['id']} - {row['支付日期']} {row['費用項目']} (金額: {row['總金額']})"
            for _, row in all_expenses_df.iterrows()
        }
        selected_expense_id = st.selectbox(
            "請從上方列表選擇一筆紀錄進行編輯：",
            options=[None] + list(options_dict.keys()),
            format_func=lambda x: "請選擇..." if x is None else options_dict.get(x)
        )

        if selected_expense_id:
            # --- 預先載入廠商資料 ---
            vendors_df = vendor_model.get_vendors_for_view()
            vendor_names = [""] + list(vendors_df['廠商名稱'].unique()) if not vendors_df.empty else [""]

            expense_details = finance_model.get_single_annual_expense_details(selected_expense_id)
            expense_type = all_expenses_df.loc[all_expenses_df['id'] == selected_expense_id, '費用類型'].iloc[0]

            if not expense_details:
                st.error("找不到選定的費用資料，可能已被刪除。")
                return

            if expense_type == '一般費用':
                with st.form(f"edit_general_expense_{selected_expense_id}"):
                    st.markdown(f"###### 正在編輯 ID: {expense_details['id']} ({expense_type})")
                    edit_expense_item = st.text_input("費用項目", value=expense_details.get('expense_item', ''))
                    e_c1, e_c2 = st.columns(2)
                    edit_payment_date = e_c1.date_input("實際支付日期", value=expense_details.get('payment_date'))
                    edit_total_amount = e_c2.number_input("支付總金額", min_value=0, step=1000, value=expense_details.get('total_amount', 0))
                    st.markdown("###### 攤提期間")
                    e_sc1, e_sc2 = st.columns(2)
                    edit_amort_start = e_sc1.text_input("攤提起始月 (YYYY-MM)", value=expense_details.get('amortization_start_month', ''))
                    edit_amort_end = e_sc2.text_input("攤提結束月 (YYYY-MM)", value=expense_details.get('amortization_end_month', ''))
                    edit_notes = st.text_area("備註", value=expense_details.get('notes', ''))

                    if st.form_submit_button("儲存一般費用變更"):
                        update_data = {
                            "expense_item": edit_expense_item, "notes": edit_notes,
                            "payment_date": edit_payment_date, "total_amount": edit_total_amount,
                            "amortization_start_month": edit_amort_start, "amortization_end_month": edit_amort_end,
                        }
                        success, message = finance_model.update_annual_expense_record(selected_expense_id, update_data)
                        if success: st.success(message); st.cache_data.clear(); st.rerun()
                        else: st.error(message)
            else:
                compliance_id = expense_details.get('compliance_record_id')
                if not compliance_id:
                    st.error("資料錯誤：找不到與此費用關聯的詳細紀錄。")
                    return
                
                compliance_details = finance_model.get_single_compliance_details(compliance_id)
                if not compliance_details:
                    st.error("資料錯誤：讀取關聯的詳細紀錄時失敗。")
                    return

                with st.form(f"edit_compliance_expense_{selected_expense_id}"):
                    st.markdown(f"###### 正在編輯 ID: {expense_details['id']} ({expense_type})")
                    
                    st.markdown("##### 財務資訊")
                    fin_c1, fin_c2 = st.columns(2)
                    e_payment_date = fin_c1.date_input("實際支付日期", value=expense_details.get('payment_date'))
                    e_total_amount = fin_c2.number_input("支付總金額", min_value=0, value=expense_details.get('total_amount', 0))
                    
                    st.markdown("##### 攤提期間")
                    am_c1, am_c2 = st.columns(2)
                    e_amort_start = am_c1.text_input("攤提起始月 (YYYY-MM)", value=expense_details.get('amortization_start_month', ''))
                    e_amort_end = am_c2.text_input("攤提結束月 (YYYY-MM)", value=expense_details.get('amortization_end_month', ''))
                    
                    st.markdown("---")
                    st.markdown("##### 詳細資料")

                    if expense_type == '建物申報':
                        col1, col2 = st.columns(2)
                        with col1:
                            # --- 將建築師改為下拉選單 ---
                            current_architect = compliance_details.get('architect_name', '')
                            architect_index = vendor_names.index(current_architect) if current_architect in vendor_names else 0
                            e_architect_name = st.selectbox("建築師", options=vendor_names, index=architect_index)
                            
                            e_declaration_item = st.text_input("申報項目", value=compliance_details.get('declaration_item', ''))
                            e_area_legal = st.text_input("申報面積(合法)", value=compliance_details.get('area_legal', ''))
                            e_area_total = st.text_input("申報面積(合法+違規)", value=compliance_details.get('area_total', ''))
                            e_submission_date = st.date_input("申報文件送出日期", value=compliance_details.get('submission_date'))
                        with col2:
                            e_gov_doc = st.checkbox("政府是否發文", value=compliance_details.get('gov_document_exists', False))
                            e_improvements = st.checkbox("現場是否改善", value=compliance_details.get('improvements_made', False))
                            e_next_start = st.date_input("下次申報起始日期", value=compliance_details.get('next_declaration_start'))
                            e_next_end = st.date_input("下次申報結束日期", value=compliance_details.get('next_declaration_end'))
                    
                    elif expense_type == '消防安檢':
                        fs_c1, fs_c2 = st.columns(2)
                        # --- 將廠商改為下拉選單 ---
                        current_vendor = compliance_details.get('vendor', '')
                        vendor_index = vendor_names.index(current_vendor) if current_vendor in vendor_names else 0
                        e_fs_vendor = fs_c1.selectbox("支出對象/廠商", options=vendor_names, index=vendor_index)

                        e_fs_item = fs_c2.text_input("申報項目", value=compliance_details.get('declaration_item', ''))
                        st.date_input("收到憑證日期", value=compliance_details.get('certificate_date'), key="certificate_date_widget")
                        e_fs_next_start = st.date_input("下次申報起始日期", value=compliance_details.get('next_declaration_start'))

                    elif expense_type == '保險':
                        ins_c1, ins_c2 = st.columns(2)
                        # --- 將保險公司改為下拉選單 ---
                        current_insurer = compliance_details.get('vendor', '')
                        insurer_index = vendor_names.index(current_insurer) if current_insurer in vendor_names else 0
                        e_ins_vendor = ins_c1.selectbox("保險公司", options=vendor_names, index=insurer_index)
                        
                        e_ins_start = ins_c2.date_input("保險起始日", value=compliance_details.get('insurance_start_date'))
                        e_ins_end = ins_c2.date_input("保險截止日", value=compliance_details.get('insurance_end_date'))
                    
                    if st.form_submit_button("儲存變更"):
                        updated_expense_data = {
                            "payment_date": e_payment_date, "total_amount": e_total_amount,
                            "amortization_start_month": e_amort_start, "amortization_end_month": e_amort_end,
                        }
                        
                        updated_compliance_data = {}
                        if expense_type == '建物申報':
                            updated_compliance_data = {
                                "architect_name": e_architect_name, "declaration_item": e_declaration_item,
                                "area_legal": e_area_legal, "area_total": e_area_total,
                                "submission_date": e_submission_date, "gov_document_exists": e_gov_doc,
                                "improvements_made": e_improvements, "next_declaration_start": e_next_start,
                                "next_declaration_end": e_next_end
                            }
                        elif expense_type == '消防安檢':
                            updated_compliance_data = {
                                "vendor": e_fs_vendor, "declaration_item": e_fs_item,
                                "certificate_date": st.session_state.get('certificate_date_widget'),
                                "next_declaration_start": e_fs_next_start
                            }
                        elif expense_type == '保險':
                             updated_compliance_data = {
                                "vendor": e_ins_vendor, 
                                "insurance_start_date": e_ins_start,
                                "insurance_end_date": e_ins_end
                            }
                        
                        success, message = finance_model.update_compliance_expense_record(
                            selected_expense_id, updated_expense_data, 
                            compliance_id, updated_compliance_data,
                            expense_type
                        )
                        if success: st.success(message); st.cache_data.clear(); st.rerun()
                        else: st.error(message)

    st.markdown("---")
    
    st.subheader("新增費用紀錄")
    tab1, tab2, tab3 = st.tabs(["📋 一般費用", "🏗️ 建物申報", "🔥 消防與保險"])

    with tab1:
        with st.form("new_annual_expense_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            expense_item_options = ["維修", "傢俱", "其他(請手動輸入)"]
            selected_expense_item = c1.selectbox("費用項目", expense_item_options, key="general_item")
            custom_expense_item = c1.text_input("自訂費用項目", help="若上方選擇「其他」，請在此處填寫", key="general_custom_item")
            payment_date_general = c2.date_input("實際支付日期", value=datetime.now(), key="general_payment_date")
            total_amount_general = c3.number_input("支付總金額", min_value=0, step=1000, key="general_amount")
            st.markdown("##### 攤提期間")
            sc1, sc2, sc3 = st.columns(3)
            amort_start_general = sc1.date_input("攤提起始日", value=payment_date_general, key="general_amort_start")
            amort_period_general = sc2.number_input("攤提月數", min_value=1, step=1, value=12, key="general_amort_period")
            end_date_obj_general = amort_start_general + relativedelta(months=amort_period_general - 1) if amort_start_general and amort_period_general else None
            amort_end_month_general = end_date_obj_general.strftime('%Y-%m') if end_date_obj_general else ""
            sc3.text_input("攤提結束月份 (自動計算)", value=amort_end_month_general, disabled=True, key="general_amort_end")
            notes_general = st.text_area("備註", key="general_notes")
            submitted_general = st.form_submit_button("儲存一般費用紀錄")
            if submitted_general:
                final_expense_item = custom_expense_item if selected_expense_item == "其他(請手動輸入)" and custom_expense_item else selected_expense_item
                if not final_expense_item or pd.isna(total_amount_general):
                    st.error("「費用項目」和「總金額」為必填欄位！")
                else:
                    details = {
                        "dorm_id": selected_dorm_id, "expense_item": final_expense_item,
                        "payment_date": str(payment_date_general), "total_amount": total_amount_general,
                        "amortization_start_month": amort_start_general.strftime('%Y-%m'),
                        "amortization_end_month": amort_end_month_general, "notes": notes_general
                    }
                    success, message, _ = finance_model.add_annual_expense_record(details)
                    if success: st.success(message); st.cache_data.clear(); st.rerun()
                    else: st.error(message)
    with tab2:
        with st.form("new_permit_form", clear_on_submit=True):
            st.markdown("##### 財務資訊")
            fin_c1, fin_c2, fin_c3, fin_c4 = st.columns(4)
            payment_date = fin_c1.date_input("實際支付日期", value=datetime.now(), key="permit_payment_date")
            amount_pre_tax = fin_c2.number_input("金額(未稅)", min_value=0, key="permit_pre_tax")
            total_amount = fin_c3.number_input("總金額(含稅)", min_value=0, key="permit_total")
            invoice_date = fin_c4.date_input("請款日", value=None, key="permit_invoice_date")
            st.markdown("##### 攤提期間")
            am_c1, am_c2, am_c3 = st.columns(3)
            amortization_start_date = am_c1.date_input("攤提起始日", value=payment_date, key="permit_amort_start")
            amortization_period = am_c2.number_input("攤提月數", min_value=1, step=1, value=12, key="permit_amort_period")
            end_date_obj = amortization_start_date + relativedelta(months=amortization_period - 1) if amortization_start_date and amortization_period else None
            amortization_end_month = end_date_obj.strftime('%Y-%m') if end_date_obj else ""
            am_c3.text_input("攤提結束月份 (自動計算)", value=amortization_end_month, disabled=True, key="permit_amort_end")
            st.markdown("---")
            st.markdown("##### 申報詳細資料")
            col1, col2 = st.columns(2)
            with col1:
                architect_name = st.text_input("建築師 (支出對象/廠商)")
                declaration_item = st.text_input("申報項目")
                area_legal = st.text_input("申報面積(合法)")
                area_total = st.text_input("申報面積(合法+違規)")
                submission_date = st.date_input("申報文件送出日期", value=None)
                registered_mail_date = st.date_input("掛號憑證日期", value=None)
                certificate_received_date = st.date_input("收到憑證日期", value=None)
            with col2:
                gov_document_exists = st.checkbox("政府是否發文")
                usage_license_exists = st.checkbox("使用執照有無")
                property_deed_exists = st.checkbox("權狀有無")
                landlord_id_exists = st.checkbox("房東證件有無")
                improvements_made = st.checkbox("現場是否改善")
                insurance_exists = st.checkbox("保險有無")
            st.markdown("##### 下次申報期間")
            next_c1, next_c2 = st.columns(2)
            next_declaration_start = next_c1.date_input("下次申報起始日期", value=None)
            next_declaration_end = next_c2.date_input("下次申報結束日期", value=None)
            st.markdown("##### 本次核准期間")
            app_c1, app_c2 = st.columns(2)
            approval_start_date = app_c1.date_input("此次申報核准起始日期", value=None)
            approval_end_date = app_c2.date_input("此次申報核准結束日期", value=None)
            submitted = st.form_submit_button("儲存建物申報紀錄")
            if submitted:
                permit_details = {
                    "dorm_id": selected_dorm_id,
                    "details": {
                        "architect_name": architect_name, "gov_document_exists": gov_document_exists,
                        "next_declaration_start": str(next_declaration_start) if next_declaration_start else None,
                        "next_declaration_end": str(next_declaration_end) if next_declaration_end else None,
                        "declaration_item": declaration_item, "area_legal": area_legal, "area_total": area_total,
                        "amount_pre_tax": amount_pre_tax, "usage_license_exists": usage_license_exists,
                        "property_deed_exists": property_deed_exists, "landlord_id_exists": landlord_id_exists,
                        "improvements_made": improvements_made, "insurance_exists": insurance_exists,
                        "submission_date": str(submission_date) if submission_date else None,
                        "registered_mail_date": str(registered_mail_date) if registered_mail_date else None,
                        "certificate_received_date": str(certificate_received_date) if certificate_received_date else None,
                        "invoice_date": str(invoice_date) if invoice_date else None,
                        "approval_start_date": str(approval_start_date) if approval_start_date else None,
                        "approval_end_date": str(approval_end_date) if approval_end_date else None
                    }
                }
                expense_details = {
                    "dorm_id": selected_dorm_id,
                    "expense_item": f"建物申報-{declaration_item}" if declaration_item else "建物申報",
                    "payment_date": str(payment_date), "total_amount": total_amount,
                    "amortization_start_month": amortization_start_date.strftime('%Y-%m'),
                    "amortization_end_month": amortization_end_month
                }
                success, message, _ = finance_model.add_building_permit_record(permit_details, expense_details)
                if success: st.success(message); st.cache_data.clear(); st.rerun()
                else: st.error(message)

    with tab3:
        st.subheader("新增消防安檢紀錄")
        with st.form("new_fire_safety_form", clear_on_submit=True):
            st.markdown("##### 財務資訊")
            fsc1, fsc2, fsc3 = st.columns(3)
            fs_payment_date = fsc1.date_input("支付日期", value=datetime.now(), key="fs_payment")
            fs_amount = fsc2.number_input("支付總金額", min_value=0, key="fs_amount")
            
            st.markdown("##### 攤提期間")
            fs_am_c1, fs_am_c2, fs_am_c3 = st.columns(3)
            fs_amort_start = fs_am_c1.date_input("攤提起始日", value=fs_payment_date, key="fs_amort_start")
            fs_amort_period = fs_am_c2.number_input("攤提月數", min_value=1, step=1, value=12, key="fs_amort_period")
            fs_end_date_obj = fs_amort_start + relativedelta(months=fs_amort_period - 1) if fs_amort_start and fs_amort_period else None
            fs_amort_end_month = fs_end_date_obj.strftime('%Y-%m') if fs_end_date_obj else ""
            fs_am_c3.text_input("攤提結束月份 (自動計算)", value=fs_amort_end_month, disabled=True, key="fs_amort_end")

            st.markdown("##### 申報詳細資料")
            fs_vendor = st.text_input("支出對象/廠商", key="fs_vendor")
            fs_declaration_item = st.text_input("申報項目", key="fs_item", value="消防安檢")
            fsc4, fsc5, fsc6 = st.columns(3)
            fs_submission_date = fsc4.date_input("申報文件送出日期", value=None, key="fs_submission_date")
            fs_registered_mail_date = fsc5.date_input("掛號憑證日期", value=None, key="fs_registered_mail_date")
            fs_certificate_date = fsc6.date_input("收到憑證日期", value=None, key="fs_certificate_date")

            st.markdown("##### 下次申報期間")
            fs_next_c1, fs_next_c2 = st.columns(2)
            fs_next_start = fs_next_c1.date_input("下次申報起始日期", value=None, key="fs_next_start")
            fs_next_end = fs_next_c2.date_input("下次申報結束日期", value=None, key="fs_next_end")
            
            st.markdown("##### 本次核准期間")
            fs_app_c1, fs_app_c2 = st.columns(2)
            fs_approval_start = fs_app_c1.date_input("此次申報核准起始日期", value=None, key="fs_approval_start")
            fs_approval_end = fs_app_c2.date_input("此次申報核准結束日期", value=None, key="fs_approval_end")
            
            fs_submitted = st.form_submit_button("儲存消防安檢紀錄")
            if fs_submitted:
                record_details = {"dorm_id": selected_dorm_id, "details": {
                    "vendor": fs_vendor, "declaration_item": fs_declaration_item,
                    "submission_date": fs_submission_date, "registered_mail_date": fs_registered_mail_date,
                    "certificate_date": fs_certificate_date, "next_declaration_start": fs_next_start,
                    "next_declaration_end": fs_next_end, "approval_start_date": fs_approval_start,
                    "approval_end_date": fs_approval_end,
                }}
                expense_details = {
                    "dorm_id": selected_dorm_id, "expense_item": fs_declaration_item,
                    "payment_date": fs_payment_date, "total_amount": fs_amount,
                    "amortization_start_month": fs_amort_start.strftime('%Y-%m'),
                    "amortization_end_month": fs_amort_end_month
                }
                success, message, _ = finance_model.add_compliance_record('消防安檢', record_details, expense_details)
                if success: st.success(message); st.cache_data.clear(); st.rerun()
                else: st.error(message)
        
        st.markdown("---")
        
        st.subheader("新增保險紀錄")
        with st.form("new_insurance_form", clear_on_submit=True):
            insc1, insc2, insc3 = st.columns(3)
            ins_payment_date = insc1.date_input("支付日期", value=datetime.now(), key="ins_payment")
            ins_amount = insc2.number_input("支付總金額 (保費)", min_value=0, key="ins_amount")
            ins_certificate_date = insc3.date_input("憑證日期", value=None, key="ins_cert_date")
            insc4, insc5, insc6 = st.columns(3)
            ins_vendor = insc4.text_input("保險公司", key="ins_vendor")
            ins_start_date = insc5.date_input("保險起始日", value=None, key="ins_start")
            ins_end_date = insc6.date_input("保險截止日", value=None, key="ins_end")
            ins_submitted = st.form_submit_button("儲存保險紀錄")
            if ins_submitted:
                record_details = {"dorm_id": selected_dorm_id, "details": {
                    "vendor": ins_vendor,
                    "certificate_date": ins_certificate_date,
                    "insurance_start_date": ins_start_date,
                    "insurance_end_date": ins_end_date,
                }}
                expense_details = {
                    "dorm_id": selected_dorm_id, "expense_item": "保險費",
                    "payment_date": ins_payment_date, "total_amount": ins_amount,
                    "amortization_start_month": ins_start_date.strftime('%Y-%m') if ins_start_date else ins_payment_date.strftime('%Y-%m'),
                    "amortization_end_month": (ins_end_date - relativedelta(months=1)).strftime('%Y-%m') if ins_end_date else (ins_payment_date + relativedelta(years=1, months=-1)).strftime('%Y-%m')
                }
                success, message, _ = finance_model.add_compliance_record('保險', record_details, expense_details)
                if success: st.success(message); st.cache_data.clear(); st.rerun()
                else: st.error(message)

def render_by_item_view():
    """
    新功能：以項目為中心，並支援 JSON/JSONB 欄位展開與中文對照
    """
    st.subheader("📋 跨宿舍項目檢視與編輯")
    
    # === 1. 定義欄位中英對照表 (您可以隨時在此擴充) ===
    field_mapping = {
        # 建物/消防申報相關
        "declaration_item": "申報項目",
        "architect_name": "檢查人/代辦",
        "area_legal": "合法面積(㎡)",
        "area_total": "總面積(㎡)",
        "amount_pre_tax": "未稅金額",
        "submission_date": "申報日期",
        "registered_mail_date": "掛號日期",
        "certificate_received_date": "合格標章取得日",
        "approval_start_date": "核准有效起日",
        "approval_end_date": "核准有效迄日",
        "next_declaration_start": "下次申報起日",
        "next_declaration_end": "下次申報迄日",
        "invoice_date": "發票日期",
        
        # 證件/文件勾選 (Boolean)
        "usage_license_exists": "有使用執照?",
        "property_deed_exists": "有建物權狀?",
        "landlord_id_exists": "有房東身分證?",
        "insurance_exists": "有公共意外險?",
        "gov_document_exists": "有市府公文?",
        "improvements_made": "改善事項已完成?",
        
        # 其他通用
        "notes": "備註",
        "vendor": "廠商",
        "contact_person": "聯絡人"
    }

    # 2. 篩選區
    col1, col2 = st.columns([1, 2])
    with col1:
        all_items = finance_model.get_unique_expense_items()
        selected_item = st.selectbox("請選擇費用項目", ["(全部)"] + all_items)
    
    # 3. 抓取資料
    filters = {}
    if selected_item != "(全部)":
        filters['expense_item'] = selected_item
    
    raw_df = finance_model.get_all_annual_expenses(filters)
    
    if raw_df.empty:
        st.warning("查無相關資料。")
        return

    # === 4. JSON 展開邏輯 ===
    json_columns = []
    expanded_data = []
    
    # 預設固定欄位
    fixed_cols = ["id", "宿舍地址", "費用項目", "總金額", "支付日期", "攤提起", "攤提迄", "dorm_id"]
    
    for idx, row in raw_df.iterrows():
        note_content = row.get('備註')
        row_json_data = {}
        
        # 情況 A: 資料庫欄位是 JSONB，讀出來已經是 dict
        if isinstance(note_content, dict):
            row_json_data = note_content
            
        # 情況 B: 資料庫欄位是 Text，但內容是 JSON 字串
        elif isinstance(note_content, str):
            try:
                clean_content = note_content.strip()
                if clean_content.startswith('{'):
                    parsed = json.loads(clean_content)
                    if isinstance(parsed, dict):
                        row_json_data = parsed
            except Exception:
                pass 

        expanded_data.append(row_json_data)
    
    # 建立 JSON 資料的 DataFrame
    json_df = pd.DataFrame(expanded_data)
    
    # 合併資料
    if not json_df.empty and len(json_df.columns) > 0:
        json_columns = list(json_df.columns)
        # 簡單排序：讓布林值(exists/made)排在後面，日期排前面
        json_columns.sort(key=lambda x: (1 if 'exists' in x or 'made' in x else 0, x))
        
        st.info(f"💡 偵測到結構化資料，已展開 {len(json_columns)} 個詳細欄位。")
        display_df = pd.concat([raw_df.reset_index(drop=True), json_df.reset_index(drop=True)], axis=1)
    else:
        display_df = raw_df.copy()
        fixed_cols.append("備註") 

    # === 5. 設定編輯器欄位格式 (套用中文標題) ===
    column_config = {
        "id": st.column_config.NumberColumn("ID", disabled=True, width="small"),
        "宿舍地址": st.column_config.TextColumn("宿舍", disabled=True, width="medium"),
        "費用項目": st.column_config.TextColumn("項目", required=True),
        "總金額": st.column_config.NumberColumn("總金額", min_value=0, format="$%d"),
        "支付日期": st.column_config.DateColumn("支付日期", format="YYYY-MM-DD"),
        "攤提起": st.column_config.TextColumn("攤提起", help="格式: YYYY-MM"),
        "攤提迄": st.column_config.TextColumn("攤提迄", help="格式: YYYY-MM"),
        "dorm_id": None, 
        "備註": None if json_columns else st.column_config.TextColumn("備註") 
    }

    # 為 JSON 展開的欄位設定格式與中文標題
    for col in json_columns:
        # 取得中文名稱 (若無對照則顯示原英文)
        chinese_label = field_mapping.get(col, col)
        
        col_lower = col.lower()
        if 'exists' in col_lower or 'made' in col_lower or 'is_' in col_lower:
             column_config[col] = st.column_config.CheckboxColumn(label=chinese_label)
        
        elif 'date' in col_lower:
             column_config[col] = st.column_config.TextColumn(label=chinese_label, help="格式: YYYY-MM-DD") 
        
        elif 'amount' in col_lower or 'area' in col_lower:
             column_config[col] = st.column_config.NumberColumn(label=chinese_label)
        
        else:
             column_config[col] = st.column_config.TextColumn(label=chinese_label)

    # 6. 顯示 Data Editor
    edited_df = st.data_editor(
        display_df,
        column_config=column_config,
        hide_index=True,
        use_container_width=True,
        num_rows="dynamic",
        key="annual_expense_json_editor"
    )

    # 7. 儲存邏輯 (維持不變)
    if st.button("💾 儲存表格變更", type="primary"):
        updates = []
        original_df_idx = raw_df.set_index("id")
        
        for index, row in edited_df.iterrows():
            row_id = row.get('id')
            if not row_id or row_id not in original_df_idx.index: continue
                
            orig_row = original_df_idx.loc[row_id]
            changes = {}
            
            # 固定欄位
            if row['費用項目'] != orig_row['費用項目']: changes['expense_item'] = row['費用項目']
            if row['總金額'] != orig_row['總金額']: changes['total_amount'] = row['總金額']
            
            new_pay_date = pd.to_datetime(row['支付日期']).date() if pd.notnull(row['支付日期']) else None
            orig_pay_date = pd.to_datetime(orig_row['支付日期']).date() if pd.notnull(orig_row['支付日期']) else None
            if new_pay_date != orig_pay_date: changes['payment_date'] = new_pay_date

            if row['攤提起'] != orig_row['攤提起']: changes['amortization_start_month'] = row['攤提起']
            if row['攤提迄'] != orig_row['攤提迄']: changes['amortization_end_month'] = row['攤提迄']

            # JSON 欄位打包
            if json_columns:
                current_json_data = {}
                for col in json_columns:
                    val = row.get(col)
                    if pd.isna(val): val = None
                    elif hasattr(val, 'item'): val = val.item()
                    if val is not None: current_json_data[col] = val
                
                new_note_str = json.dumps(current_json_data, ensure_ascii=False)
                
                orig_note_obj = {}
                orig_raw = orig_row.get('備註')
                if isinstance(orig_raw, dict): orig_note_obj = orig_raw
                elif isinstance(orig_raw, str):
                    try: orig_note_obj = json.loads(orig_raw)
                    except: pass
                
                if current_json_data != orig_note_obj:
                    changes['notes'] = new_note_str
            else:
                if row.get('備註') != orig_row.get('備註'):
                    changes['notes'] = row.get('備註')

            if changes:
                changes['id'] = int(row_id)
                updates.append(changes)
        
        if updates:
            success, msg = finance_model.batch_update_annual_expenses(updates)
            if success:
                st.success(f"✅ {msg}")
                st.cache_data.clear()
                st.rerun()
            else:
                st.error(f"❌ {msg}")
        else:
            st.info("沒有偵測到任何變更。")