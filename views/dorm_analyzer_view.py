import streamlit as st
import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
from data_models import dormitory_model, single_dorm_analyzer

def render():
    """渲染「宿舍深度分析」頁面"""
    st.header("宿舍深度分析儀表板")

    # --- 1. 宿舍選擇 ---
    my_dorms = dormitory_model.get_my_company_dorms_for_selection()
    if not my_dorms:
        st.warning("目前沒有「我司管理」的宿舍可供分析。")
        return

    dorm_options = {d['id']: d['original_address'] for d in my_dorms}
    selected_dorm_id = st.selectbox(
        "請選擇要分析的宿舍：",
        options=list(dorm_options.keys()),
        format_func=lambda x: dorm_options.get(x, "未知宿舍")
    )

    if not selected_dorm_id: return
    st.markdown("---")

    # --- 2. 顯示基本資訊 ---
    basic_info = single_dorm_analyzer.get_dorm_basic_info(selected_dorm_id)
    meters_df = single_dorm_analyzer.get_dorm_meters(selected_dorm_id)

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
            
    st.markdown("---")

    # --- 3. 數據分析區塊 ---
    st.subheader("數據分析")
    
    today = datetime.now()
    sc1, sc2 = st.columns(2)
    selected_year = sc1.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2)
    selected_month = sc2.selectbox("選擇月份", options=range(1, 13), index=today.month - 1)
    year_month_str = f"{selected_year}-{selected_month:02d}"

    resident_data = single_dorm_analyzer.get_resident_summary(selected_dorm_id, year_month_str)
    
    st.markdown(f"#### {year_month_str} 住宿人員分析")
    st.metric("總在住人數", f"{resident_data['total_residents']} 人")

    res_c1, res_c2, res_c3 = st.columns(3)
    with res_c1:
        st.markdown("**性別分佈**")
        st.dataframe(resident_data['gender_counts'],  width="stretch", hide_index=True)
    with res_c2:
        st.markdown("**國籍分佈**")
        st.dataframe(resident_data['nationality_counts'],  width="stretch", hide_index=True)
    with res_c3:
        st.markdown("**房租簡表**")
        st.dataframe(resident_data['rent_summary'],  width="stretch", hide_index=True)

    st.subheader(f"{year_month_str} 宿舍營運分析")
    analysis_data = single_dorm_analyzer.get_dorm_analysis_data(selected_dorm_id, year_month_str)
    if not analysis_data:
        st.error("分析數據時發生錯誤，請檢查資料庫連線。")
    else:
        st.markdown("##### Ａ. 宿舍容量與概況")
        st.metric("宿舍總床位容量", f"{analysis_data['total_capacity']} 床")
        st.markdown("##### Ｂ. 當月實際住宿分析")
        ar, er, ab = analysis_data['actual_residents'], analysis_data['external_residents'], analysis_data['available_beds']
        b_col1, b_col2, b_col3 = st.columns(3)
        b_col1.metric("目前實際住宿人數", f"{ar['total']} 人", help="計算方式：所有住在該宿舍的人員，扣除『掛宿外住』者。")
        b_col2.metric("掛宿外住人數", f"{er['total']} 人", help="計算方式：統計特殊狀況為『掛宿外住』的人員總數。")
        b_col3.metric("一般可住空床數", f"{ab['total']} 床", help="計算方式：[總容量] - [實際住宿人數] - [特殊房間獨立空床數]。代表可自由安排的床位。")
        st.markdown(f"**實際住宿性別比**：男 {ar['male']} 人 / 女 {ar['female']} 人")
        st.markdown(f"**掛宿外住性別比**：男 {er['male']} 人 / 女 {er['female']} 人")
        st.markdown("##### Ｃ. 特殊房間註記與獨立空床")
        special_rooms_df = analysis_data['special_rooms']
        if special_rooms_df.empty:
            st.info("此宿舍沒有任何註記特殊備註的房間。")
        else:
            st.warning("注意：下方所列房間的空床位『不』計入上方的一般可住空床數，需獨立評估安排。")
            st.dataframe(
                special_rooms_df[['room_number', 'room_notes', 'capacity', '目前住的人數', '獨立空床數']],
                 width="stretch", hide_index=True
            )
            
    st.markdown("---")

    st.subheader(f"{year_month_str} 財務分析 (我司視角)")

    income_total = single_dorm_analyzer.get_income_summary(selected_dorm_id, year_month_str)
    expense_data_df = single_dorm_analyzer.get_expense_summary(selected_dorm_id, year_month_str)
    
    # 只計算「我司支付」的費用
    our_company_expense_df = expense_data_df[expense_data_df['費用項目'].str.contains("我司支付", na=False)]
    expense_total_our_company = int(our_company_expense_df['金額'].sum())
    
    profit_loss = income_total - expense_total_our_company

    # 更新指標卡標題與數值
    fin_col1, fin_col2, fin_col3 = st.columns(3)
    fin_col1.metric("我司預估總收入", f"NT$ {income_total:,}", help="工人月費總和 + 其他收入")
    fin_col2.metric("我司預估總支出", f"NT$ {expense_total_our_company:,}", help="僅加總支付方為「我司」的費用項目")
    fin_col3.metric("我司預估淨損益", f"NT$ {profit_loss:,}", delta=f"{profit_loss:,}")

    # 展開區塊顯示所有支付方的明細
    with st.expander("點此查看支出細項 (含所有支付方)"):
        st.dataframe(expense_data_df, width="stretch", hide_index=True)

    st.markdown("---")
    st.subheader("歷史財務趨勢 (近24個月)")
    
    @st.cache_data
    def get_trend_data(dorm_id):
        return single_dorm_analyzer.get_monthly_financial_trend(dorm_id)

    trend_df = get_trend_data(selected_dorm_id)
    if not trend_df.empty:
        chart_df = trend_df.set_index("月份")
        st.line_chart(chart_df)
        with st.expander("查看趨勢圖原始數據"):
            st.dataframe(trend_df, width="stretch", hide_index=True)
    else:
        st.info("尚無足夠的歷史資料可繪製趨勢圖。")
    
    # --- 自訂區間平均分析 ---
    st.markdown("---")
    st.subheader("自訂區間平均損益分析")
    
    c1_avg, c2_avg, c3_avg = st.columns(3)
    today = datetime.now().date()
    default_start = today - relativedelta(years=1)
    
    start_date = c1_avg.date_input("選擇起始日", value=default_start)
    end_date = c2_avg.date_input("選擇結束日", value=today)
    
    c3_avg.write("")
    c3_avg.write("")
    if c3_avg.button("📈 計算平均損益", type="primary"):
        if start_date > end_date:
            st.error("錯誤：起始日不能晚于結束日！")
        else:
            with st.spinner("正在計算中..."):
                summary_data = single_dorm_analyzer.calculate_financial_summary_for_period(selected_dorm_id, start_date, end_date)
            
            if summary_data:
                st.markdown(f"#### 分析結果: {start_date} ~ {end_date}")
                
                # 主要指標
                m_col1, m_col2, m_col3 = st.columns(3)
                m_col1.metric("平均每月收入", f"NT$ {summary_data.get('avg_monthly_income', 0):,}")
                m_col2.metric("平均每月總支出", f"NT$ {summary_data.get('avg_monthly_expense', 0):,}")
                avg_pl = summary_data.get('avg_monthly_profit_loss', 0)
                m_col3.metric("平均每月淨損益", f"NT$ {avg_pl:,}", delta=f"{avg_pl:,}")

                st.markdown("##### 平均每月支出結構")
                # 支出細項
                ex_col1, ex_col2, ex_col3 = st.columns(3)
                ex_col1.metric("平均月租支出", f"NT$ {summary_data.get('avg_monthly_rent', 0):,}")
                ex_col2.metric("平均變動雜費", f"NT$ {summary_data.get('avg_monthly_utilities', 0):,}")
                ex_col3.metric("平均長期攤銷", f"NT$ {summary_data.get('avg_monthly_amortized', 0):,}")

            else:
                st.warning("在此期間內查無任何財務數據可供計算。")

    st.markdown("---")
    st.subheader(f"{year_month_str} 在住人員詳細名單")
    
    resident_details_df = single_dorm_analyzer.get_resident_details_as_df(selected_dorm_id, year_month_str)

    if resident_details_df.empty:
        st.info("此宿舍於該月份沒有在住人員。")
    else:
        st.dataframe(resident_details_df, width="stretch", hide_index=True)