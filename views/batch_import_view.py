import streamlit as st
import pandas as pd
from io import BytesIO
from data_models import importer_model

def to_excel(df):
    """將 DataFrame 轉換為可供下載的 Excel 檔案。"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Sheet1')
    processed_data = output.getvalue()
    return processed_data

def render():
    """渲染「批次匯入」頁面"""
    st.header("批次資料匯入中心")

    # --- 1. 變動費用匯入區塊 ---
    with st.container(border=True):
        st.subheader("變動費用批次匯入 (水電、網路等)")
        st.info("請下載新版範本，依照帳單上的【起訖日】和【總金額】填寫。")
        
        # 【本次修改】提供全新的範本
        expense_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮中山路100號"],
            "費用類型": ["電費"],
            "帳單金額": [6500],
            "帳單起始日": ["2025-06-15"],
            "帳單結束日": ["2025-08-14"],
            "是否已請款": ["N"],
            "備註": ["夏季電費"]
        })
        st.download_button(
            label="📥 下載變動費用匯入範本",
            data=to_excel(expense_template_df),
            file_name="utility_bill_import_template.xlsx"
        )

        uploaded_monthly_file = st.file_uploader("上傳【變動費用】Excel 檔案", type=["xlsx"], key="monthly_uploader")

        if uploaded_monthly_file:
            try:
                df_monthly = pd.read_excel(uploaded_monthly_file)
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_monthly.head())
                if st.button("🚀 開始匯入變動費用", type="primary", key="monthly_import_btn"):
                    with st.spinner("正在處理與匯入資料..."):
                        # 【本次修改】呼叫的函式名稱不變，但背後邏輯已更新
                        success, failed_df = importer_model.batch_import_expenses(df_monthly)
                    st.success(f"匯入完成！成功 {success} 筆。")
                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
                        st.download_button(
                            label="📥 下載失敗紀錄報告",
                            data=to_excel(failed_df),
                            file_name="import_failed_report.xlsx"
                        )
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")

    st.markdown("---")

    # --- 2. 年度費用匯入區塊 ---
    with st.container(border=True):
        st.subheader("年度/長期費用批次匯入 (保險、年費等)")
        
        annual_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮成功路123號"],
            "費用項目": ["114年度建築火險"],
            "支付日期": ["2025-08-15"],
            "總金額": [12000],
            "攤提起始月": ["2025-09"],
            "攤提結束月": ["2026-08"],
            "備註": ["富邦產險 A-123"]
        })
        st.download_button(
            label="📥 下載年度費用匯入範本",
            data=to_excel(annual_template_df),
            file_name="annual_expense_import_template.xlsx"
        )
        
        uploaded_annual_file = st.file_uploader("上傳【年度費用】Excel 檔案", type=["xlsx"], key="annual_uploader")

        if uploaded_annual_file:
            try:
                df_annual = pd.read_excel(uploaded_annual_file)
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_annual.head())
                if st.button("🚀 開始匯入年度費用", type="primary", key="annual_import_btn"):
                    with st.spinner("正在處理與匯入資料..."):
                        success, failed_df = importer_model.batch_import_annual_expenses(df_annual)
                    st.success(f"匯入完成！成功 {success} 筆。")
                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")