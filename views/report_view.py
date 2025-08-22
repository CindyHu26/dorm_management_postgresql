import streamlit as st
import pandas as pd
from io import BytesIO
from data_models import report_model, dormitory_model, worker_model, export_model

def to_excel(df_dict: dict):
    """
    將一個包含多個 DataFrame 的字典寫入一個 Excel 檔案的不同工作表或不同位置。
    """
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # 遍歷字典中的每一個項目
        for sheet_name, data in df_dict.items():
            df = data.get('dataframe')
            # 檢查 DataFrame 是否存在且不為空
            if df is not None and not df.empty:
                start_row = data.get('start_row', 0)
                # 將 DataFrame 寫入指定的 sheet 和起始行
                df.to_excel(writer, index=False, sheet_name=sheet_name, startrow=start_row)
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

    # --- 2. 單一宿舍深度分析報表 ---
    with st.container(border=True):
        st.subheader("單一宿舍深度分析報表")
        st.info("選擇一個我司管理的宿舍，產生一份包含人數、國籍、性別統計與人員詳情的完整報告。")

        @st.cache_data
        def get_my_dorms():
            return dormitory_model.get_my_company_dorms_for_selection()

        my_dorms = get_my_dorms()
        if not my_dorms:
            st.warning("目前沒有「我司管理」的宿舍可供選擇。")
        else:
            dorm_options = {d['id']: d['original_address'] for d in my_dorms}
            selected_dorm_id = st.selectbox(
                "請選擇要匯出報表的宿舍：",
                options=list(dorm_options.keys()),
                format_func=lambda x: dorm_options[x]
            )

            if st.button("🚀 產生並下載宿舍報表", key="download_dorm_report"):
                if not selected_dorm_id:
                    st.error("請先選擇一個宿舍。")
                else:
                    with st.spinner("正在產生報表..."):
                        # 1. 獲取詳細資料
                        report_df = report_model.get_dorm_report_data(selected_dorm_id)
                        
                        if report_df.empty:
                            st.warning("此宿舍目前沒有在住人員可供匯出。")
                        else:
                            # 2. 建立總覽區塊
                            # 處理國籍統計，即使國籍為空值也能正常運作
                            nationality_counts = report_df['nationality'].dropna().value_counts().to_dict()
                            
                            summary_items = ["總人數", "男性人數", "女性人數"] + [f"{nat}籍人數" for nat in nationality_counts.keys()]
                            summary_values = [
                                len(report_df),
                                len(report_df[report_df['gender'] == '男']),
                                len(report_df[report_df['gender'] == '女']),
                            ] + list(nationality_counts.values())

                            summary_df = pd.DataFrame({
                                "統計項目": summary_items,
                                "數值": summary_values
                            })

                            # 3. 準備人員詳情區塊
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

                            # 4. 準備下載按鈕
                            # 將總覽和詳情放在同一個 Sheet 的不同位置
                            excel_file_dict = {
                                "宿舍報表": {
                                    "dataframe": summary_df,
                                    "start_row": 0
                                },
                                # 在 Sheet1 中，從總覽表格下方空兩行處開始寫入詳細資料
                                "Sheet1": { 
                                    "dataframe": details_df,
                                    "start_row": len(summary_df) + 2
                                }
                            }
                            excel_file = to_excel(excel_file_dict)
                            
                            dorm_name_for_file = dorm_options[selected_dorm_id].replace(" ", "_").replace("/", "_")
                            st.download_button(
                                label="✅ 報表已產生！點此下載",
                                data=excel_file,
                                file_name=f"宿舍報表_{dorm_name_for_file}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                            )

    st.markdown("---")

    # --- 3. 通用總覽報表 ---
    with st.container(border=True):
        st.subheader("通用總覽報表")
        
        st.markdown("##### 宿舍總覽報表")
        dorms_df = dormitory_model.get_all_dorms_for_view()
        if not dorms_df.empty:
            excel_data_dorms = to_excel({"宿舍總覽": {"dataframe": dorms_df}})
            st.download_button(
                label="📥 下載完整宿舍總覽 (Excel)",
                data=excel_data_dorms,
                file_name="dormitory_summary_full.xlsx"
            )
        else:
            st.info("目前無宿舍資料可匯出。")
            
        st.markdown("---")

        st.markdown("##### 移工住宿總覽報表")
        report_status_filter = st.selectbox("選擇在住狀態", ["全部", "在住", "已離住"], key="report_status_filter")
        workers_df_report = worker_model.get_workers_for_view({'status': report_status_filter})
        
        if not workers_df_report.empty:
            excel_data_workers = to_excel({"移工住宿總覽": {"dataframe": workers_df_report}})
            st.download_button(
                label="📥 下載移工住宿總覽 (Excel)",
                data=excel_data_workers,
                file_name=f"worker_accommodation_summary_{report_status_filter}.xlsx"
            )
        else:
            st.info("目前無移工資料可匯出。")