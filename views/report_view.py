import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from data_models import report_model, dormitory_model, export_model, employer_dashboard_model, single_dorm_analyzer

def to_excel(sheet_data: dict):
    """
    【修改版】將一個包含多個 DataFrame 的字典寫入一個 Excel 檔案。
    現在支援為每個 DataFrame 添加標題。
    """
    output = BytesIO()
    has_data_to_write = any(
        table_info.get('dataframe') is not None and not table_info.get('dataframe').empty
        for tables in sheet_data.values() for table_info in tables
    )
    
    if has_data_to_write:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            for sheet_name, tables in sheet_data.items():
                start_row_counter = 0
                for table_info in tables:
                    df = table_info.get('dataframe')
                    title = table_info.get('title')
                    
                    if df is not None and not df.empty:
                        if title:
                            pd.DataFrame([title]).to_excel(writer, index=False, header=False, sheet_name=sheet_name, startrow=start_row_counter)
                            start_row_counter += 2
                        
                        df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=start_row_counter)
                        start_row_counter += len(df) + 2
    
    return output.getvalue()


def render():
    """渲染「匯出報表」頁面的所有 Streamlit UI 元件。"""

    # with st.container(border=True):
    #     st.subheader("更新至雲端儀表板 (Google Sheet)")
    #     gsheet_name_to_update = "宿舍外部儀表板數據"
    #     st.info(f"點擊下方按鈕，系統將會查詢最新的「人員清冊」與「設備清單」，並將其上傳至 Google Sheet: **{gsheet_name_to_update}**。")
    #     if st.button("🚀 開始上傳", type="primary"):
    #         with st.spinner("正在查詢並上傳最新數據至雲端..."):
    #             worker_data = export_model.get_data_for_export()
    #             equipment_data = export_model.get_equipment_for_export()
                
    #             data_package = {}
    #             if not worker_data.empty:
    #                 data_package["人員清冊"] = worker_data
    #             if not equipment_data.empty:
    #                 data_package["設備清冊"] = equipment_data

    #             if not data_package:
    #                 st.warning("目前沒有任何人員或設備資料可供上傳。")
    #             else:
    #                 # 將 gsheet_name_to_update 作為參數傳遞
    #                 success, message = export_model.update_google_sheet(gsheet_name_to_update, data_package)
    #                 if success:
    #                     st.success(message)
    #                 else:
    #                     st.error(message)
    
    st.markdown("---")
    with st.container(border=True):
        st.subheader("年度宿舍財務總覽報表")
        st.info("選擇一個年份，系統將匯出該年度從 1月1日 至今日的各宿舍實際收支彙總表。")

        today = datetime.now()
        report_year = st.selectbox(
            "選擇報表年份", 
            options=range(today.year - 3, today.year + 1), 
            index=3,
            key="annual_financial_report_year"
        )

        if st.button("🚀 產生年度財務報表", key="generate_annual_financial_report"):
            with st.spinner(f"正在計算 {report_year} 年度的財務數據..."):
                report_df = report_model.get_annual_financial_summary_report(report_year)
            
            if report_df.empty:
                st.warning(f"在 {report_year} 年度中，找不到任何可供計算的財務數據。")
            else:
                st.success(f"報表已產生！共計算 {len(report_df)} 間宿舍的數據。請點擊下方按鈕下載。")
                excel_file = to_excel({"年度財務總覽": [{"dataframe": report_df}]})
                st.download_button(
                    label="📥 點此下載 Excel 報表",
                    data=excel_file,
                    file_name=f"年度宿舍財務總覽_{report_year}.xlsx"
                )

    with st.container(border=True):
        st.subheader("雇主月度損益報表")
        st.info("選擇月份與一位或多位雇主，系統將以『人天數』為基礎，分攤宿舍的各項收支，計算出該雇主在每個宿舍的損益情況。")

        all_employers_list = employer_dashboard_model.get_all_employers()
        
        if not all_employers_list:
            st.warning("目前資料庫中沒有任何雇主資料可供選擇。")
        else:
            pl_c1, pl_c2, pl_c3 = st.columns(3)
            
            with pl_c1:
                today_pl = datetime.now()
                default_date_pl = today_pl - relativedelta(months=2)
                default_year_pl = default_date_pl.year
                default_month_pl = default_date_pl.month
                
                year_options_pl = list(range(today_pl.year - 2, today_pl.year + 2))
                try:
                    default_year_index_pl = year_options_pl.index(default_year_pl)
                except ValueError:
                    default_year_index_pl = 2

                selected_year_pl = st.selectbox("選擇年份", options=year_options_pl, index=default_year_index_pl, key="pl_year")
                selected_month_pl = st.selectbox("選擇月份", options=range(1, 13), index=default_month_pl - 1, key="pl_month")
                year_month_str_pl = f"{selected_year_pl}-{selected_month_pl:02d}"

            with pl_c2:
                selected_employers_pl = st.multiselect("選擇雇主 (可多選)", options=all_employers_list)

            with pl_c3:
                st.write("") # 佔位
                st.write("") # 佔位
                if st.button("🚀 產生雇主損益報表", key="generate_pl_report"):
                    if not selected_employers_pl:
                        st.error("請至少選擇一位雇主！")
                    else:
                        with st.spinner(f"正在為您計算 {year_month_str_pl} 的損益報表..."):
                            report_df = report_model.get_employer_profit_loss_report(selected_employers_pl, year_month_str_pl)
                        
                        if report_df.empty:
                            st.warning("在指定月份中，找不到與所選雇主相關的任何住宿或財務紀錄。")
                        else:
                            # 建立合計列
                            total_row = report_df.sum(numeric_only=True)
                            total_row['宿舍地址'] = '---- 合計 ----'
                            total_df = pd.DataFrame(total_row).T
                            
                            final_df = pd.concat([report_df, total_df], ignore_index=True)
                            
                            # 準備 Excel 標題
                            roc_year = selected_year_pl - 1911
                            employers_str = "、".join(selected_employers_pl)
                            excel_title = f"{employers_str} 民國{roc_year}年{selected_month_pl}月"

                            excel_file_data = {
                                "雇主損益報表": [
                                    {"dataframe": final_df, "title": excel_title}
                                ]
                            }
                            excel_file = to_excel(excel_file_data)
                            
                            st.success("報表已成功產生！請點擊下方按鈕下載。")
                            st.download_button(
                                label="📥 點此下載 Excel 報表",
                                data=excel_file,
                                file_name=f"雇主損益報表_{year_month_str_pl}.xlsx"
                            )
    st.markdown("---")
    with st.container(border=True):
        st.subheader("月份異動人員報表")
        st.info("選擇一個月份，系統將匯出該月份所有「離住」以及「有特殊狀況」的人員清單。")
        today = datetime.now()
        c1, c2, c3 = st.columns([1, 1, 2])
        selected_year = c1.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2, key="exception_report_year")
        selected_month = c2.selectbox("選擇月份", options=range(1, 13), index=today.month - 1, key="exception_report_month")
        year_month_str = f"{selected_year}-{selected_month:02d}"
        download_placeholder = st.empty()
        if c3.button("🚀 產生異動報表", key="generate_exception_report"):
            with st.spinner(f"正在查詢 {year_month_str} 的異動人員資料..."):
                report_df = report_model.get_monthly_exception_report(year_month_str)
            if report_df.empty:
                st.warning("在您選擇的月份中，找不到任何離住或有特殊狀況的人員。")
            else:
                st.success(f"報表已產生！共找到 {len(report_df)} 筆紀錄。請點擊下方按鈕下載。")
                excel_file = to_excel({"異動人員清單": [{"dataframe": report_df}]})
                download_placeholder.download_button(
                    label="📥 點此下載 Excel 報表",
                    data=excel_file,
                    file_name=f"住宿特例_{year_month_str}.xlsx"
                )

    with st.container(border=True):
        st.subheader("單一宿舍深度分析報表")
        st.info("選擇一個宿舍與月份，產生包含人數、國籍、性別統計與人員詳情的完整報告。")

        my_dorms = dormitory_model.get_my_company_dorms_for_selection()
        if not my_dorms:
            st.warning("目前沒有「我司管理」的宿舍可供選擇。")
        else:
            dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}
            
            # 版面配置：宿舍 + 日期
            dc1, dc2, dc3 = st.columns(3)
            
            selected_dorm_id = dc1.selectbox(
                "選擇宿舍", 
                options=list(dorm_options.keys()), 
                format_func=lambda x: dorm_options.get(x),
                key="deep_report_dorm_select"
            )
            
            # 預設上個月
            today_deep = datetime.now()
            default_date_deep = today_deep - relativedelta(months=1)
            
            year_opts_deep = list(range(today_deep.year - 2, today_deep.year + 2))
            default_year_idx = year_opts_deep.index(default_date_deep.year) if default_date_deep.year in year_opts_deep else 2

            selected_year_deep = dc2.selectbox("年份", options=year_opts_deep, index=default_year_idx, key="deep_rep_year")
            selected_month_deep = dc3.selectbox("月份", options=range(1, 13), index=default_date_deep.month - 1, key="deep_rep_month")
            
            year_month_str_deep = f"{selected_year_deep}-{selected_month_deep:02d}"

            if st.button("🚀 產生並下載宿舍報表", key="download_dorm_report"):
                if not selected_dorm_id:
                    st.error("請先選擇一個宿舍。")
                else:
                    with st.spinner(f"正在產生 {year_month_str_deep} 的報表..."):
                        # 傳入年月
                        report_df = report_model.get_dorm_report_data(selected_dorm_id, year_month_str_deep)
                        
                        if report_df.empty:
                            st.warning(f"此宿舍在 {year_month_str_deep} 沒有在住人員紀錄。")
                        else:
                            # 製作摘要表
                            nationality_counts = report_df['國籍'].dropna().value_counts().to_dict()
                            summary_items = ["總人數", "男性人數", "女性人數"] + [f"{nat}籍人數" for nat in nationality_counts.keys()]
                            summary_values = [
                                len(report_df), 
                                len(report_df[report_df['性別'] == '男']), 
                                len(report_df[report_df['性別'] == '女'])
                            ] + list(nationality_counts.values())
                            summary_df = pd.DataFrame({"統計項目": summary_items, "數值": summary_values})

                            # 【核心修改】客製化標題：地址 人數摘要 (YYYY-MM)
                            dorm_address_str = dorm_options.get(selected_dorm_id, "").split(') ')[-1] # 取出括號後面的地址部分
                            custom_title = f"{dorm_address_str} 人數摘要 ({year_month_str_deep})"

                            excel_file_data = {
                                "宿舍報表": [
                                    {"dataframe": summary_df, "title": custom_title}, # 使用新標題
                                    {"dataframe": report_df, "title": "在住人員明細"}
                                ]
                            }
                            excel_file = to_excel(excel_file_data)
                            
                            dorm_name_for_file = dorm_address_str.replace(" ", "_").replace("/", "_")
                            st.download_button(
                                label="✅ 報表已產生！點此下載",
                                data=excel_file,
                                file_name=f"宿舍報表_{dorm_name_for_file}_{year_month_str_deep}.xlsx"
                            )

    st.markdown("---")
    with st.container(border=True):
        st.subheader("慶豐富專用-水電費分攤報表")
        st.info("請依序選擇宿舍、雇主與要搜尋的帳單日期範圍，系統將會列出所有符合條件的水電帳單供您勾選。")

        all_dorms = dormitory_model.get_dorms_for_selection()
        all_employers = employer_dashboard_model.get_all_employers()
        
        if not all_dorms or not all_employers:
            st.warning("缺少宿舍或雇主資料，無法產生報表。")
        else:
            dorm_options = {d['id']: d['original_address'] for d in all_dorms}
            
            try:
                chingfong_index = all_employers.index("慶豐富")
            except ValueError:
                chingfong_index = 0

            # --- 步驟 1: 選擇基本條件 ---
            cf_c1, cf_c2 = st.columns(2)
            selected_dorm_id_cf = cf_c1.selectbox("選擇宿舍地址", options=list(dorm_options.keys()), format_func=lambda x: dorm_options.get(x), key="cf_dorm_select")
            selected_employer_cf = cf_c2.selectbox("選擇雇主", options=all_employers, index=chingfong_index, key="cf_employer_select")
            
            # --- 將年月選擇器改為日期範圍選擇器 ---
            st.markdown("##### 請選擇要搜尋的帳單迄日範圍")
            range_c1, range_c2 = st.columns(2)
            today = datetime.now().date()
            one_year_ago = today - pd.DateOffset(years=1)
            
            bill_range_start = range_c1.date_input("起始日期", value=one_year_ago)
            bill_range_end = range_c2.date_input("結束日期", value=today)

            # --- 步驟 2: 根據條件，列出可選帳單 ---
            available_bills = []
            if bill_range_start and bill_range_end:
                if bill_range_start > bill_range_end:
                    st.error("起始日期不能晚於結束日期！")
                else:
                    available_bills = report_model.get_utility_bills_for_selection(selected_dorm_id_cf, bill_range_start, bill_range_end)
            
            selected_water_bill_ids = []
            selected_elec_bill_ids = []

            if not available_bills:
                st.warning(f"在 {bill_range_start} 至 {bill_range_end} 期間，找不到此宿舍的任何水電費帳單。")
            else:
                water_bills = [b for b in available_bills if b['bill_type'] == '水費']
                elec_bills = [b for b in available_bills if b['bill_type'] == '電費']
                
                bill_c1, bill_c2 = st.columns(2)
                
                with bill_c1:
                    if water_bills:
                        selected_water_bill_ids = st.multiselect(
                            "請勾選要納入計算的水費帳單：",
                            options=[b['id'] for b in water_bills],
                            format_func=lambda x: f"迄日:{[b['bill_end_date'] for b in water_bills if b['id'] == x][0]}, 金額:{[b['amount'] for b in water_bills if b['id'] == x][0]:,}",
                            default=[b['id'] for b in water_bills]
                        )
                    else:
                        st.info("在此日期範圍內無水費帳單。")
                
                with bill_c2:
                    if elec_bills:
                        selected_elec_bill_ids = st.multiselect(
                            "請勾選要納入計算的電費帳單：",
                            options=[b['id'] for b in elec_bills],
                            format_func=lambda x: f"迄日:{[b['bill_end_date'] for b in elec_bills if b['id'] == x][0]}, 金額:{[b['amount'] for b in elec_bills if b['id'] == x][0]:,}",
                            default=[b['id'] for b in elec_bills]
                        )
                    else:
                        st.info("在此日期範圍內無電費帳單。")

            # --- 步驟 3: 產生報表 ---
            if st.button("🚀 產生慶豐富水電報表", key="generate_cf_report"):
                selected_bill_ids = selected_water_bill_ids + selected_elec_bill_ids

                if not selected_dorm_id_cf or not selected_employer_cf:
                    st.error("請務必選擇宿舍和雇主！")
                elif not selected_bill_ids:
                    st.error("請至少勾選一筆水費或電費帳單！")
                else:
                    with st.spinner(f"正在為 {selected_employer_cf} 產生報表..."):
                        dorm_details, bills_df, details_df = report_model.get_custom_utility_report_data(
                            selected_dorm_id_cf, selected_employer_cf, selected_bill_ids
                        )

                    if bills_df is None or details_df is None:
                        st.error("產生報表時發生錯誤，請檢查後台日誌。")
                    elif bills_df.empty:
                        st.warning("在您勾選的帳單中，找不到資料可供計算。")
                    elif details_df.empty:
                        st.warning("在您勾選的帳單期間內，找不到此雇主的任何在住人員。")
                    else:
                        summary_header_df = pd.DataFrame({
                            "宿舍名稱": [dorm_details['dorm_name'] or dorm_details['original_address']],
                            "人數": [details_df.shape[0]]
                        })

                        bill_summary_df = bills_df.copy()
                        bill_summary_df.rename(columns={
                            'bill_type': '帳單', 'bill_start_date': '起日', 'bill_end_date': '迄日', 'amount': '費用'
                        }, inplace=True)
                        
                        bill_summary_df['天數'] = (pd.to_datetime(bill_summary_df['迄日']) - pd.to_datetime(bill_summary_df['起日'])).dt.days + 1
                        
                        # 1. 取得基礎欄位
                        final_details_df_base = details_df[['離住日期', '姓名', '入住日期', '母語姓名']].copy()

                        # 2. 初始化列表以收集所有新欄位
                        new_cols_to_add = []
                        # 初始化費用欄位清單 (用於最後的總電費計算)
                        water_bill_cols, elec_bill_cols = [], []
                        water_bill_counter = 1
                        elec_bill_counter = 1

                        # 建立一個臨時 DataFrame，用於儲存所有費用 Series
                        intermediate_fees_days = []

                        for _, bill in bills_df.iterrows():
                            bill_col_name = f"{bill['bill_type']}_{bill['bill_id']}"
                            
                            if bill['bill_type'] == '水費':
                                days_col_name = f"水繳費單{water_bill_counter} 居住日期"
                                fee_col_name = f"水費{water_bill_counter}"
                                water_bill_cols.append(fee_col_name)
                                water_bill_counter += 1
                            else:
                                days_col_name = f"電繳費單{elec_bill_counter} 居住日期"
                                fee_col_name = f"電費{elec_bill_counter}"
                                elec_bill_cols.append(fee_col_name)
                                elec_bill_counter += 1
                            
                            # 3. 命名新的 Series 並將其加入列表
                            
                            # 居住天數 (Days column)
                            days_series = details_df[f"{bill_col_name}_days"].rename(days_col_name)
                            intermediate_fees_days.append(days_series)
                            
                            # 費用金額 (Fee column)
                            fee_series = details_df[f"{bill_col_name}_fee"].round(2).rename(fee_col_name)
                            intermediate_fees_days.append(fee_series)


                        # 4. 計算總電費 (Series)
                        if intermediate_fees_days:
                            # 暫時合併所有中間欄位，以便計算總和
                            intermediate_df = pd.concat(intermediate_fees_days, axis=1)
                            
                            if elec_bill_cols:
                                # 計算總和，並將其作為一個 Series 加入列表
                                total_elec_fee_series = intermediate_df[elec_bill_cols].sum(axis=1).round(2).rename('總電費')
                                intermediate_fees_days.append(total_elec_fee_series)
                                
                            # 5. 一次性合併所有欄位
                            final_details_df = pd.concat([final_details_df_base] + intermediate_fees_days, axis=1)

                        else:
                            final_details_df = final_details_df_base.copy()
                            # 如果沒有任何費用，也要初始化總電費欄位 (避免後續代碼錯誤)
                            if elec_bill_cols:
                                final_details_df['總電費'] = 0.0

                        # 5. 最後的總電費計算 (保持不變，但作用在新的 final_details_df 上)
                        if elec_bill_cols:
                            final_details_df['總電費'] = final_details_df[elec_bill_cols].sum(axis=1).round(2)
                        
                        if elec_bill_cols:
                            final_details_df['總電費'] = final_details_df[elec_bill_cols].sum(axis=1).round(2)

                        excel_file_data = {
                            "水電費分攤報表": [
                                {"dataframe": summary_header_df, "title": ""},
                                {"dataframe": bill_summary_df[['帳單', '起日', '迄日', '天數', '費用']], "title": "帳單摘要"},
                                {"dataframe": final_details_df, "title": "費用分攤明細"}
                            ]
                        }

                        excel_file = to_excel(excel_file_data)
                        
                        st.success("報表已成功產生！請點擊下方按鈕下載。")
                        st.download_button(
                            label="📥 點此下載 Excel 報表",
                            data=excel_file,
                            file_name=f"{selected_employer_cf}_水電費報表_{bill_range_end}.xlsx"
                        )

    st.markdown("---")
    # --- 區塊 7: 超額水電費分攤報表 (新制) ---
    if 'selected_employer_names_ex' not in st.session_state:
         st.session_state.selected_employer_names_ex = []
         
    with st.container(border=True):
        st.subheader("💧 超額水電費分攤報表 (新制)")
        st.info("此報表計算：每人先收固定費用，若總帳單超額，則超額部分由所有在住者按居住天數平均分攤，並彙總給指定雇主請款。支援多宿舍、多雇主請款。")

        all_dorms = dormitory_model.get_dorms_for_selection()
        
        if not all_dorms:
            st.warning("缺少宿舍資料，無法產生報表。")
        else:
            dorm_options = {d['id']: d['original_address'] for d in all_dorms}
            all_dorm_ids = list(dorm_options.keys())
            
            # --- 步驟 1: 選擇基本條件 ---
            col_dorm, col_subsidy = st.columns([0.7, 0.3])
            
            # 宿舍地址多選
            selected_dorm_ids_ex = col_dorm.multiselect(
                "選擇宿舍地址 (可多選)*", 
                options=all_dorm_ids, 
                format_func=lambda x: dorm_options.get(x),
                default=None, 
                key="ex_dorm_select"
            )
            
            # 固定補助金額輸入
            fixed_subsidy_amount = col_subsidy.number_input(
                "每人每月補助金額 (元/月)", 
                min_value=0, 
                value=300, 
                step=10, 
                help="此金額為收費基準，超額部分將被平均分攤。",
                key="ex_subsidy_input"
            )

            # --- 日期範圍選擇器 ---
            st.markdown("##### 請選擇要搜尋的帳單迄日範圍")
            range_c1, range_c2 = st.columns(2)
            today = datetime.now().date()
            one_year_ago = today - relativedelta(years=1)
            
            bill_range_start_ex = range_c1.date_input("起始日期", value=one_year_ago, key="ex_bill_start")
            bill_range_end_ex = range_c2.date_input("結束日期", value=today, key="ex_bill_end")
            
            # 額外新增勾選框
            include_external_workers = st.checkbox(
                "✅ 將「掛宿外住」人員納入水電費分攤計算",
                value=False,
                help="如果勾選，在分攤超額水電費時，特殊狀況為『掛宿外住』的人員也會被計算在總人天數內。"
            )

            # 初始化變數
            available_bills_ex = []
            relevant_employers = []
            
            # --- 修正 1: 動態獲取雇主列表 ---
            if selected_dorm_ids_ex and bill_range_start_ex and bill_range_end_ex:
                if bill_range_start_ex <= bill_range_end_ex:
                    relevant_employers = report_model.get_employers_in_dorms_for_period(
                        selected_dorm_ids_ex, 
                        bill_range_start_ex, 
                        bill_range_end_ex
                    )

            # --- 步驟 2: 選擇目標雇主 ---
            if relevant_employers:
                # 修正 2: 這裡使用 Session State 來儲存 selected_employer_names_ex
                st.session_state.selected_employer_names_ex = st.multiselect(
                    f"選擇目標雇主 (共 {len(relevant_employers)} 位)", 
                    options=relevant_employers, 
                    default=relevant_employers, # 預設全選
                    key="ex_employer_select_multi" 
                )
            elif selected_dorm_ids_ex:
                 st.info("在所選宿舍與日期範圍內，沒有找到任何有居住者的雇主資料。")
            else:
                 st.info("請先從上方選擇「宿舍地址」與「帳單日期範圍」，以載入相關雇主。")


            # --- 步驟 3: 勾選要納入計算的帳單 (只有在有選雇主時才顯示) ---
            # 從 Session State 獲取最終的雇主勾選結果
            final_selected_employers = st.session_state.get("ex_employer_select_multi", []) 

            if final_selected_employers and selected_dorm_ids_ex and bill_range_start_ex and bill_range_end_ex:
                
                # 獲取可選帳單
                available_bills_ex = report_model.get_utility_bills_for_selection(selected_dorm_ids_ex, bill_range_start_ex, bill_range_end_ex)

                water_bills_ex = [b for b in available_bills_ex if b['bill_type'] == '水費']
                elec_bills_ex = [b for b in available_bills_ex if b['bill_type'] == '電費']
                
                selected_water_bill_ids_ex = [] # 初始化
                selected_elec_bill_ids_ex = [] # 初始化
                
                if available_bills_ex:
                    st.markdown("##### 選擇要納入計算的帳單")
                    bill_c1, bill_c2 = st.columns(2)
                    
                    with bill_c1:
                        if water_bills_ex:
                            default_water_ids = [b['id'] for b in water_bills_ex]
                            selected_water_bill_ids_ex = st.multiselect(
                                "請勾選水費帳單：",
                                options=default_water_ids,
                                # 顯示宿舍地址在帳單名稱中
                                format_func=lambda x: f"{dorm_options.get([b['dorm_id'] for b in available_bills_ex if b['id'] == x][0])} 迄日:{[b['bill_end_date'] for b in water_bills_ex if b['id'] == x][0]}, 金額:{[b['amount'] for b in water_bills_ex if b['id'] == x][0]:,}",
                                default=default_water_ids,
                                key="ex_water_bills"
                            )
                        else: pass

                    with bill_c2:
                        if elec_bills_ex:
                            default_elec_ids = [b['id'] for b in elec_bills_ex]
                            selected_elec_bill_ids_ex = st.multiselect(
                                "請勾選電費帳單：",
                                options=default_elec_ids,
                                # 顯示宿舍地址在帳單名稱中
                                format_func=lambda x: f"{dorm_options.get([b['dorm_id'] for b in available_bills_ex if b['id'] == x][0])} 迄日:{[b['bill_end_date'] for b in elec_bills_ex if b['id'] == x][0]}, 金額:{[b['amount'] for b in elec_bills_ex if b['id'] == x][0]:,}",
                                default=default_elec_ids,
                                key="ex_elec_bills"
                            )
                        else: pass
                else:
                    st.warning("在所選條件下沒有找到任何水費或電費帳單。")
            else:
                 selected_water_bill_ids_ex = []
                 selected_elec_bill_ids_ex = []


            selected_bill_ids_ex = selected_water_bill_ids_ex + selected_elec_bill_ids_ex

            st.markdown("---")
            # 【新增】計算模式選擇
            calc_mode_option = st.radio(
                "選擇計算模式：",
                options=["依帳單計費 (以帳單起迄為準，完整分攤)", "依日期區間計費 (以搜尋區間為準，嚴格切斷)"],
                index=0,
                help="""
                - **依帳單計費**：無論您搜尋的日期為何，系統會將您勾選的帳單金額「全額」納入計算，並向該帳單期間內的所有住戶收費。
                - **依日期區間計費**：系統只計算您上方設定的「起始日期」到「結束日期」這段期間的費用與人頭。若帳單跨出此範圍，金額會按天數比例縮減。
                """
            )
            
            # 將選項轉換為後端參數代碼
            calc_mode_code = 'bill' if "依帳單" in calc_mode_option else 'date_range'

            # --- 步驟 4: 產生報表 ---
            if st.button("🚀 產生超額水電費分攤報表", type="primary", key="generate_ex_report"):
                if not selected_dorm_ids_ex:
                    st.error("請至少選擇一間宿舍！")
                elif not final_selected_employers:
                    st.error("請至少選擇一個雇主！")
                elif not selected_bill_ids_ex:
                    st.error("請至少勾選一筆水費或電費帳單！")
                else:
                    with st.spinner(f"正在為 {len(final_selected_employers)} 個雇主產生報表..."):
                        # 呼叫後端 (傳入 calc_mode_code)
                        dorm_address_list, bills_df, details_df, total_charge, total_excess = report_model.get_excess_utility_report_data(
                            selected_dorm_ids_ex, 
                            final_selected_employers, 
                            selected_bill_ids_ex,
                            fixed_subsidy_amount,
                            include_external_workers,
                            calculation_mode=calc_mode_code, # 傳入模式
                            report_start_date=bill_range_start_ex,
                            report_end_date=bill_range_end_ex
                        )

                    if dorm_address_list is None or details_df is None:
                        st.error("產生報表時發生錯誤，請檢查後台日誌。")
                    elif bills_df.empty:
                        st.warning("在您勾選的帳單中，找不到資料可供計算。")
                    elif details_df.empty:
                        st.warning("在您勾選的帳單期間內，找不到目標雇主的任何在住人員。")
                    else:
                        # --- 【新增】判斷是否超額 ---
                        if total_excess <= 0:
                            # 情況 A：沒超過，顯示提示，不產出報表
                            st.info(f"ℹ️ **計算結果：未達超額標準**")
                            st.markdown(f"""
                            * 帳單總金額：**NT$ {int(bills_df['amount'].sum()):,}**
                            * 預期基本收費總額：**NT$ {int(bills_df['amount'].sum() - total_excess):,}** (依人頭/天數計算)
                            * **結論**：總費用在基本額度內，無須額外分攤超額費用，**不需印製報表**。
                            """)
                        else:
                            # 情況 B：超過了，才執行原本的 Excel 產生與下載邏輯
                            
                            # 報表標題調整為多地址/多雇主
                            dorm_title = " / ".join(dorm_address_list) 
                            employer_title = " / ".join(final_selected_employers)
                            
                            # 準備 Excel 數據
                            summary_header_df = pd.DataFrame({
                                "宿舍地址": [dorm_title],
                                "目標雇主": [employer_title],
                                "總水電費": [f"NT$ {int(total_charge):,}"],
                                "計算基準 (元/月)": [fixed_subsidy_amount],
                                "總人數": [details_df.shape[0]],
                            })

                            bill_summary_df = bills_df.copy()
                            bill_summary_df.rename(columns={
                                'bill_type': '帳單', 'bill_start_date': '起日', 'bill_end_date': '迄日', 'amount': '費用'
                            }, inplace=True)
                            bill_summary_df['天數'] = (pd.to_datetime(bill_summary_df['迄日']) - pd.to_datetime(bill_summary_df['起日'])).dt.days + 1
                            
                            
                            final_details_df = details_df[['雇主', '姓名', '英文姓名', '護照號碼', '國籍', '性別', '入住日期', '離住日期', '居住天數', '應收水電費']].copy()
                            
                            final_details_df['應收水電費'] = final_details_df['應收水電費'].round().astype(int)

                            excel_file_data = {
                                "超額水電費報表": [
                                    {"dataframe": summary_header_df, "title": "【超額水電費請款單】"},
                                    {"dataframe": bill_summary_df[['帳單', '起日', '迄日', '天數', '費用']], "title": "帳單摘要"},
                                    {"dataframe": final_details_df, "title": "應收費用明細"}
                                ]
                            }

                            excel_file = to_excel(excel_file_data)
                            
                            st.success(f"報表已成功產生！總水電費為 NT$ {int(total_charge):,}")
                            
                            file_name_prefix = employer_title.replace(" ", "_").replace("/", "_")
                            st.download_button(
                                label="📥 點此下載 Excel 報表",
                                data=excel_file,
                                file_name=f"{file_name_prefix}_超額水電費報表_{bill_range_end_ex}.xlsx"
                            )

    st.markdown("---")
    with st.container(border=True):
        st.subheader("🛏️ 房間床位佔用總覽報表")
        st.info("匯出指定宿舍的床位矩陣報表，可直觀查看哪個床位（或潛在床位）目前住著誰，哪些是空床。")
        
        # 載入我司管理宿舍列表
        my_dorms = dormitory_model.get_my_company_dorms_for_selection()
        if not my_dorms:
            st.warning("目前沒有「我司管理」的宿舍可供選擇。")
        else:
            dorm_options = {d['id']: f"({d.get('legacy_dorm_code') or '無編號'}) {d.get('original_address', '')}" for d in my_dorms}
            
            # 宿舍選擇
            selected_dorm_id_bed = st.selectbox(
                "選擇要分析的宿舍", 
                options=list(dorm_options.keys()), 
                format_func=lambda x: dorm_options.get(x),
                key="bed_occupancy_dorm_select"
            )

            if st.button("🚀 產生床位佔用報表", key="generate_bed_occupancy_report"):
                if not selected_dorm_id_bed:
                    st.error("請先選擇一個宿舍。")
                else:
                    with st.spinner(f"正在產生床位佔用矩陣..."):
                        # 呼叫新的後端函式
                        from data_models import single_dorm_analyzer
                        dorm_address, occupancy_df = single_dorm_analyzer.get_bed_occupancy_report(selected_dorm_id_bed)
                    
                    if dorm_address is None:
                         st.error("找不到該宿舍紀錄或資料庫連線失敗。")
                    elif occupancy_df.empty:
                         st.warning(f"宿舍 {dorm_address} 目前沒有任何房間或在住人員紀錄。")
                    else:
                        st.success(f"床位佔用報表已產生！請點擊下方按鈕下載。")
                        
                        # 準備 Excel 數據
                        excel_title = f"{dorm_address} 床位佔用總覽"
                        
                        excel_file_data = {
                            "床位佔用報表": [
                                {"dataframe": occupancy_df, "title": excel_title}
                            ]
                        }
                        excel_file = to_excel(excel_file_data)
                        
                        dorm_name_for_file = dorm_address.replace(" ", "_").replace("/", "_")
                        st.download_button(
                            label="📥 點此下載 Excel 床位佔用報表",
                            data=excel_file,
                            file_name=f"床位佔用報表_{dorm_name_for_file}_{date.today().strftime('%Y%m%d')}.xlsx"
                        )