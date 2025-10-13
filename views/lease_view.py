# views/lease_view.py

import streamlit as st
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from data_models import lease_model, dormitory_model, vendor_model

def render():
    """渲染「長期合約管理」頁面"""
    st.header("長期合約管理")
    st.info("用於管理房租、清運費、網路費等具備固定月費的長期合約。")

    today = date.today()
    thirty_years_ago = today - relativedelta(years=30)
    thirty_years_from_now = today + relativedelta(years=30)

    with st.expander("➕ 新增長期合約"):
        with st.form("new_lease_form", clear_on_submit=True):
            dorms = dormitory_model.get_dorms_for_selection() or []
            dorm_options = {d['id']: d['original_address'] for d in dorms}
            
            # --- 預先載入廠商列表 ---
            vendors = vendor_model.get_vendors_for_view()
            vendor_options = {v['id']: f"{v['服務項目']} - {v['廠商名稱']}" for _, v in vendors.iterrows()} if not vendors.empty else {}
            
            selected_dorm_id = st.selectbox("選擇宿舍地址*", options=dorm_options.keys(), format_func=lambda x: dorm_options.get(x, "未知宿舍"))
            
            # --- 新增廠商選擇器和備註欄位 ---
            c1_item, c2_item, c3_item = st.columns(3) 
            item_options = ["房租", "清運費", "其他...(手動輸入)"]
            selected_item = c1_item.selectbox("合約項目*", options=item_options)
            custom_item = c1_item.text_input("自訂項目名稱", help="若上方選擇「其他...」，請在此處填寫")
            
            monthly_rent = c2_item.number_input("每月固定金額*", min_value=0, step=1000)

            # 將廠商選擇器放在第三欄
            selected_vendor_id = c3_item.selectbox("房東/廠商 (選填)", options=[None] + list(vendor_options.keys()), format_func=lambda x: "未指定" if x is None else vendor_options.get(x))

            c1, c2 = st.columns(2)
            lease_start_date = c1.date_input("合約起始日", value=None, min_value=thirty_years_ago, max_value=thirty_years_from_now)
            with c2:
                lease_end_date = st.date_input("合約截止日 (可留空)", value=None, min_value=thirty_years_ago, max_value=thirty_years_from_now)
                st.write("若為長期合約，此處請留空。")
            
            c3, c4 = st.columns([1, 3])
            deposit = c3.number_input("押金", min_value=0, step=1000)
            utilities_included = c4.checkbox("費用是否包含水電 (通常用於房租)")

            notes = st.text_area("合約備註")

            submitted = st.form_submit_button("儲存新合約")
            if submitted:
                final_item = custom_item if selected_item == "其他..." and custom_item else selected_item
                if not final_item:
                    st.error("「合約項目」為必填欄位！")
                else:
                    details = {
                        "dorm_id": selected_dorm_id,
                        "vendor_id": selected_vendor_id,
                        "contract_item": final_item,
                        "lease_start_date": str(lease_start_date) if lease_start_date else None,
                        "lease_end_date": str(lease_end_date) if lease_end_date else None,
                        "monthly_rent": monthly_rent,
                        "deposit": deposit,
                        "utilities_included": utilities_included,
                        "notes": notes
                    }
                    success, message, _ = lease_model.add_lease(details)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)

    st.markdown("---")

    st.subheader("現有合約總覽")
    
    dorms_for_filter = dormitory_model.get_dorms_for_selection() or []
    dorm_filter_options = {0: "所有宿舍"} | {d['id']: d['original_address'] for d in dorms_for_filter}
    dorm_id_filter = st.selectbox("篩選宿舍", options=list(dorm_filter_options.keys()), format_func=lambda x: dorm_filter_options.get(x))

    @st.cache_data
    def get_leases(filter_id):
        return lease_model.get_leases_for_view(filter_id if filter_id else None)

    leases_df = get_leases(dorm_id_filter)
    
    # --- 顯示的欄位名稱 ---
    st.dataframe(leases_df, width="stretch", hide_index=True, column_config={
        "月費金額": st.column_config.NumberColumn(format="NT$ %d")
    })
    
    st.markdown("---")

    st.subheader("編輯或刪除單筆合約")

    if leases_df.empty:
        st.info("目前沒有可供操作的合約紀錄。")
    else:
        # --- 預先載入廠商列表以供編輯表單使用 ---
        if 'vendor_options' not in locals():
            vendors = vendor_model.get_vendors_for_view()
            vendor_options = {v['id']: f"{v['服務項目']} - {v['廠商名稱']}" for _, v in vendors.iterrows()} if not vendors.empty else {}
            
        if 'dorm_options' not in locals():
            dorms = dormitory_model.get_dorms_for_selection() or []
            dorm_options = {d['id']: d['original_address'] for d in dorms}
            
        lease_options_dict = {
            row['id']: f"ID:{row['id']} - {row['宿舍地址']} ({row['合約項目']})" 
            for _, row in leases_df.iterrows()
        }
        
        selected_lease_id = st.selectbox(
            "請從上方列表選擇一筆紀錄進行操作：",
            options=[None] + list(lease_options_dict.keys()),
            format_func=lambda x: "請選擇..." if x is None else lease_options_dict.get(x)
        )

        if selected_lease_id:
            lease_details = lease_model.get_single_lease_details(selected_lease_id)
            if not lease_details:
                st.error("找不到選定的合約資料。")
            else:
                with st.form(f"edit_lease_form_{selected_lease_id}"):
                    st.text_input("宿舍地址", value=dorm_options.get(lease_details['dorm_id'], "未知"), disabled=True)
                    
                    # --- 新增廠商和備註的編輯欄位 ---
                    ec1_item, ec2_item, ec3_item = st.columns(3) # 改為 3 欄
                    current_item = lease_details.get('contract_item', '')
                    item_options = ["房租", "清運費", "其他...(手動輸入)"] # 確保 item_options 存在
                    if current_item in item_options:
                        default_index = item_options.index(current_item)
                        default_custom = ""
                    else:
                        default_index = item_options.index("其他...")
                        default_custom = current_item
                    
                    e_selected_item = ec1_item.selectbox("合約項目*", options=item_options, index=default_index)
                    e_custom_item = ec1_item.text_input("自訂項目名稱", value=default_custom)
                    
                    e_monthly_rent = ec2_item.number_input("每月固定金額*", min_value=0, step=1000, value=int(lease_details.get('monthly_rent') or 0))

                    current_vendor_id = lease_details.get('vendor_id')
                    e_selected_vendor_id = ec3_item.selectbox(
                        "房東/廠商 (選填)", 
                        options=[None] + list(vendor_options.keys()), 
                        index=([None] + list(vendor_options.keys())).index(current_vendor_id) if current_vendor_id in [None] + list(vendor_options.keys()) else 0,
                        format_func=lambda x: "未指定" if x is None else vendor_options.get(x)
                    )

                    ec1, ec2 = st.columns(2)
                    start_date_val = lease_details.get('lease_start_date')
                    end_date_val = lease_details.get('lease_end_date')
                    
                    e_lease_start_date = ec1.date_input("合約起始日", value=start_date_val, min_value=thirty_years_ago, max_value=thirty_years_from_now)
                    with ec2:
                        e_lease_end_date = st.date_input("合約截止日", value=end_date_val, min_value=thirty_years_ago, max_value=thirty_years_from_now)
                        clear_end_date = st.checkbox("清除截止日 (設為長期合約)")

                    ec3, ec4 = st.columns([1, 3])
                    e_deposit = ec3.number_input("押金", min_value=0, step=1000, value=int(lease_details.get('deposit') or 0))
                    e_utilities_included = ec4.checkbox("費用是否包含水電", value=bool(lease_details.get('utilities_included', False)))

                    e_notes = st.text_area("合約備註", value=lease_details.get('notes', ''))

                    edit_submitted = st.form_submit_button("儲存變更")
                    if edit_submitted:
                        final_end_date = None
                        if not clear_end_date:
                            final_end_date = str(e_lease_end_date) if e_lease_end_date else None
                        
                        e_final_item = e_custom_item if e_selected_item == "其他..." and e_custom_item else e_selected_item
                        
                        # --- 將新欄位加入 updated_details 字典 ---
                        updated_details = {
                            "vendor_id": e_selected_vendor_id, 
                            "contract_item": e_final_item,
                            "lease_start_date": str(e_lease_start_date) if e_lease_start_date else None,
                            "lease_end_date": final_end_date,
                            "monthly_rent": e_monthly_rent,
                            "deposit": e_deposit,
                            "utilities_included": e_utilities_included,
                            "notes": e_notes 
                        }
                        success, message = lease_model.update_lease(selected_lease_id, updated_details)
                        if success:
                            st.success(message)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error(message)

                st.markdown("---")
                st.markdown("##### 危險操作區")
                confirm_delete = st.checkbox("我了解並確認要刪除此筆合約", key=f"delete_confirm_{selected_lease_id}")
                if st.button("🗑️ 刪除此合約", type="primary", disabled=not confirm_delete, key=f"delete_button_{selected_lease_id}"):
                    success, message = lease_model.delete_lease(selected_lease_id)
                    if success:
                        st.success(message)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error(message)