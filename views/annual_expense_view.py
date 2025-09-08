import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from data_models import finance_model, dormitory_model

def render():
    """渲染「年度費用管理」頁面"""
    st.header("我司管理宿舍 - 長期攤銷費用管理")
    
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
            use_container_width=True,
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
            expense_details = finance_model.get_single_annual_expense_details(selected_expense_id)
            expense_type = all_expenses_df.loc[all_expenses_df['id'] == selected_expense_id, '費用類型'].iloc[0]

            if not expense_details:
                st.error("找不到選定的費用資料，可能已被刪除。")
            else:
                with st.form(f"edit_annual_expense_{selected_expense_id}"):
                    st.markdown(f"###### 正在編輯 ID: {expense_details['id']} ({expense_type})")
                    is_general_expense = (expense_type == '一般費用')

                    edit_expense_item = st.text_input(
                        "費用項目",
                        value=expense_details.get('expense_item', ''),
                        disabled=not is_general_expense,
                        help="關聯到建物申報或保險的費用項目為自動產生，無法直接修改。"
                    )
                    e_c1, e_c2 = st.columns(2)
                    edit_payment_date = e_c1.date_input("實際支付日期", value=expense_details.get('payment_date'))
                    edit_total_amount = e_c2.number_input("支付總金額", min_value=0, step=1000, value=expense_details.get('total_amount', 0))

                    st.markdown("###### 攤提期間")
                    e_sc1, e_sc2 = st.columns(2)
                    edit_amort_start = e_sc1.text_input("攤提起始月 (YYYY-MM)", value=expense_details.get('amortization_start_month', ''))
                    edit_amort_end = e_sc2.text_input("攤提結束月 (YYYY-MM)", value=expense_details.get('amortization_end_month', ''))

                    edit_notes = st.text_area(
                        "備註",
                        value=expense_details.get('notes', ''),
                        disabled=not is_general_expense,
                        help="關聯到建物申報或保險的備註為自動產生，無法直接修改。"
                    )

                    submitted = st.form_submit_button("儲存變更")
                    if submitted:
                        update_data = {
                            "payment_date": edit_payment_date,
                            "total_amount": edit_total_amount,
                            "amortization_start_month": edit_amort_start,
                            "amortization_end_month": edit_amort_end,
                        }
                        if is_general_expense:
                            update_data["expense_item"] = edit_expense_item
                            update_data["notes"] = edit_notes

                        success, message = finance_model.update_annual_expense_record(selected_expense_id, update_data)
                        if success:
                            st.success(message)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(message)

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
            
            # --- 【核心修改】將財務與攤銷欄位都加入 ---
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
        # ... (保險紀錄表單維持不變) ...
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