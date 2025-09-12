import streamlit as st
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from data_models import lease_model, dormitory_model

def render():
    """渲染「合約管理」頁面"""
    st.header("租賃合約管理")

    # 【核心修改】計算前後 30 年的日期範圍
    today = date.today()
    thirty_years_ago = today - relativedelta(years=30)
    thirty_years_from_now = today + relativedelta(years=30)

    with st.expander("➕ 新增租賃合約"):
        with st.form("new_lease_form", clear_on_submit=True):
            dorms = dormitory_model.get_dorms_for_selection() or []
            dorm_options = {d['id']: d['original_address'] for d in dorms}
            
            selected_dorm_id = st.selectbox("選擇宿舍地址", options=dorm_options.keys(), format_func=lambda x: dorm_options.get(x, "未知宿舍"))
            
            c1, c2 = st.columns(2)
            # 【核心修改】為日期輸入框設定新的 min_value 和 max_value
            lease_start_date = c1.date_input("合約起始日", value=None, min_value=thirty_years_ago, max_value=thirty_years_from_now)
            lease_end_date = c2.date_input("合約截止日", value=None, min_value=thirty_years_ago, max_value=thirty_years_from_now)
            
            c3, c4, c5 = st.columns(3)
            monthly_rent = c3.number_input("月租金", min_value=0, step=1000)
            deposit = c4.number_input("押金", min_value=0, step=1000)
            utilities_included = c5.checkbox("租金含水電")

            submitted = st.form_submit_button("儲存新合約")
            if submitted:
                details = {
                    "dorm_id": selected_dorm_id,
                    "lease_start_date": str(lease_start_date) if lease_start_date else None,
                    "lease_end_date": str(lease_end_date) if lease_end_date else None,
                    "monthly_rent": monthly_rent,
                    "deposit": deposit,
                    "utilities_included": utilities_included
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
    
    st.dataframe(leases_df, width="stretch", hide_index=True)
    
    st.markdown("---")

    st.subheader("編輯或刪除單筆合約")

    if leases_df.empty:
        st.info("目前沒有可供操作的合約紀錄。")
    else:
        if 'dorm_options' not in locals():
            dorms = dormitory_model.get_dorms_for_selection() or []
            dorm_options = {d['id']: d['original_address'] for d in dorms}
            
        lease_options_dict = {
            row['id']: f"ID:{row['id']} - {row['宿舍地址']} ({row['合約起始日']})" 
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
                    
                    ec1, ec2 = st.columns(2)
                    start_date_val = lease_details.get('lease_start_date')
                    end_date_val = lease_details.get('lease_end_date')
                    
                    # 【核心修改】為日期輸入框設定新的 min_value 和 max_value
                    e_lease_start_date = ec1.date_input("合約起始日", value=start_date_val, min_value=thirty_years_ago, max_value=thirty_years_from_now)
                    e_lease_end_date = ec2.date_input("合約截止日", value=end_date_val, min_value=thirty_years_ago, max_value=thirty_years_from_now)
                    
                    ec3, ec4, ec5 = st.columns(3)
                    e_monthly_rent = ec3.number_input("月租金", min_value=0, step=1000, value=int(lease_details.get('monthly_rent') or 0))
                    e_deposit = ec4.number_input("押金", min_value=0, step=1000, value=int(lease_details.get('deposit') or 0))
                    e_utilities_included = ec5.checkbox("租金含水電", value=bool(lease_details.get('utilities_included', False)))

                    edit_submitted = st.form_submit_button("儲存變更")
                    if edit_submitted:
                        updated_details = {
                            "lease_start_date": str(e_lease_start_date) if e_lease_start_date else None,
                            "lease_end_date": str(e_lease_end_date) if e_lease_end_date else None,
                            "monthly_rent": e_monthly_rent,
                            "deposit": e_deposit,
                            "utilities_included": e_utilities_included
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