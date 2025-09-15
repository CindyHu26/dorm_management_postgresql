import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
from data_models import report_model, dormitory_model, export_model, employer_dashboard_model

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
    st.header("各式報表匯出")

    with st.container(border=True):
        st.subheader("更新至雲端儀表板 (Google Sheet)")
        gsheet_name_to_update = "宿舍外部儀表板數據"
        st.info(f"點擊下方按鈕，系統將會查詢最新的「人員清冊」與「設備清單」，並將其上傳至 Google Sheet: **{gsheet_name_to_update}**。")
        if st.button("🚀 開始上傳", type="primary"):
            with st.spinner("正在查詢並上傳最新數據至雲端..."):
                worker_data = export_model.get_data_for_export()
                equipment_data = export_model.get_equipment_for_export()
                
                data_package = {}
                if not worker_data.empty:
                    data_package["人員清冊"] = worker_data
                if not equipment_data.empty:
                    data_package["設備清冊"] = equipment_data

                if not data_package:
                    st.warning("目前沒有任何人員或設備資料可供上傳。")
                else:
                    # 將 gsheet_name_to_update 作為參數傳遞
                    success, message = export_model.update_google_sheet(gsheet_name_to_update, data_package)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
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
                selected_year_pl = st.selectbox("選擇年份", options=range(today_pl.year - 2, today_pl.year + 2), index=2, key="pl_year")
                selected_month_pl = st.selectbox("選擇月份", options=range(1, 13), index=today_pl.month - 1, key="pl_month")
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
            st.info("選擇一個我司管理的宿舍，產生一份包含人數、國籍、性別統計與人員詳情的完整報告。")

            my_dorms = dormitory_model.get_my_company_dorms_for_selection()
            if not my_dorms:
                st.warning("目前沒有「我司管理」的宿舍可供選擇。")
            else:
                dorm_options = {d['id']: d['original_address'] for d in my_dorms}
                selected_dorm_id = st.selectbox(
                    "請選擇要匯出報表的宿舍：", 
                    options=list(dorm_options.keys()), 
                    format_func=lambda x: dorm_options.get(x),
                    key="deep_report_dorm_select"
                )

                if st.button("🚀 產生並下載宿舍報表", key="download_dorm_report"):
                    if not selected_dorm_id:
                        st.error("請先選擇一個宿舍。")
                    else:
                        with st.spinner("正在產生報表..."):
                            # 呼叫後端函式獲取資料
                            report_df = report_model.get_dorm_report_data(selected_dorm_id)
                            
                            if report_df.empty:
                                st.warning("此宿舍目前沒有在住人員可供匯出。")
                            else:
                                # 1. 產生摘要 DataFrame
                                nationality_counts = report_df['nationality'].dropna().value_counts().to_dict()
                                summary_items = ["總人數", "男性人數", "女性人數"] + [f"{nat}籍人數" for nat in nationality_counts.keys()]
                                summary_values = [
                                    len(report_df), 
                                    len(report_df[report_df['gender'] == '男']), 
                                    len(report_df[report_df['gender'] == '女'])
                                ] + list(nationality_counts.values())
                                summary_df = pd.DataFrame({"統計項目": summary_items, "數值": summary_values})

                                # 2. 產生明細 DataFrame 並重新命名欄位
                                details_df = report_df.rename(columns={
                                    'room_number': '房號', 
                                    'worker_name': '姓名', 
                                    'employer_name': '雇主', 
                                    'gender': '性別', 
                                    'nationality': '國籍', 
                                    'monthly_fee': '房租', 
                                    'special_status': '特殊狀況', 
                                    'worker_notes': '備註'
                                })

                                # 3. 準備寫入 Excel 的資料結構
                                excel_file_data = {
                                    "宿舍報表": [
                                        {"dataframe": summary_df, "title": "宿舍人數摘要"},
                                        {"dataframe": details_df, "title": "在住人員明細"}
                                    ]
                                }
                                excel_file = to_excel(excel_file_data)
                                
                                # 4. 提供下載按鈕
                                dorm_name_for_file = dorm_options.get(selected_dorm_id, "export").replace(" ", "_").replace("/", "_")
                                st.download_button(
                                    label="✅ 報表已產生！點此下載",
                                    data=excel_file,
                                    file_name=f"宿舍報表_{dorm_name_for_file}.xlsx"
                                )

    st.markdown("---")
    with st.container(border=True):
        st.subheader("慶豐富專用-水電費分攤報表")
        st.info("請選擇宿舍、雇主與月份，產生指定格式的水電費分攤明細。")

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

            cf_c1, cf_c2, cf_c3 = st.columns(3)
            selected_dorm_id_cf = cf_c1.selectbox("選擇宿舍地址", options=list(dorm_options.keys()), format_func=lambda x: dorm_options.get(x), key="cf_dorm_select")
            selected_employer_cf = cf_c2.selectbox("選擇雇主", options=all_employers, index=chingfong_index, key="cf_employer_select")
            
            today_cf = datetime.now()
            year_month_str_cf = f"{today_cf.year}-{today_cf.month:02d}"
            
            with cf_c3:
                selected_year_cf = st.selectbox("選擇年份", options=range(today_cf.year - 2, today_cf.year + 2), index=2, key="cf_year")
                selected_month_cf = st.selectbox("選擇月份", options=range(1, 13), index=today_cf.month - 1, key="cf_month")
                year_month_str_cf = f"{selected_year_cf}-{selected_month_cf:02d}"

            if st.button("🚀 產生慶豐富水電報表", key="generate_cf_report"):
                if not selected_dorm_id_cf or not selected_employer_cf:
                    st.error("請務必選擇宿舍和雇主！")
                else:
                    with st.spinner(f"正在為 {selected_employer_cf} 產生 {year_month_str_cf} 的報表..."):
                        dorm_details, bills_df, details_df = report_model.get_custom_utility_report_data(
                            selected_dorm_id_cf, selected_employer_cf, year_month_str_cf
                        )

                    if bills_df is None or details_df is None:
                        st.error("產生報表時發生錯誤，請檢查後台日誌。")
                    elif bills_df.empty:
                        st.warning("在指定月份中，找不到此宿舍的任何水電費帳單。")
                    elif details_df.empty:
                        st.warning("在指定帳單期間內，找不到此雇主的任何在住人員。")
                    else:
                        summary_header_df = pd.DataFrame({
                            "宿舍名稱": [dorm_details['dorm_name'] or dorm_details['original_address']],
                            "人數": [details_df.shape[0]]
                        })

                        bill_summary_df = bills_df.copy()
                        bill_summary_df.rename(columns={
                            'bill_type': '帳單', 'bill_start_date': '起日', 'bill_end_date': '迄日', 'amount': '費用'
                        }, inplace=True)
                        
                        # --- : 統一天數計算方式 ---
                        bill_summary_df['天數'] = (pd.to_datetime(bill_summary_df['迄日']) - pd.to_datetime(bill_summary_df['起日'])).dt.days + 1
                        
                        final_details_df = details_df[['離住日期', '姓名', '入住日期', '母語姓名']].copy()
                        
                        water_bill_cols, elec_bill_cols = [], []
                        water_bill_counter = 1
                        elec_bill_counter = 1
                        
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
                            
                            final_details_df[days_col_name] = details_df[f"{bill_col_name}_days"]
                            final_details_df[fee_col_name] = details_df[f"{bill_col_name}_fee"].round(2)
                        
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
                            file_name=f"{selected_employer_cf}_水電費報表_{year_month_str_cf}.xlsx"
                        )