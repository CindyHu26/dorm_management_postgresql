import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
from data_models import report_model, dormitory_model, export_model

def to_excel(sheet_data: dict):
    """
    將一個包含多個 DataFrame 的字典寫入一個 Excel 檔案。
    """
    output = BytesIO()
    has_data_to_write = any(
        table_info.get('dataframe') is not None and not table_info.get('dataframe').empty
        for tables in sheet_data.values() for table_info in tables
    )
    if has_data_to_write:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            for sheet_name, tables in sheet_data.items():
                for table_info in tables:
                    df = table_info.get('dataframe')
                    if df is not None and not df.empty:
                        df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=table_info.get('start_row', 0))
    return output.getvalue()

def render():
    """渲染「匯出報表」頁面的所有 Streamlit UI 元件。"""
    st.header("各式報表匯出")

    # --- 1. 上傳至雲端儀表板 ---
    with st.container(border=True):
        st.subheader("更新至雲端儀表板 (Google Sheet)")
        
        # 【核心修改】將 Google Sheet 名稱定義在前端
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
                    # 【核心修改】將 gsheet_name_to_update 作為參數傳遞
                    success, message = export_model.update_google_sheet(gsheet_name_to_update, data_package)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
    st.markdown("---")

    # --- 2. 月份異動人員報表 ---
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

    # --- 3. 單一宿舍深度分析報表 ---
    with st.container(border=True):
        st.subheader("單一宿舍深度分析報表")
        st.info("選擇一個我司管理的宿舍，產生一份包含人數、國籍、性別統計與人員詳情的完整報告。")

        my_dorms = dormitory_model.get_my_company_dorms_for_selection()
        if not my_dorms:
            st.warning("目前沒有「我司管理」的宿舍可供選擇。")
        else:
            dorm_options = {d['id']: d['original_address'] for d in my_dorms}
            selected_dorm_id = st.selectbox("請選擇要匯出報表的宿舍：", options=list(dorm_options.keys()), format_func=lambda x: dorm_options.get(x))

            if st.button("🚀 產生並下載宿舍報表", key="download_dorm_report"):
                if not selected_dorm_id:
                    st.error("請先選擇一個宿舍。")
                else:
                    with st.spinner("正在產生報表..."):
                        report_df = report_model.get_dorm_report_data(selected_dorm_id)
                        
                        if report_df.empty:
                            st.warning("此宿舍目前沒有在住人員可供匯出。")
                        else:
                            nationality_counts = report_df['nationality'].dropna().value_counts().to_dict()
                            summary_items = ["總人數", "男性人數", "女性人數"] + [f"{nat}籍人數" for nat in nationality_counts.keys()]
                            summary_values = [len(report_df), len(report_df[report_df['gender'] == '男']), len(report_df[report_df['gender'] == '女'])] + list(nationality_counts.values())
                            summary_df = pd.DataFrame({"統計項目": summary_items, "數值": summary_values})
                            details_df = report_df.rename(columns={'room_number': '房號', 'worker_name': '姓名', 'employer_name': '雇主', 'gender': '性別', 'nationality': '國籍', 'monthly_fee': '房租', 'special_status': '特殊狀況', 'worker_notes': '備註'})

                            excel_file_data = {
                                "宿舍報表": [
                                    {"dataframe": summary_df, "start_row": 0},
                                    {"dataframe": details_df, "start_row": len(summary_df) + 2}
                                ]
                            }
                            excel_file = to_excel(excel_file_data)
                            
                            dorm_name_for_file = dorm_options.get(selected_dorm_id, "export").replace(" ", "_").replace("/", "_")
                            st.download_button(
                                label="✅ 報表已產生！點此下載",
                                data=excel_file,
                                file_name=f"宿舍報表_{dorm_name_for_file}.xlsx"
                            )