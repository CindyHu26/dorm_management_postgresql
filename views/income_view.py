import streamlit as st
import pandas as pd
from datetime import datetime
from data_models import income_model, dormitory_model

def render():
    st.header("我司管理宿舍 - 其他收入管理")
    st.info("用於登錄房租以外的收入，例如冷氣卡儲值、押金沒收、雜項收入等。")

    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前沒有「我司管理」的宿舍可供操作。")
        return

    dorm_options = {d['id']: d['original_address'] for d in my_dorms}
    selected_dorm_id = st.selectbox("請選擇宿舍：", options=list(dorm_options.keys()), format_func=lambda x: dorm_options.get(x))

    if not selected_dorm_id: return
    st.markdown("---")

    with st.expander("📝 新增一筆收入紀錄"):
        with st.form("new_income_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            
            income_options = ["冷氣卡儲值", "投幣式洗衣機", "販賣機", "其他 (請手動輸入)"]
            selected_income_item = c1.selectbox("收入項目", income_options)
            custom_income_item = c1.text_input("自訂收入項目", help="若上方選擇「其他」，請在此處填寫")

            amount = c2.number_input("收入金額", min_value=0)
            transaction_date = c3.date_input("收入日期", value=datetime.now())
            notes = st.text_area("備註")
            
            submitted = st.form_submit_button("儲存收入紀錄")
            if submitted:
                final_income_item = custom_income_item if selected_income_item == "其他 (請手動輸入)" and custom_income_item else selected_income_item
                
                if not final_income_item or final_income_item == "其他 (請手動輸入)":
                    st.error("「收入項目」為必填欄位！若選擇「其他」，請務必填寫自訂項目。")
                else:
                    details = {
                        "dorm_id": selected_dorm_id, "income_item": final_income_item,
                        "transaction_date": str(transaction_date), "amount": amount, "notes": notes
                    }
                    success, message, _ = income_model.add_income_record(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

    st.markdown("---")
    st.subheader("歷史收入紀錄")

    if st.button("🔄 重新整理列表"):
        st.cache_data.clear()
        
    @st.cache_data
    def get_income_df(dorm_id):
        return income_model.get_income_for_dorm_as_df(dorm_id)
        
    income_df = get_income_df(selected_dorm_id)
    
    if income_df.empty:
        st.info("此宿舍尚無任何其他收入紀錄。")
    else:
        st.dataframe(income_df, width="stretch", hide_index=True)

        st.markdown("---")
        # --- 【核心修改點】整合編輯與刪除區塊 ---
        st.subheader("編輯或刪除單筆紀錄")
        
        options_dict = {
            row['id']: f"ID:{row['id']} - {row['收入日期']} {row['收入項目']} 金額:{row['金額']}" 
            for _, row in income_df.iterrows()
        }
        
        selected_income_id = st.selectbox(
            "請從上方列表選擇一筆紀錄進行操作：",
            options=[None] + list(options_dict.keys()),
            format_func=lambda x: "請選擇..." if x is None else options_dict.get(x)
        )

        if selected_income_id:
            income_details = income_model.get_single_income_details(selected_income_id)
            if not income_details:
                st.error("找不到選定的收入資料，可能已被刪除。")
            else:
                # 編輯表單
                with st.form(f"edit_income_form_{selected_income_id}"):
                    st.markdown(f"###### 正在編輯 ID: {selected_income_id} 的紀錄")
                    ec1, ec2, ec3 = st.columns(3)
                    
                    e_income_item = ec1.text_input("收入項目", value=income_details.get('income_item', ''))
                    e_amount = ec2.number_input("收入金額", min_value=0, value=income_details.get('amount', 0))
                    e_transaction_date = ec3.date_input("收入日期", value=income_details.get('transaction_date'))
                    e_notes = st.text_area("備註", value=income_details.get('notes', ''))

                    edit_submitted = st.form_submit_button("儲存變更")
                    if edit_submitted:
                        updated_details = {
                            "income_item": e_income_item,
                            "amount": e_amount,
                            "transaction_date": str(e_transaction_date),
                            "notes": e_notes
                        }
                        success, message = income_model.update_income_record(selected_income_id, updated_details)
                        if success:
                            st.success(message)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(message)

                # 刪除區塊
                st.markdown("---")
                st.markdown("##### 危險操作區")
                confirm_delete = st.checkbox("我了解並確認要刪除此筆收入紀錄")
                if st.button("🗑️ 刪除此筆紀錄", type="primary", disabled=not confirm_delete):
                    success, message = income_model.delete_income_record(selected_income_id)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)