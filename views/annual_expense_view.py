import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from data_models import finance_model, dormitory_model

def render():
    """渲染「年度費用管理」頁面"""
    st.header("我司管理宿舍 - 長期攤銷費用管理")
    
    # --- 1. 宿舍選擇 ---
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
    
    # --- 歷史費用總覽 ---
    st.subheader(f"歷史費用總覽: {dorm_options.get(selected_dorm_id)}")

    if st.button("🔄 重新整理費用列表"):
        st.cache_data.clear()

    @st.cache_data
    def get_all_annual_expenses(dorm_id):
        return finance_model.get_all_annual_expenses_for_dorm(dorm_id)

    all_expenses_df = get_all_annual_expenses(selected_dorm_id)

    if all_expenses_df.empty:
        st.info("此宿舍尚無任何長期費用紀錄。")
    else:
        st.dataframe(all_expenses_df, use_container_width=True, hide_index=True)
        
        # 統一的刪除功能
        st.markdown("---")
        st.subheader("刪除單筆紀錄")
        record_to_delete_options = {
            row['id']: f"ID:{row['id']} - {row['費用類型']} - {row['費用項目']} ({row['支付日期']})" 
            for _, row in all_expenses_df.iterrows()
        }
        record_id_to_delete = st.selectbox(
            "選擇要刪除的費用紀錄：",
            options=[None] + list(record_to_delete_options.keys()),
            format_func=lambda x: "請選擇..." if x is None else record_to_delete_options.get(x)
        )

        if record_id_to_delete:
            selected_record = all_expenses_df[all_expenses_df['id'] == record_id_to_delete].iloc[0]
            selected_record_type = selected_record['費用類型']
            
            if selected_record_type != '一般費用':
                st.warning(f"注意：刪除「{selected_record_type}」類型的紀錄是一個複雜操作，目前尚未開放。請聯絡系統管理員。")
            else:
                if st.button("🗑️ 刪除選定的一般費用紀錄", type="primary"):
                    success, message = finance_model.delete_annual_expense_record(record_id_to_delete)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

    st.markdown("---")
    
    # --- 新增費用紀錄 ---
    st.subheader("新增費用紀錄")
    # 【核心修改】對調頁籤順序
    tab1, tab2 = st.tabs(["📋 新增一般年度費用", "🏗️ 新增建物申報"])

    # --- 頁籤一：一般年度費用 ---
    with tab1:
        with st.form("new_annual_expense_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            expense_item_options = ["消防安檢", "維修", "傢俱", "其他(請手動輸入)"]
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
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

    # --- 頁籤二：建物申報管理 ---
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
                        "architect_name": architect_name,
                        "gov_document_exists": gov_document_exists,
                        "next_declaration_start": str(next_declaration_start) if next_declaration_start else None,
                        "next_declaration_end": str(next_declaration_end) if next_declaration_end else None,
                        "declaration_item": declaration_item,
                        "area_legal": area_legal,
                        "area_total": area_total,
                        "amount_pre_tax": amount_pre_tax,
                        "usage_license_exists": usage_license_exists,
                        "property_deed_exists": property_deed_exists,
                        "landlord_id_exists": landlord_id_exists,
                        "improvements_made": improvements_made,
                        "insurance_exists": insurance_exists,
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
                    "payment_date": str(payment_date),
                    "total_amount": total_amount,
                    "amortization_start_month": amortization_start_date.strftime('%Y-%m'),
                    "amortization_end_month": amortization_end_month
                }
                success, message, _ = finance_model.add_building_permit_record(permit_details, expense_details)
                if success:
                    st.success(message)
                    st.cache_data.clear()
                    st.rerun()
                else:
                    st.error(message)