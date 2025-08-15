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

    st.info("請先下載範本檔案，依照格式填寫後，再上傳至系統進行匯入。")

    # --- 1. 範本下載區 ---
    st.subheader("步驟一：下載範本檔案")
    
    # 在程式中直接建立範本 DataFrame
    expense_template_df = pd.DataFrame({
        "宿舍地址": ["範例：彰化縣鹿港鎮中山路100號"],
        "費用月份": ["2025-08"],
        "電費": [5000],
        "水費": [1200],
        "瓦斯費": [800],
        "網路費": [600],
        "其他費用": [0],
        "是否已請款": ["Y"]
    })
    
    st.download_button(
        label="📥 下載每月費用匯入範本 (Excel)",
        data=to_excel(expense_template_df),
        file_name="expense_import_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    st.markdown("---")

    # --- 2. 檔案上傳與預覽 ---
    st.subheader("步驟二：上傳已填寫的 Excel 檔案")
    
    uploaded_file = st.file_uploader("請選擇一個 XLSX 檔案", type=["xlsx"])

    if uploaded_file is not None:
        try:
            # 讀取上傳的檔案
            df_to_import = pd.read_excel(uploaded_file)
            
            st.markdown("#### 檔案內容預覽：")
            st.dataframe(df_to_import)
            
            st.markdown("---")
            
            # --- 3. 執行匯入 ---
            st.subheader("步驟三：確認並執行匯入")
            if st.button("🚀 開始匯入", type="primary"):
                with st.spinner("正在處理與匯入資料，請稍候..."):
                    success_count, failed_df = importer_model.batch_import_expenses(df_to_import)

                st.success(f"匯入完成！成功 {success_count} 筆。")
                
                if not failed_df.empty:
                    st.error(f"有 {len(failed_df)} 筆資料匯入失敗，詳情如下：")
                    st.dataframe(failed_df)
                    st.download_button(
                        label="📥 下載失敗紀錄報告",
                        data=to_excel(failed_df),
                        file_name="import_failed_report.xlsx"
                    )

        except Exception as e:
            st.error(f"讀取或處理檔案時發生錯誤：{e}")