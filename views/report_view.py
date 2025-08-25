import streamlit as st
import pandas as pd
from io import BytesIO
from datetime import datetime
from data_models import report_model, dormitory_model, worker_model, export_model

def to_excel(sheet_data: dict):
    """
    將一個包含多個 DataFrame 的字典寫入一個 Excel 檔案。
    支援在同一個工作表 (sheet) 中，從不同起始行 (start_row) 寫入多個表格。
    """
    output = BytesIO()
    
    # 步驟一：檢查是否有任何實際的資料需要寫入
    has_data_to_write = False
    for sheet_name, tables in sheet_data.items():
        for table_info in tables:
            df = table_info.get('dataframe')
            if df is not None and not df.empty:
                has_data_to_write = True
                break
        if has_data_to_write:
            break

    # 步驟二：只有在確定有資料時，才建立 ExcelWriter 並寫入
    if has_data_to_write:
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            for sheet_name, tables in sheet_data.items():
                for table_info in tables:
                    df = table_info.get('dataframe')
                    if df is not None and not df.empty:
                        start_row = table_info.get('start_row', 0)
                        df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=start_row)
    
    # 步驟三：回傳處理後的數據
    processed_data = output.getvalue()
    return processed_data

def render():
    """渲染「匯出報表」頁面的所有 Streamlit UI 元件。"""
    st.header("各式報表匯出")

    # --- 1. 上傳至雲端儀表板 ---
    with st.container(border=True):
        st.subheader("更新至雲端儀表板 (Google Sheet)")
        st.info("點擊下方按鈕，系統將會查詢最新的「人員清冊」與「設備清單」，並將其上傳至 Google Sheet。")
        
        if st.button("🚀 開始上傳", type="primary"):
            with st.spinner("正在查詢並上傳最新數據至雲端..."):
                # 1. 獲取人員數據
                worker_data = export_model.get_data_for_export()
                # 2. 獲取設備數據
                equipment_data = export_model.get_equipment_for_export()
                
                # 3. 準備要上傳的資料包
                data_package = {}
                if worker_data is not None and not worker_data.empty:
                    data_package["人員清冊"] = worker_data
                if equipment_data is not None and not equipment_data.empty:
                    data_package["設備清冊"] = equipment_data

                if not data_package:
                    st.warning("目前沒有任何人員或設備資料可供上傳。")
                else:
                    # 4. 執行上傳
                    success, message = export_model.update_google_sheet(data_package)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
    st.markdown("---")

    st.markdown("---")

    # --- 月份異動人員報表 ---
    with st.container(border=True):
        st.subheader("月份異動人員報表")
        st.info("選擇一個月份，系統將匯出該月份所有「離住」以及「有特殊狀況」的人員清單。")
        
        today = datetime.now()
        c1, c2, c3 = st.columns([1, 1, 2])
        
        selected_year = c1.selectbox("選擇年份", options=range(today.year - 2, today.year + 2), index=2, key="exception_report_year")
        selected_month = c2.selectbox("選擇月份", options=range(1, 13), index=today.month - 1, key="exception_report_month")
        year_month_str = f"{selected_year}-{selected_month:02d}"

        # 使用 st.empty() 來創建一個容器，以便在生成報表後顯示下載按鈕
        download_placeholder = st.empty()

        if c3.button("🚀 產生異動報表", key="generate_exception_report"):
            with st.spinner(f"正在查詢 {year_month_str} 的異動人員資料..."):
                report_df = report_model.get_monthly_exception_report(year_month_str)
            
            if report_df.empty:
                st.warning("在您選擇的月份中，找不到任何離住或有特殊狀況的人員。")
            else:
                st.success(f"報表已產生！共找到 {len(report_df)} 筆紀錄。請點擊下方按鈕下載。")
                
                excel_file = to_excel({"異動人員清單": {"dataframe": report_df}})
                
                download_placeholder.download_button(
                    label="📥 點此下載 Excel 報表",
                    data=excel_file,
                    file_name=f"住宿例外_{year_month_str}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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

                            # --- 【核心修改】將兩個表格放在同一個工作表的列表中 ---
                            excel_file_data = {
                                "宿舍報表": [
                                    {
                                        "dataframe": summary_df,
                                        "start_row": 0
                                    },
                                    {
                                        "dataframe": details_df,
                                        "start_row": len(summary_df) + 2
                                    }
                                ]
                            }
                            excel_file = to_excel(excel_file_data)
                            # --- 修改結束 ---
                            
                            dorm_name_for_file = dorm_options.get(selected_dorm_id, "export").replace(" ", "_").replace("/", "_")
                            st.download_button(
                                label="✅ 報表已產生！點此下載",
                                data=excel_file,
                                file_name=f"宿舍報表_{dorm_name_for_file}.xlsx"
                            )
    st.markdown("---")

    # # --- 4. 通用總覽報表 ---
    # with st.container(border=True):
    #     st.subheader("通用總覽報表")
        
    #     st.markdown("##### 宿舍總覽報表")
    #     dorms_df = dormitory_model.get_all_dorms_for_view()
    #     if not dorms_df.empty:
    #         excel_data_dorms = to_excel({"宿舍總覽": [{"dataframe": dorms_df}]})
    #         st.download_button("📥 下載完整宿舍總覽 (Excel)", data=excel_data_dorms, file_name="dormitory_summary_full.xlsx")
        
    #     st.markdown("---")

    #     st.markdown("##### 移工住宿總覽報表")
    #     report_status_filter = st.selectbox("選擇在住狀態", ["全部", "在住", "已離住"], key="report_status_filter")
    #     workers_df_report = worker_model.get_workers_for_view({'status': report_status_filter})
    #     if not workers_df_report.empty:
    #         excel_data_workers = to_excel({"移工住宿總覽": [{"dataframe": workers_df_report}]})
    #         st.download_button("📥 下載移工住宿總覽 (Excel)", data=excel_data_workers, file_name=f"worker_accommodation_summary_{report_status_filter}.xlsx")