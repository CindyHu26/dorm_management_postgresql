# views/dorm_analyzer_view.py (複選版)

import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import database
from data_models import dormitory_model, single_dorm_analyzer, analytics_model

def render():
    """渲染「宿舍深度分析」頁面"""
    st.header("宿舍深度分析儀表板")
    with st.sidebar:
        st.markdown("### ⚙️ 合規設定")
        # 讀取 config 作為預設值，但允許使用者調整
        general_config = database.get_general_config()
        default_standard = float(general_config.get('min_area_per_person', 3.6))
        
        min_area_standard = st.number_input(
            "人均面積標準 (m²)", 
            value=default_standard, 
            step=0.1,
            help="調整此數值可即時更新右側的紅色警告標準"
        )
    # --- 1. 宿舍選擇 (改為複選) ---
    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前沒有「我司管理」的宿舍可供分析。")
        return

    dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}
    
    selected_dorm_ids = st.multiselect(
        "請選擇要分析的宿舍 (可複選)：",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options.get(x, "未知宿舍")
    )

    if not selected_dorm_ids:
        st.info("請從上方列表至少選擇一間宿舍以開始分析。")
        return
        
    st.markdown("---")

    # --- 2. 顯示基本資訊 (僅在選取單一宿舍時顯示) ---
    
    if len(selected_dorm_ids) == 1:
        selected_dorm_id = selected_dorm_ids[0]
        basic_info = single_dorm_analyzer.get_dorm_basic_info(selected_dorm_id)
        meters_df = single_dorm_analyzer.get_dorm_meters(selected_dorm_ids) # 傳入 list

        st.subheader(f"基本資訊: {dorm_options[selected_dorm_id]}")
        if basic_info:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("主要管理人", basic_info.get('primary_manager'))
            c2.metric("租金支付方", basic_info.get('rent_payer'))
            c3.metric("水電支付方", basic_info.get('utilities_payer'))
            rent_value = basic_info.get('monthly_rent') or 0
            c4.metric("當前月租", f"NT$ {int(rent_value):,}")
            st.write(f"**租賃合約期間:** {basic_info.get('lease_start_date', 'N/A')} ~ {basic_info.get('lease_end_date', 'N/A')}")
        if not meters_df.empty:
            with st.expander("顯示此宿舍的電水錶號"):
                st.dataframe(meters_df, width="stretch", hide_index=True)
    else:
        st.subheader("基本資訊")
        st.info(f"您已選擇 {len(selected_dorm_ids)} 間宿舍。基本資訊與電水錶清單僅在單選一間宿舍時顯示。")
        meters_df = single_dorm_analyzer.get_dorm_meters(selected_dorm_ids)
        if not meters_df.empty:
            with st.expander(f"顯示所選 {len(selected_dorm_ids)} 間宿舍的電水錶號總覽"):
                st.dataframe(meters_df, width="stretch", hide_index=True)
            
    st.markdown("---")

    # --- 3. 數據分析區塊 (所有函式都傳入 selected_dorm_ids) ---
    st.subheader("數據分析")
    
    today = datetime.now()
    default_date = today - relativedelta(months=2)
    default_year = default_date.year
    default_month = default_date.month
    
    year_options = list(range(today.year - 2, today.year + 2))
    try:
        default_year_index = year_options.index(default_year)
    except ValueError:
        default_year_index = 2

    sc1, sc2 = st.columns(2)
    selected_year = sc1.selectbox("選擇年份", options=year_options, index=default_year_index)
    selected_month = sc2.selectbox("選擇月份", options=range(1, 13), index=default_month - 1)
    year_month_str = f"{selected_year}-{selected_month:02d}"

    resident_data = single_dorm_analyzer.get_resident_summary(selected_dorm_ids, year_month_str)
    
    st.markdown(f"#### {year_month_str} 住宿人員分析 (彙總)")
    st.metric("總在住人數 (彙總)", f"{resident_data['total_residents']} 人")

    res_c1, res_c2, res_c3 = st.columns(3)
    with res_c1:
        st.markdown("**性別分佈 (彙總)**")
        st.dataframe(resident_data['gender_counts'],  width="stretch", hide_index=True)
    with res_c2:
        st.markdown("**國籍分佈 (彙總)**")
        st.dataframe(resident_data['nationality_counts'],  width="stretch", hide_index=True)
    with res_c3:
        st.markdown("**該月總收租簡表 (彙總)**")
        st.dataframe(resident_data['rent_summary'],  width="stretch", hide_index=True)

    st.subheader(f"{year_month_str} 宿舍營運分析 (彙總)")
    analysis_data = single_dorm_analyzer.get_dorm_analysis_data(selected_dorm_ids, year_month_str)
    if not analysis_data:
        st.error("分析數據時發生錯誤，請檢查資料庫連線。")
    else:
        st.markdown("##### Ａ. 宿舍容量與概況 (彙總)")
        st.metric("宿舍總床位容量 (彙總)", f"{analysis_data['total_capacity']} 床")
        st.markdown("##### Ｂ. 當月實際住宿分析 (彙總)")
        ar, er, ab = analysis_data['actual_residents'], analysis_data['external_residents'], analysis_data['available_beds']
        b_col1, b_col2, b_col3 = st.columns(3)
        b_col1.metric("目前實際住宿人數 (彙總)", f"{ar['total']} 人", help="計算方式：所有住在該宿舍的人員，扣除『掛宿外住』者。")
        b_col2.metric("掛宿外住人數 (彙總)", f"{er['total']} 人", help="計算方式：統計特殊狀況為『掛宿外住』的人員總數。")
        b_col3.metric("一般可住空床數 (彙總)", f"{ab['total']} 床", help="計算方式：[總容量] - [實際住宿人數] - [特殊房間獨立空床數]。代表可自由安排的床位。")
        st.markdown(f"**實際住宿性別比 (彙總)**：男 {ar['male']} 人 / 女 {ar['female']} 人")
        st.markdown(f"**掛宿外住性別比 (彙總)**：男 {er['male']} 人 / 女 {er['female']} 人")
        st.markdown("##### Ｃ. 特殊房間註記與獨立空床 (彙總)")
        special_rooms_df = analysis_data['special_rooms']
        if special_rooms_df.empty:
            st.info("所選宿舍沒有任何註記特殊備註的房間。")
        else:
            st.warning("注意：下方所列房間的空床位『不』計入上方的一般可住空床數，需獨立評估安排。")
            st.dataframe(
                special_rooms_df[['room_number', 'room_notes', 'capacity', '目前住的人數', '獨立空床數']],
                 width="stretch", hide_index=True
            )
            
    st.markdown("---")
    # --- 房況總覽區塊 ---
    st.subheader(f"{year_month_str} 宿舍房況總覽 (彙總)")
    
    @st.cache_data
    def get_room_view_data(dorm_ids, year_month):
        return single_dorm_analyzer.get_room_occupancy_view(list(dorm_ids), year_month)
    
    # 將 dorm_ids 轉為 tuple 才能被快取
    room_view_df = get_room_view_data(tuple(selected_dorm_ids), year_month_str)
    
    if room_view_df.empty:
        st.info("所選宿舍中沒有建立房間 (或僅有 [未分配房間])。")
    else:
        # --- 【修正 1】引入 calendar 計算月底日期 ---
        import calendar
        # 計算該月份的最後一天 (例如 2025-11-30)
        last_day = calendar.monthrange(selected_year, selected_month)[1]
        month_end_date = pd.Timestamp(datetime(selected_year, selected_month, last_day).date())

        # 依照宿舍地址和房號排序
        room_view_df.sort_values(by=['original_address', 'room_number'], inplace=True)
        
        # 確保日期欄位格式正確 (轉為 datetime 以便比較)
        if 'accommodation_end' in room_view_df.columns:
            room_view_df['accommodation_end'] = pd.to_datetime(room_view_df['accommodation_end'], errors='coerce')

        # 讀取法規標準 (預設 3.6)
        general_config = database.get_general_config()
        min_area_standard = float(general_config.get('min_area_per_person', 3.6))

        # 依照 (宿舍, 房號) 進行分組
        for (dorm_address, room_number), occupants in room_view_df.groupby(['original_address', 'room_number']):
            
            room_capacity = occupants['capacity'].iloc[0]
            # 讀取房間面積 (處理可能的空值)
            room_area = occupants['area_sq_meters'].iloc[0]
            room_area = float(room_area) if pd.notna(room_area) else 0
            
            # --- 【修正 2】修正「實際佔床」邏輯：排除月底前已離住者 ---
            # 條件 A: 有人名
            # 條件 B: 狀態不含 "掛宿外住"
            # 條件 C: (在住) OR (離住日 > 月底) --> 代表月底那天他還在

            # --- 1. 計算「掛宿外住」人數 ---
            # 使用 fillna('') 避免空值報錯，並計算包含 "掛宿外住" 的列數
            num_external = occupants['special_status'].fillna('').str.contains('掛宿外住').sum()

            # --- 2. 計算「實際佔床」人數 (排除掛宿外住 & 已搬離) ---
            def check_occupancy(row):
                if not row['worker_name']: return False # 空資料
                if "掛宿外住" in str(row['special_status']): return False # 掛宿不佔床
                
                end_date = row.get('accommodation_end') # 使用 get 避免 KeyError
                # 如果有離住日，且離住日 <= 月底，代表月底時已不在，不佔床
                if pd.notna(end_date) and end_date <= month_end_date:
                    return False
                return True

            # 計算佔床人數
            num_occupants = occupants.apply(check_occupancy, axis=1).sum()
            vacancies = room_capacity - num_occupants

            # --- 人均面積檢核邏輯 ---
            area_warning = ""
            avg_area = 0.0
            if num_occupants > 0 and room_area > 0:
                avg_area = room_area / num_occupants
                if avg_area < min_area_standard:
                    # 顯示紅色警告與實際數值
                    area_warning = f" ⚠️ 空間不足 ({avg_area:.2f} m²/人)"
            # --- 3. 組合標題字串 ---
            room_title = f"{dorm_address} - {room_number} (容量: {room_capacity}, 空床: {vacancies}){area_warning}"
            
            if vacancies == 0:
                room_title = f"🔴 {room_title} (已滿)"
            elif vacancies < 0:
                room_title = f"⚠️ {room_title} (超住?)"
            elif vacancies > 0:
                room_title = f"🟢 {room_title}"
            
            # 若有掛宿外住，標示在最後面
            if num_external > 0:
                room_title += f"，掛住: {num_external}人"

            with st.expander(room_title):
                has_data = occupants['worker_name'] != ''
                if not has_data.any():
                    st.text("此房間目前無人居住。")
                else:
                    # 取出要顯示的資料
                    occupant_details = occupants[has_data][['worker_name', 'employer_name', 'bed_number', 'special_status', 'accommodation_end']].copy()
                    
                    # --- 在表格中標記已離住者 ---
                    def format_status_display(row):
                        status = str(row['special_status']) if pd.notna(row['special_status']) else ""
                        end_date = row['accommodation_end']
                        
                        # 如果在這個月結束前離住
                        if pd.notna(end_date) and end_date <= month_end_date:
                            date_str = end_date.strftime('%m/%d')
                            return f"❌ 已於 {date_str} 搬離"
                        
                        return status

                    occupant_details['狀態/備註'] = occupant_details.apply(format_status_display, axis=1)

                    occupant_details.rename(columns={
                        'worker_name': '姓名', 
                        'employer_name': '雇主', 
                        'bed_number': '床位'
                    }, inplace=True)
                    
                    # 顯示表格 (隱藏原始日期欄位，改顯示處理過的狀態)
                    final_view = occupant_details[['姓名', '雇主', '床位', '狀態/備註']]

                    # 樣式設定：將「已搬離」的列標示為灰色文字
                    def highlight_leavers(row):
                        val = str(row['狀態/備註'])
                        if "已於" in val and "搬離" in val:
                            return ['color: #999999; font-style: italic;'] * len(row)
                        elif "掛宿外住" in val:
                            return ['color: #FFBF00; font-weight: bold;'] * len(row)
                        return [''] * len(row)

                    st.dataframe(
                        final_view.style.apply(highlight_leavers, axis=1), 
                        hide_index=True, 
                        width="stretch"
                    )
    # --- 房況總覽區塊結束 ---
    st.markdown("---")
    st.subheader(f"{year_month_str} 財務分析 (我司視角 - 彙總)")

    income_total = single_dorm_analyzer.get_income_summary(selected_dorm_ids, year_month_str)
    expense_data_df = single_dorm_analyzer.get_expense_summary(selected_dorm_ids, year_month_str)
    
    our_company_expense_df = expense_data_df[expense_data_df['費用項目'].str.contains("我司支付", na=False)]
    expense_total_our_company = int(our_company_expense_df['金額'].sum())
    
    profit_loss = income_total - expense_total_our_company

    fin_col1, fin_col2, fin_col3 = st.columns(3)
    fin_col1.metric("我司總收入 (彙總)", f"NT$ {income_total:,}", help="工人月費總和 + 其他收入")
    fin_col2.metric("我司總支出 (彙總)", f"NT$ {expense_total_our_company:,}", help="僅加總支付方為「我司」的費用項目")
    fin_col3.metric("我司淨損益 (彙總)", f"NT$ {profit_loss:,}", delta=f"{profit_loss:,}")

    # --- 【核心修改 2】重構支出細項區塊 ---
    with st.expander("點此查看支出細項 (彙總 - 含所有支付方)"):
        st.dataframe(expense_data_df.sort_values(by="金額", ascending=False), width="stretch", hide_index=True)
        
        st.markdown("---")
        st.markdown("##### 鑽研費用細節")
        
        # --- 建立快取函式 ---
        @st.cache_data
        def get_lease_details_data(dorm_ids, year_month):
            return single_dorm_analyzer.get_lease_expense_details(list(dorm_ids), year_month)
        
        @st.cache_data
        def get_utility_details_data(dorm_ids, year_month):
            return single_dorm_analyzer.get_utility_bill_details(list(dorm_ids), year_month)

        @st.cache_data
        def get_amortized_details_data(dorm_ids, year_month):
            return single_dorm_analyzer.get_amortized_expense_details(list(dorm_ids), year_month)

        @st.cache_data
        def get_meter_history(meter_id):
            return analytics_model.get_bill_history_for_meter(meter_id)
        
        # --- 篩選器 UI ---
        sel_col1, sel_col2 = st.columns(2)
        
        selected_main_category = sel_col1.selectbox(
            "步驟一：選擇費用主類別",
            options=["請選擇...", "長期合約支出", "變動雜費", "長期攤銷"],
            key="main_cat_select"
        )
        
        lease_details_df = pd.DataFrame()
        utility_details_df = pd.DataFrame()
        amortized_details_df = pd.DataFrame()
        sub_options = ["(請先選主類別)"]
        
        # --- 根據主類別載入資料並產生子類別選項 ---
        if selected_main_category == "長期合約支出":
            lease_details_df = get_lease_details_data(selected_dorm_ids, year_month_str)
            if not lease_details_df.empty:
                sub_options = ["全部"] + sorted(list(lease_details_df["合約項目"].unique()))
        
        elif selected_main_category == "變動雜費":
            utility_details_df = get_utility_details_data(selected_dorm_ids, year_month_str)
            if not utility_details_df.empty:
                sub_options = ["全部"] + sorted(list(utility_details_df["費用類型"].unique()))
        
        elif selected_main_category == "長期攤銷":
            amortized_details_df = get_amortized_details_data(selected_dorm_ids, year_month_str)
            if not amortized_details_df.empty:
                sub_options = ["全部"] + sorted(list(amortized_details_df["費用項目"].unique()))

        selected_sub_category = sel_col2.selectbox(
            "步驟二：選擇費用子項目",
            options=sub_options,
            key="sub_cat_select"
        )

        st.markdown("##### 查詢結果")

        # --- 顯示篩選後的明細表 ---
        if selected_main_category == "長期合約支出" and not lease_details_df.empty:
            df_to_show = lease_details_df
            if selected_sub_category != "全部":
                df_to_show = lease_details_df[lease_details_df["合約項目"] == selected_sub_category]
            st.dataframe(df_to_show, width="stretch", hide_index=True)

        elif selected_main_category == "變動雜費" and not utility_details_df.empty:
            df_to_show = utility_details_df
            if selected_sub_category != "全部":
                df_to_show = utility_details_df[utility_details_df["費用類型"] == selected_sub_category]
            
            st.dataframe(df_to_show.drop(columns=["meter_id"]), width="stretch", hide_index=True) # 隱藏 meter_id

            # --- 變動雜費的特殊邏輯：顯示錶號篩選器 ---
            available_meter_ids = df_to_show['meter_id'].dropna().unique()
            
            if len(available_meter_ids) > 0:
                meter_selector_options = {
                    row['meter_id']: f"{row['宿舍地址']} - {row['費用類型']} ({row['對應錶號'] or 'N/A'})"
                    for _, row in df_to_show[df_to_show['meter_id'].isin(available_meter_ids)].drop_duplicates('meter_id').iterrows()
                }
                
                if meter_selector_options:
                    st.markdown("---")
                    st.markdown("##### 鑽研單一錶號歷史")
                    selected_meter_id_for_history = st.selectbox(
                        "選擇單一錶號查看其完整歷史帳單：",
                        options=[None] + list(meter_selector_options.keys()),
                        format_func=lambda x: "請選擇..." if x is None else meter_selector_options[x]
                    )
                    
                    if selected_meter_id_for_history:
                        meter_history_df = get_meter_history(selected_meter_id_for_history)
                        if meter_history_df.empty:
                            st.info("此錶號沒有歷史帳單紀錄。")
                        else:
                            st.markdown("###### 金額趨勢圖")
                            st.line_chart(meter_history_df.set_index('帳單結束日')['帳單金額'])
                            
                            if '用量(度/噸)' in meter_history_df.columns and meter_history_df['用量(度/噸)'].notna().any():
                                st.markdown("###### 用量趨勢圖")
                                meter_history_df['用量(度/噸)'] = pd.to_numeric(meter_history_df['用量(度/噸)'], errors='coerce')
                                st.line_chart(meter_history_df[meter_history_df['用量(度/噸)'].notna()].set_index('帳單結束日')['用量(度/噸)'])
                            
                            st.dataframe(meter_history_df, width="stretch", hide_index=True)

        elif selected_main_category == "長期攤銷" and not amortized_details_df.empty:
            df_to_show = amortized_details_df
            if selected_sub_category != "全部":
                df_to_show = amortized_details_df[amortized_details_df["費用項目"] == selected_sub_category]
            st.dataframe(df_to_show, width="stretch", hide_index=True)

        elif selected_main_category != "請選擇...":
            st.info(f"在 {year_month_str} 期間，找不到「{selected_main_category}」的任何明細紀錄。")

    st.markdown("---")
    st.caption(f"基準月份：{year_month_str} (往前推算24個月)")
    
    # 【核心修改 1】傳入 year_month 參數
    @st.cache_data
    def get_trend_data(dorm_ids, year_month):
        # 這裡 year_month 是 "YYYY-MM" 格式，轉為 "YYYY-MM-01" 傳給後端
        end_date_str = f"{year_month}-01"
        return single_dorm_analyzer.get_monthly_financial_trend(list(dorm_ids), end_date_str)

    # 呼叫時帶入使用者選擇的月份
    trend_df = get_trend_data(selected_dorm_ids, year_month_str)

    if not trend_df.empty:
        chart_df = trend_df.set_index("月份")
        st.line_chart(chart_df)
        
        with st.expander("查看趨勢圖原始數據"):
            # 【核心修改 2】將表格依月份倒序排列 (最新的在上面)
            st.dataframe(trend_df.sort_values("月份", ascending=False), width="stretch", hide_index=True)
    else:
        st.info("尚無足夠的歷史資料可繪製趨勢圖。")
    
    st.markdown("---")
    st.subheader("自訂區間平均損益分析 (彙總)")
    
    c1_avg, c2_avg, c3_avg = st.columns(3)
    today_avg = datetime.now().date()
    default_start = today_avg - relativedelta(years=1)
    
    start_date = c1_avg.date_input("選擇起始日", value=default_start)
    end_date = c2_avg.date_input("選擇結束日", value=today_avg)
    
    c3_avg.write("")
    c3_avg.write("")
    if c3_avg.button("📈 計算平均損益", type="primary"):
        if start_date > end_date:
            st.error("錯誤：起始日不能晚于結束日！")
        else:
            with st.spinner("正在計算中..."):
                summary_data = single_dorm_analyzer.calculate_financial_summary_for_period(selected_dorm_ids, start_date, end_date)
            
            if summary_data:
                st.markdown(f"#### 分析結果 (彙總): {start_date} ~ {end_date}")
                m_col1, m_col2, m_col3 = st.columns(3)
                m_col1.metric("平均每月收入", f"NT$ {summary_data.get('avg_monthly_income', 0):,}")
                m_col2.metric("平均每月總支出", f"NT$ {summary_data.get('avg_monthly_expense', 0):,}")
                avg_pl = summary_data.get('avg_monthly_profit_loss', 0)
                m_col3.metric("平均每月淨損益", f"NT$ {avg_pl:,}", delta=f"{avg_pl:,}")

                st.markdown("##### 平均每月支出結構 (彙總)")
                ex_col1, ex_col2, ex_col3, ex_col4 = st.columns(4) # 多加一欄給代收代付
                ex_col1.metric("平均合約支出", f"NT$ {summary_data.get('avg_monthly_contract', 0):,}")
                ex_col2.metric("平均變動雜費", f"NT$ {summary_data.get('avg_monthly_utilities', 0):,}")
                ex_col3.metric("平均代收代付雜費", f"NT$ {summary_data.get('avg_monthly_passthrough', 0):,}")
                ex_col4.metric("平均長期攤銷", f"NT$ {summary_data.get('avg_monthly_amortized', 0):,}")
            else:
                st.warning("在此期間內查無任何財務數據可供計算。")

    st.markdown("---")
    st.subheader(f"{year_month_str} 在住人員詳細名單 (彙總)")
    
    resident_details_df = single_dorm_analyzer.get_resident_details_as_df(selected_dorm_ids, year_month_str)

    if resident_details_df.empty:
        st.info("所選宿舍於該月份沒有在住人員。")
    else:
        st.dataframe(resident_details_df, width="stretch", hide_index=True)