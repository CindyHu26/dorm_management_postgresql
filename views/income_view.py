import streamlit as st
import pandas as pd
from datetime import datetime, date
from data_models import income_model, dormitory_model, employer_dashboard_model

def render():
    st.header("我司管理宿舍 - 其他收入管理")
    st.info("管理房租以外的收入。您可以在此設定「每月固定收入」，並一鍵生成帳單。")

    # --- 頁籤切換 ---
    tab1, tab2 = st.tabs(["📝 收入紀錄管理", "⚙️ 固定收入設定 & 生成"])

    # ==========================================================================
    # 頁籤 1: 收入紀錄管理 (維持原有功能)
    # ==========================================================================
    with tab1:
        my_dorms = dormitory_model.get_my_company_dorms_for_selection()
        if not my_dorms:
            st.warning("目前沒有「我司管理」的宿舍可供操作。")
            return

        dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}
        selected_dorm_id = st.selectbox("請選擇宿舍：", options=list(dorm_options.keys()), format_func=lambda x: dorm_options.get(x))

        if not selected_dorm_id: return
        st.markdown("---")
        
        with st.expander("📝 新增一筆收入紀錄"):
            # --- 在這裡先獲取房間列表並進行檢查 ---
            rooms_in_dorm = dormitory_model.get_rooms_for_selection(selected_dorm_id) or []
            # 只顯示真實的房號（過濾掉系統預設的）
            room_options = {r['id']: r['room_number'] for r in rooms_in_dorm if r['room_number'] != '[未分配房間]'}

            # 只有當一個真實的房號都沒有時，才顯示提醒
            if not room_options:
                st.info("提醒：此宿舍目前尚未建立任何房號。若此筆收入需關聯特定房間(如冷氣卡)，建議先至「地址管理」新增房號。")
            
            with st.form("new_income_form", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns(4)
                
                income_options = ["冷氣卡儲值", "投幣式洗衣機", "販賣機", "其他 (請手動輸入)"]
                selected_income_item = c1.selectbox("收入項目", income_options)
                custom_income_item = c1.text_input("自訂收入項目", help="若上方選擇「其他」，請在此處填寫")

                amount = c2.number_input("收入金額", min_value=0)
                transaction_date = c3.date_input("收入日期", value=date.today())
                
                # --- 無論如何都讓使用者可以選擇，只是選項可能為空 ---
                selected_room_id = c4.selectbox("關聯房號 (選填)", [None] + list(room_options.keys()), 
                                                format_func=lambda x: "無 (不指定)" if x is None else room_options.get(x))

                notes = st.text_area("備註")
                
                submitted = st.form_submit_button("儲存收入紀錄")
                if submitted:
                    final_income_item = custom_income_item if selected_income_item == "其他 (請手動輸入)" and custom_income_item else selected_income_item
                    
                    if not final_income_item or final_income_item == "其他 (請手動輸入)":
                        st.error("「收入項目」為必填欄位！若選擇「其他」，請務必填寫自訂項目。")
                    else:
                        details = {
                            "dorm_id": selected_dorm_id, 
                            "room_id": selected_room_id,
                            "income_item": final_income_item,
                            "transaction_date": str(transaction_date), 
                            "amount": amount, 
                            "notes": notes
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
            display_cols = ["收入日期", "收入項目", "房號", "金額", "備註", "id"]
            existing_cols = [col for col in display_cols if col in income_df.columns]
            if "收入日期" in income_df.columns:
                income_df["收入日期"] = pd.to_datetime(income_df["收入日期"]).dt.date
            st.dataframe(income_df[existing_cols], width="stretch", hide_index=True, column_config={"id": None})

            st.markdown("---")
            st.subheader("編輯或刪除單筆紀錄")
            
            options_dict = {
                row['id']: f"ID:{row['id']} - {row['收入日期']} {row['收入項目']} (房號: {row.get('房號') or '無'}) 金額:{row['金額']}" 
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
                    with st.form(f"edit_income_form_{selected_income_id}"):
                        st.markdown(f"###### 正在編輯 ID: {selected_income_id} 的紀錄")
                        ec1, ec2, ec3, ec4 = st.columns(4)
                        
                        e_income_item = ec1.text_input("收入項目", value=income_details.get('income_item', ''))
                        e_amount = ec2.number_input("收入金額", min_value=0, value=income_details.get('amount', 0))
                        e_transaction_date = ec3.date_input("收入日期", value=income_details.get('transaction_date'))
                        
                        edit_rooms_in_dorm = dormitory_model.get_rooms_for_selection(selected_dorm_id) or []
                        edit_room_options = {r['id']: r['room_number'] for r in edit_rooms_in_dorm if r['room_number'] != '[未分配房間]'}
                        current_room_id = income_details.get('room_id')
                        edit_selected_room_id = ec4.selectbox("關聯房號 (選填)", [None] + list(edit_room_options.keys()), 
                                                            index=([None] + list(edit_room_options.keys())).index(current_room_id) if current_room_id in [None] + list(edit_room_options.keys()) else 0,
                                                            format_func=lambda x: "無 (不指定)" if x is None else edit_room_options.get(x))

                        e_notes = st.text_area("備註", value=income_details.get('notes', ''))

                        edit_submitted = st.form_submit_button("儲存變更")
                        if edit_submitted:
                            updated_details = {
                                "room_id": edit_selected_room_id,
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

    # ==========================================================================
    # 頁籤 2: 固定收入設定 & 生成
    # ==========================================================================
    with tab2:
        st.markdown("#### ⚙️ 固定收入設定")
        st.info("設定每個月固定的收入項目。支援「固定金額」或「按人頭計費」。")
        
        # 準備宿舍選項
        all_dorm_opts = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dormitory_model.get_dorms_for_selection()}
        all_employers = employer_dashboard_model.get_all_employers()
        
        # 1. 新增設定
        with st.expander("➕ 新增固定收入規則", expanded=True):
            
            # --- 【核心修改】將「宿舍」與「模式」都移出 form 外面，以實現連動 ---
            st.markdown("##### 1. 選擇宿舍與模式")
            c_dorm, c_mode = st.columns(2)
            
            # 1. 選擇宿舍 (觸發更新)
            r_dorm_id = c_dorm.selectbox(
                "宿舍地址", 
                options=list(all_dorm_opts.keys()), 
                format_func=lambda x: all_dorm_opts[x],
                key="recur_add_dorm"
            )
            
            # 2. 選擇模式 (觸發更新)
            calc_method_label = c_mode.radio(
                "計費模式", 
                ["固定金額 (每月定額)", "按人頭計費 (人數 x 單價)"], 
                index=0,
                horizontal=True,
                key="income_calc_mode_radio"
            )
            calc_method = 'fixed' if calc_method_label == "固定金額 (每月定額)" else 'headcount'
            
            # --- 動態取得該宿舍的雇主清單 ---
            dorm_employers = []
            if r_dorm_id:
                dorm_employers = employer_dashboard_model.get_employers_by_dorm(r_dorm_id)
            # -------------------------------------------------------

            with st.form("new_recurring_form", clear_on_submit=True):
                st.markdown("##### 2. 填寫詳細資訊")
                
                # 宿舍已經在外面選了，這裡顯示選了哪個 (唯讀提示) 或直接不顯示
                # 為了排版美觀，我們直接開始填寫項目
                
                rc_item, rc_amt = st.columns([2, 1])
                r_item = rc_item.text_input("收入項目名稱", placeholder="例如: 工廠房租補貼")
                
                r_target_employer = None
                amount_label = "每月金額"
                
                # 根據模式顯示不同欄位
                if calc_method == 'headcount':
                    amount_label = "每人單價 (元/人)"
                    st.markdown("---")
                    st.markdown(f"###### 設定人頭計費參數 (目前宿舍: {all_dorm_opts.get(r_dorm_id, '')})")
                    
                    c_emp, c_ph = st.columns([2, 1])
                    
                    if not dorm_employers:
                        c_emp.warning("⚠️ 此宿舍目前沒有任何在住的雇主員工。")
                        # 還是提供所有雇主供選擇，以免系統剛建置沒人時無法設定
                        fallback_employers = employer_dashboard_model.get_all_employers()
                        r_target_employer = c_emp.selectbox("選擇目標雇主", options=fallback_employers)
                    else:
                        r_target_employer = c_emp.selectbox("選擇目標雇主 (僅列出該宿舍現有雇主)", options=dorm_employers)
                        
                    r_amount = c_ph.number_input(amount_label, min_value=0, step=100)
                else:
                    r_amount = rc_amt.number_input(amount_label, min_value=0, step=100)

                st.markdown("##### 有效期間 (選填)")
                rc4, rc5 = st.columns(2)
                r_start_date = rc4.date_input("生效起始日", value=None, help="若留空，代表立即生效")
                r_end_date = rc5.date_input("生效結束日", value=None, help="若留空，代表無限期")
                
                r_notes = st.text_area("備註")
                
                if st.form_submit_button("儲存設定"):
                    if not r_item: 
                        st.error("請填寫收入項目名稱")
                    elif calc_method == 'headcount' and not r_target_employer:
                        st.error("選擇按人頭計費時，必須指定「目標雇主」。")
                    else:
                        s_date_str = str(r_start_date) if r_start_date else None
                        e_date_str = str(r_end_date) if r_end_date else None
                        
                        success, msg = income_model.add_recurring_config({
                            "dorm_id": r_dorm_id, # 使用 form 外面的變數
                            "income_item": r_item, 
                            "amount": r_amount, 
                            "calc_method": calc_method,
                            "target_employer": r_target_employer,
                            "start_date": s_date_str, 
                            "end_date": e_date_str,
                            "notes": r_notes
                        })
                        if success: 
                            st.success(msg)
                            st.rerun() # 重新執行以清除表單並更新列表
                        else: 
                            st.error(msg)

        # 2. 列表與編輯 (維持不變)
        st.markdown("---")
        st.markdown("##### 現有設定列表")
        
        configs_df = income_model.get_recurring_configs()
        
        if configs_df.empty:
            st.info("目前沒有任何固定收入設定。")
        else:
            configs_df['顯示模式'] = configs_df['計算模式'].map({'fixed': '固定金額', 'headcount': '按人頭'})
            
            edited_configs = st.data_editor(
                configs_df,
                hide_index=True,
                column_config={
                    "id": None, "計算模式": None, 
                    "宿舍地址": st.column_config.TextColumn(disabled=True),
                    "收入項目": st.column_config.TextColumn(disabled=True),
                    "顯示模式": st.column_config.SelectboxColumn(
                        "模式", options=["固定金額", "按人頭"], required=True
                    ),
                    "目標雇主": st.column_config.SelectboxColumn(
                        "目標雇主", options=all_employers, required=False, width="medium"
                    ),
                    "金額/單價": st.column_config.NumberColumn(format="$%d"),
                    "生效起始日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "生效結束日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "啟用中": st.column_config.CheckboxColumn(label="啟用?"),
                },
                key="recurring_editor"
            )
            
            if st.button("💾 儲存列表變更"):
                updated_count = 0
                for index, row in edited_configs.iterrows():
                    s_date = row['生效起始日'] if pd.notna(row['生效起始日']) else None
                    e_date = row['生效結束日'] if pd.notna(row['生效結束日']) else None
                    
                    c_method = 'fixed' if row['顯示模式'] == '固定金額' else 'headcount'
                    t_employer = row['目標雇主'] if c_method == 'headcount' else None

                    income_model.update_recurring_config(row['id'], {
                        "amount": row['金額/單價'],
                        "calc_method": c_method,
                        "target_employer": t_employer,
                        "start_date": s_date,
                        "end_date": e_date,
                        "active": row['啟用中'],
                        "notes": row['備註']
                    })
                    updated_count += 1
                st.success(f"已更新設定。")
                st.rerun()

            st.markdown("###### 刪除設定")
            del_c1, del_c2 = st.columns([3, 1])
            config_to_del = del_c1.selectbox("選擇要刪除的設定", options=configs_df['id'], format_func=lambda x: f"{configs_df[configs_df['id']==x]['收入項目'].iloc[0]} - {configs_df[configs_df['id']==x]['宿舍地址'].iloc[0]}")
            if del_c2.button("🗑️ 刪除", type="primary"):
                income_model.delete_recurring_config(config_to_del)
                st.success("刪除成功")
                st.rerun()

        # 3. 一鍵生成 (維持不變)
        st.markdown("---")
        st.subheader("🚀 一鍵生成本月收入")
        with st.container(border=True):
            gc1, gc2, gc3 = st.columns(3)
            gen_year = gc1.number_input("年份", value=date.today().year)
            gen_month = gc2.number_input("月份", value=date.today().month, min_value=1, max_value=12)
            
            gc3.write("") 
            gc3.write("")
            if gc3.button("執行生成", type="primary", use_container_width=True):
                with st.spinner("正在生成收入紀錄..."):
                    success, msg = income_model.generate_monthly_recurring_income(gen_year, gen_month)
                
                if success:
                    st.success(msg)
                    st.info(f"提示：生成的紀錄已自動加入「收入紀錄管理」頁籤，日期為 {gen_year}-{gen_month:02d}-01。")
                else:
                    st.error(msg)