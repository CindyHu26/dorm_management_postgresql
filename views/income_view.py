# views/income_view.py

import streamlit as st
import pandas as pd
from datetime import datetime, date
from data_models import income_model, dormitory_model, employer_dashboard_model

def render():
    st.info("用於登錄房租以外的收入，例如冷氣卡儲值、押金沒收、固定補貼等。")

    # --- 頁籤切換 ---
    tab1, tab2, tab3 = st.tabs(["📝 收入紀錄管理 (手動)", "⚙️ 固定收入設定 & 生成", "📈 其他收入年度統計"])

    # ==========================================================================
    # 頁籤 1: 收入紀錄管理 (單筆/歷史)
    # ==========================================================================
    with tab1:
        my_dorms = dormitory_model.get_my_company_dorms_for_selection()
        if not my_dorms:
            st.warning("目前沒有「我司管理」的宿舍可供操作。")
            return

        dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}
        selected_dorm_id = st.selectbox("請選擇宿舍：", options=list(dorm_options.keys()), format_func=lambda x: dorm_options.get(x), key="income_dorm_select")

        if selected_dorm_id:
            st.markdown("---")
            with st.expander("📝 新增一筆收入紀錄 (單筆)"):
                # 獲取房間與雇主列表
                rooms_in_dorm = dormitory_model.get_rooms_for_selection(selected_dorm_id) or []
                room_options = {r['id']: r['room_number'] for r in rooms_in_dorm if r['room_number'] != '[未分配房間]'}
                all_employers = employer_dashboard_model.get_all_employers()

                if not room_options:
                    st.info("提醒：此宿舍目前尚未建立任何房號。")
                
                with st.form("new_income_form", clear_on_submit=True):
                    c1, c2, c3, c4 = st.columns(4)
                    
                    income_options = ["冷氣卡儲值", "投幣式洗衣機", "販賣機", "其他 (請手動輸入)"]
                    selected_income_item = c1.selectbox("收入項目", income_options)
                    custom_income_item = c1.text_input("自訂項目", help="若選擇「其他」，請在此填寫")

                    amount = c2.number_input("收入金額", min_value=0)
                    transaction_date = c3.date_input("收入日期", value=date.today())
                    
                    selected_room_id = c4.selectbox("關聯房號 (選填)", [None] + list(room_options.keys()), 
                                                    format_func=lambda x: "無 (不指定)" if x is None else room_options.get(x))

                    # 手動指定雇主
                    c_emp, c_note = st.columns([1, 2])
                    selected_employer = c_emp.selectbox("來源雇主 (選填)", options=[None] + all_employers, help="若此收入來自特定雇主（如工廠補貼），請在此選擇，否則將視為共用收入。")
                    notes = c_note.text_area("備註")
                    
                    submitted = st.form_submit_button("儲存收入紀錄")
                    if submitted:
                        final_income_item = custom_income_item if selected_income_item == "其他 (請手動輸入)" and custom_income_item else selected_income_item
                        
                        if not final_income_item or final_income_item == "其他 (請手動輸入)":
                            st.error("「收入項目」為必填欄位！")
                        else:
                            details = {
                                "dorm_id": selected_dorm_id, 
                                "room_id": selected_room_id,
                                "income_item": final_income_item,
                                "transaction_date": str(transaction_date), 
                                "amount": amount, 
                                "target_employer": selected_employer, # 存入雇主
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
                # 顯示列表
                st.dataframe(income_df, width="stretch", hide_index=True, column_config={"id": None})

                st.markdown("---")
                st.subheader("編輯或刪除單筆紀錄")
                
                options_dict = {
                    row['id']: f"ID:{row['id']} - {row['收入日期']} {row['收入項目']} (金額:{row['金額']})" 
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
                        st.error("找不到選定的收入資料。")
                    else:
                        with st.form(f"edit_income_form_{selected_income_id}"):
                            st.markdown(f"###### 正在編輯 ID: {selected_income_id}")
                            ec1, ec2, ec3, ec4 = st.columns(4)
                            
                            e_income_item = ec1.text_input("收入項目", value=income_details.get('income_item', ''))
                            e_amount = ec2.number_input("收入金額", min_value=0, value=income_details.get('amount', 0))
                            e_transaction_date = ec3.date_input("收入日期", value=income_details.get('transaction_date'))
                            
                            edit_rooms = dormitory_model.get_rooms_for_selection(selected_dorm_id) or []
                            edit_room_opts = {r['id']: r['room_number'] for r in edit_rooms if r['room_number'] != '[未分配房間]'}
                            curr_rid = income_details.get('room_id')
                            e_room_id = ec4.selectbox("關聯房號", [None] + list(edit_room_opts.keys()), 
                                                      index=([None] + list(edit_room_opts.keys())).index(curr_rid) if curr_rid in [None] + list(edit_room_opts.keys()) else 0,
                                                      format_func=lambda x: "無" if x is None else edit_room_opts.get(x))

                            e_note_c1, e_note_c2 = st.columns([1, 2])
                            all_emps = employer_dashboard_model.get_all_employers()
                            curr_emp = income_details.get('target_employer')
                            e_target_employer = e_note_c1.selectbox("來源雇主", [None] + all_emps, 
                                                                    index=([None] + all_emps).index(curr_emp) if curr_emp in all_emps else 0)
                            e_notes = e_note_c2.text_area("備註", value=income_details.get('notes', ''))

                            edit_submitted = st.form_submit_button("儲存變更")
                            if edit_submitted:
                                updated_details = {
                                    "room_id": e_room_id,
                                    "income_item": e_income_item,
                                    "amount": e_amount,
                                    "transaction_date": str(e_transaction_date),
                                    "target_employer": e_target_employer,
                                    "notes": e_notes
                                }
                                success, message = income_model.update_income_record(selected_income_id, updated_details)
                                if success:
                                    st.success(message)
                                    st.cache_data.clear()
                                    st.rerun()
                                else:
                                    st.error(message)

                        st.markdown("##### 危險操作區")
                        if st.checkbox(f"我確認要刪除此筆收入紀錄"):
                            if st.button("🗑️ 刪除此筆紀錄", type="primary"):
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
        
        # 取得資料
        all_employers = employer_dashboard_model.get_all_employers()
        all_dorm_opts = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in dormitory_model.get_dorms_for_selection()}

        # ----------------------------------------------------------------------
        # 1. 新增設定 (Add New)
        # ----------------------------------------------------------------------
        with st.expander("➕ 新增固定收入規則", expanded=True):
            
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
            
            # --- 動態取得該宿舍的雇主清單 (並加上標籤) ---
            dorm_employers = []
            employer_options_display = [] # 用於顯示的列表
            
            if r_dorm_id:
                dorm_employers = employer_dashboard_model.get_employers_by_dorm(r_dorm_id)
                
                # 製作有標籤的選項
                # 1. 在住雇主 (加上標籤)
                resident_opts = [f"{e} (在住)" for e in dorm_employers]
                # 2. 其他雇主
                other_opts = [e for e in all_employers if e not in dorm_employers]
                
                employer_options_display = [None] + resident_opts + other_opts
            else:
                employer_options_display = [None] + all_employers
            # -------------------------------------------------------

            with st.form("new_recurring_form", clear_on_submit=True):
                st.markdown("##### 2. 填寫詳細資訊")
                
                rc_item, rc_amt = st.columns([2, 1])
                r_item = rc_item.text_input("收入項目名稱", placeholder="例如: 工廠房租補貼")
                
                r_target_employer_display = None
                amount_label = "每月金額"
                
                # 根據模式顯示不同欄位
                if calc_method == 'headcount':
                    amount_label = "每人單價 (元/人)"
                    st.markdown("---")
                    st.markdown(f"###### 設定人頭計費參數")
                    emp_help = "「按人頭計費」必須指定目標雇主。"
                else:
                    st.markdown("---")
                    st.markdown(f"###### 設定歸屬對象 (選填)")
                    emp_help = "若指定雇主，收入歸該雇主；若留空，則為共用收入。"

                c_emp, c_ph = st.columns([2, 1])
                
                if not dorm_employers and calc_method == 'headcount':
                    c_emp.warning("⚠️ 此宿舍目前沒有在住雇主。")
                
                # 使用有標籤的選項列表
                r_target_employer_display = c_emp.selectbox(
                    "選擇目標雇主", 
                    options=employer_options_display, 
                    help=emp_help
                )
                    
                r_amount = c_ph.number_input(amount_label, min_value=0, step=100)

                st.markdown("##### 有效期間 (選填)")
                rc4, rc5 = st.columns(2)
                r_start_date = rc4.date_input("生效起始日", value=None, help="若留空，代表立即生效")
                r_end_date = rc5.date_input("生效結束日", value=None, help="若留空，代表無限期")
                
                r_notes = st.text_area("備註")
                
                if st.form_submit_button("儲存設定"):
                    # --- 清理雇主名稱 (移除標籤) ---
                    final_employer = None
                    if r_target_employer_display:
                        # 移除 " (在住)" 後綴
                        final_employer = r_target_employer_display.replace(" (在住)", "").strip()
                    # --------------------------------
                    
                    if not r_item: 
                        st.error("請填寫收入項目名稱")
                    elif calc_method == 'headcount' and not final_employer:
                        st.error("選擇「按人頭計費」時，必須指定「目標雇主」！")
                    else:
                        s_date_str = str(r_start_date) if r_start_date else None
                        e_date_str = str(r_end_date) if r_end_date else None
                        
                        success, msg = income_model.add_recurring_config({
                            "dorm_id": r_dorm_id, 
                            "income_item": r_item, 
                            "amount": r_amount, 
                            "calc_method": calc_method,
                            "target_employer": final_employer, # 存入乾淨的名稱
                            "start_date": s_date_str, 
                            "end_date": e_date_str,
                            "notes": r_notes
                        })
                        if success: 
                            st.success(msg)
                            st.rerun()
                        else: 
                            st.error(msg)

        # ----------------------------------------------------------------------
        # 2. 列表與編輯 (List & Edit & Delete)
        # ----------------------------------------------------------------------
        st.markdown("---")
        st.subheader("📋 現有設定列表")
        
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
                        "目標雇主", options=all_employers, required=False,
                    ),
                    "金額/單價": st.column_config.NumberColumn(format="$%d"),
                    "生效起始日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "生效結束日": st.column_config.DateColumn(format="YYYY-MM-DD"),
                    "啟用中": st.column_config.CheckboxColumn(label="啟用?"),
                },
                key="recurring_editor"
            )
            
            col_save, col_del = st.columns([1, 3])
            
            if col_save.button("💾 儲存列表變更"):
                updated_count = 0
                for index, row in edited_configs.iterrows():
                    # 處理日期
                    s_date = row['生效起始日'] if pd.notna(row['生效起始日']) else None
                    e_date = row['生效結束日'] if pd.notna(row['生效結束日']) else None
                    
                    # 1. 取得雇主 (無論模式為何，都保留使用者選的值)
                    raw_employer = row.get('目標雇主')
                    t_employer = str(raw_employer).strip() if pd.notna(raw_employer) and str(raw_employer).strip() else None

                    # 2. 取得模式
                    user_mode_str = row.get('顯示模式')
                    
                    # --- 【核心修正】完全信任使用者的選擇 ---
                    # 移除 "or t_employer is not None" 的自動判斷
                    if user_mode_str == '按人頭':
                        c_method = 'headcount'
                    else:
                        c_method = 'fixed'
                    
                    # 執行更新
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
                
                st.success(f"已成功更新 {updated_count} 筆設定。")
                st.rerun()

            # --- 刪除功能 (整合在列表下方) ---
            with st.expander("🗑️ 刪除設定"):
                # 準備刪除選單的標籤 (含日期區間)
                del_c1, del_c2 = st.columns([3, 1])
                delete_options_map = {}
                for _, row in configs_df.iterrows():
                    s_date_str = str(row['生效起始日']) if pd.notna(row['生效起始日']) else "即日起"
                    e_date_str = str(row['生效結束日']) if pd.notna(row['生效結束日']) else "無限期"
                    label = f"{row['收入項目']} - {row['宿舍地址']} ({s_date_str} ~ {e_date_str})"
                    delete_options_map[row['id']] = label

                config_to_del = del_c1.selectbox(
                    "選擇要刪除的規則", 
                    options=list(delete_options_map.keys()), 
                    format_func=lambda x: delete_options_map.get(x, "未知"),
                    key="del_config_select"
                )
                if del_c2.button("確認刪除", type="primary", key="del_config_btn"):
                    income_model.delete_recurring_config(config_to_del)
                    st.success("刪除成功")
                    st.rerun()

        # ----------------------------------------------------------------------
        # 3. 自動生成 (Generation)
        # ----------------------------------------------------------------------
        st.markdown("---")
        st.subheader("🚀 自動生成收入")
        st.info("此功能會讀取上方「所有啟用中」的設定，自動產生 OtherIncome 紀錄。")
        
        gen_tab1, gen_tab2 = st.tabs(["單月生成 (指定月份)", "區間批次生成 (補帳用)"])
        
        with gen_tab1:
            with st.container(border=True):
                st.write("針對「特定月份」執行生成。")
                gc1, gc2, gc3 = st.columns(3)
                gen_year = gc1.number_input("年份", value=date.today().year)
                gen_month = gc2.number_input("月份", value=date.today().month, min_value=1, max_value=12)
                
                gc3.write("") 
                gc3.write("")
                if gc3.button("執行單月生成", type="primary", width='stretch'):
                    with st.spinner("正在生成收入紀錄..."):
                        success, msg = income_model.generate_monthly_recurring_income(gen_year, gen_month)
                    
                    if success:
                        st.success(msg)
                        st.info(f"提示：生成的紀錄已加入「收入紀錄管理」頁籤。")
                    else:
                        st.error(msg)

        with gen_tab2:
            with st.container(border=True):
                st.write("針對「一段時間範圍」執行生成。")
                bc1, bc2, bc3 = st.columns(3)
                default_start = date(date.today().year, 1, 1)
                batch_start_date = bc1.date_input("起始月份", value=default_start)
                batch_end_date = bc2.date_input("結束月份", value=date.today())
                
                bc3.write("") 
                bc3.write("")
                if bc3.button("執行區間批次生成", type="primary", width='stretch'):
                    if batch_start_date > batch_end_date:
                        st.error("起始日期不能晚於結束日期！")
                    else:
                        with st.spinner(f"正在生成..."):
                            success, msg = income_model.batch_generate_recurring_income(batch_start_date, batch_end_date)
                        if success: st.success(msg)
                        else: st.error(msg)

    # ==================== 第三個頁籤 (支援地址與項目多選、單純列表呈現) ====================
    with tab3:
        st.subheader("📊 其他收入年度與項目分析")
        
        # 呼叫 Model 統計函式 (地址已經變成 "(編號) 地址" 的格式)
        stats_df = income_model.get_other_income_annual_stats()
        
        if stats_df.empty:
            st.info("目前沒有任何其他收入的紀錄可供統計。")
        else:
            # --- 1. 選擇年度 ---
            available_years = sorted(stats_df['年度'].unique(), reverse=True)
            selected_year = st.selectbox("📅 選擇統計年度", options=available_years, key="other_inc_stat_year")
            
            # 篩出該年度擁有的所有地址與項目
            year_df = stats_df[stats_df['年度'] == selected_year]
            all_addresses = sorted(year_df['宿舍地址'].unique())
            all_items = sorted(year_df['項目'].unique())
            
            st.divider()

            # --- 2. 雙重篩選控制區 (地址與項目並排) ---
            col_addr, col_item = st.columns(2)
            
            # (A) 宿舍地址篩選區
            with col_addr:
                st.markdown("**🏠 宿舍地址篩選**")
                btn_a1, btn_a2 = st.columns(2)
                
                # 直接針對元件的 key ("ms_addrs") 進行初始化與安全過濾
                if "ms_addrs" not in st.session_state:
                    st.session_state.ms_addrs = all_addresses
                else:
                    # 年份切換時的防呆過濾
                    st.session_state.ms_addrs = [a for a in st.session_state.ms_addrs if a in all_addresses]
                    
                if btn_a1.button("✅ 全選地址", key="btn_all_addrs", use_container_width=True):
                    st.session_state.ms_addrs = all_addresses
                    st.rerun()
                if btn_a2.button("❌ 清空地址", key="btn_clear_addrs", use_container_width=True):
                    st.session_state.ms_addrs = []
                    st.rerun()
                    
                # 移除 default 參數，完全交給 key 自動同步畫面
                selected_addrs = st.multiselect(
                    "選擇欲統計的宿舍", 
                    options=all_addresses, 
                    key="ms_addrs",
                    label_visibility="collapsed"
                )

            # (B) 收入項目篩選區
            with col_item:
                st.markdown("**🔍 收入項目篩選**")
                btn_i1, btn_i2 = st.columns(2)
                
                # 直接針對元件的 key ("ms_items") 進行初始化與安全過濾
                if "ms_items" not in st.session_state:
                    desired_defaults = ["冷氣卡儲值", "投幣式洗衣機"]
                    st.session_state.ms_items = [item for item in desired_defaults if item in all_items]
                else:
                    # 年份切換時的防呆過濾
                    st.session_state.ms_items = [i for i in st.session_state.ms_items if i in all_items]
                    
                if btn_i1.button("✅ 全選項目", key="btn_all_items", use_container_width=True):
                    st.session_state.ms_items = all_items
                    st.rerun()
                if btn_i2.button("❌ 清空項目", key="btn_clear_items", use_container_width=True):
                    st.session_state.ms_items = []
                    st.rerun()
                    
                # 移除 default 參數，完全交給 key 自動同步畫面
                selected_items = st.multiselect(
                    "選擇欲統計的項目", 
                    options=all_items, 
                    key="ms_items",
                    label_visibility="collapsed"
                )
                st.session_state.selected_income_items = selected_items

            st.divider()

            # --- 3. 數據處理與單純列表呈現 ---
            final_df = year_df[
                year_df['宿舍地址'].isin(selected_addrs) & 
                year_df['項目'].isin(selected_items)
            ]
            
            if final_df.empty:
                st.warning("⚠️ 查無符合條件的數據，請放寬您的篩選條件。")
            else:
                # 計算總金額
                total_amount = final_df['總金額'].sum()
                
                # 大字卡顯示目前條件下的總收入
                st.metric(
                    label=f"💰 {selected_year} 年度 - 篩選條件合計總收入", 
                    value=f"${total_amount:,.0f} 元"
                )
                
                st.write("##### 📋 項目金額明細列表")
                
                # 整理只要顯示的三個欄位 (地址、項目、總金額)
                display_df = final_df[['宿舍地址', '項目', '總金額']].copy()
                
                # 將資料先依地址排、再依金額排，方便閱讀
                display_df = display_df.sort_values(by=['宿舍地址', '總金額'], ascending=[True, False])
                
                # 加上千分位格式
                display_df['總金額'] = display_df['總金額'].map(lambda x: f"${x:,.0f}")
                
                # 直接輸出全寬度的表格，不用圖表
                st.dataframe(
                    display_df, 
                    hide_index=True, 
                    use_container_width=True
                )