import streamlit as st
import pandas as pd
from io import BytesIO
from data_models import importer_model
from datetime import date

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
    st.markdown("---")

    # --- 區塊一：變動費用匯入 ---
    with st.container(border=True):
        st.subheader("💧 變動費用匯入 (水電、網路等)")
        st.info("用於匯入水電、網路等每月變動的費用帳單。")
        
        # 【核心修改】在範本中加入「用量(度/噸)」
        expense_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮中山路100號"],
            "費用類型": ["電費"],
            "帳單金額": [6500],
            "用量(度/噸)": [1850.5], # 新增欄位
            "帳單起始日": ["2025-06-15"],
            "帳單結束日": ["2025-08-14"],
            "對應錶號": ["07-12-3333-44-5"],
            "支付方": ["我司"],
            "是否為代收代付": [False],
            "是否已請款": ["N"],
            "備註": ["1F公共電費"]
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
                        success, failed_df = importer_model.batch_import_expenses(df_monthly)
                    st.success(f"匯入完成！成功 {success} 筆。")
                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
                        st.download_button(
                            label="📥 下載失敗紀錄報告",
                            data=to_excel(failed_df),
                            file_name="import_failed_report.xlsx",
                            key="failed_monthly_download"
                        )
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")

    # --- 區塊二：一般年度費用匯入 ---
    with st.container(border=True):
        st.subheader("📋 一般年度費用匯入")
        st.info("用於匯入維修、消防安檢、傢俱等一次性支付，但效益橫跨多個月份的費用。")
        
        annual_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮成功路123號"],
            "費用項目": ["114年度消防安檢"],
            "支付日期": ["2025-08-15"], "總金額": [12000],
            "攤提起始月": ["2025-09"], "攤提結束月": ["2026-08"],
            "備註": ["ABC消防公司"]
        })
        st.download_button(
            label="📥 下載一般年度費用匯入範本",
            data=to_excel(annual_template_df),
            file_name="annual_expense_import_template.xlsx"
        )
        
        uploaded_annual_file = st.file_uploader("上傳【一般年度費用】Excel 檔案", type=["xlsx"], key="annual_uploader")

        if uploaded_annual_file:
            try:
                df_annual = pd.read_excel(uploaded_annual_file)
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_annual.head())
                if st.button("🚀 開始匯入一般年度費用", type="primary", key="annual_import_btn"):
                    with st.spinner("正在處理與匯入資料..."):
                        success, failed_df = importer_model.batch_import_annual_expenses(df_annual)
                    st.success(f"匯入完成！成功 {success} 筆。")
                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")

    st.markdown("---")

    # --- 區塊三：建物申報匯入 ---
    with st.container(border=True):
        st.subheader("🏗️ 建物申報匯入")
        st.info("請下載建物申報專用範本，依照欄位填寫後上傳。")
        
        permit_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮中山路100號"],
            "支付日期": ["2025-08-15"], "金額（未稅）": [10000], "總金額（含稅）": [10500], "請款日": ["2025-08-20"],
            "攤提起始月": ["2025-09-01"], "攤提結束月": ["2026-08-31"],
            "建築師": ["王大明建築師事務所"], "政府是否發文": [True],
            "下次申報起日期": ["2026-07-01"], "下次申報迄日期": ["2026-08-31"],
            "申報項目": ["公安申報"], "申報面積（合法）": ["150坪"], "申報面積（合法加違規）": ["165坪"],
            "使用執照有無": [True], "權狀有無": [True], "房東證件有無": [False],
            "現場是否改善": [True], "保險有無": [True],
            "申報文件送出日期": ["2025-08-01"], "掛號憑證日期": ["2025-08-02"], "收到憑證日期": ["2025-08-18"],
            "此次申報核准起日期": ["2025-09-01"], "此次申報核准迄日期": ["2026-08-31"],
        })
        st.download_button(
            label="📥 下載建物申報匯入範本",
            data=to_excel(permit_template_df),
            file_name="building_permit_import_template.xlsx"
        )

        uploaded_permit_file = st.file_uploader("上傳【建物申報】Excel 檔案", type=["xlsx"], key="permit_uploader")

        if uploaded_permit_file:
            try:
                df_permit = pd.read_excel(uploaded_permit_file)
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_permit.head())
                if st.button("🚀 開始匯入建物申報", type="primary", key="permit_import_btn"):
                    with st.spinner("正在處理與匯入建物申報資料..."):
                        success, failed_df = importer_model.batch_import_building_permits(df_permit)
                    st.success(f"匯入完成！成功 {success} 筆。")
                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
                        st.download_button(
                            label="📥 下載失敗紀錄報告",
                            data=to_excel(failed_df),
                            file_name="permit_import_failed_report.xlsx"
                        )
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")

    with st.container(border=True):
        st.subheader("🔥 消防安檢匯入")
        st.info("用於批次新增消防安檢的費用與憑證紀錄。")

        fire_safety_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮成功路123號"],
            "支付日期": [date.today().strftime('%Y-%m-%d')],
            "支付總金額": [12000],
            "攤提起始日": [date.today().strftime('%Y-%m-%d')],
            "攤提月數": [12],
            "支出對象/廠商": ["ABC消防公司"],
            "申報項目": ["114年度消防安檢"],
            "申報文件送出日期": [None], "掛號憑證日期": [None], "收到憑證日期": [None],
            "下次申報起始日期": [None], "下次申報結束日期": [None],
            "此次申報核准起始日期": [None], "此次申報核准結束日期": [None],
        })
        st.download_button(
            label="📥 下載消防安檢匯入範本",
            data=to_excel(fire_safety_template_df),
            file_name="fire_safety_import_template.xlsx"
        )

        uploaded_fire_safety_file = st.file_uploader("上傳【消防安檢】Excel 檔案", type=["xlsx"], key="fire_safety_uploader")

        if uploaded_fire_safety_file:
            try:
                df_fire_safety = pd.read_excel(uploaded_fire_safety_file)
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_fire_safety.head())
                if st.button("🚀 開始匯入消防安檢紀錄", type="primary", key="fire_safety_import_btn"):
                    with st.spinner("正在處理與匯入消防安檢紀錄..."):
                        success, failed_df, skipped_df = importer_model.batch_import_fire_safety(df_fire_safety)
                    st.success(f"匯入完成！成功新增 {success} 筆。")
                    if not skipped_df.empty:
                        st.warning(f"有 {len(skipped_df)} 筆資料因重複而跳過：")
                        st.dataframe(skipped_df)
                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")

    st.markdown("---")
    # --- 區塊四：住宿分配匯入 ---
    with st.container(border=True):
        st.subheader("🏠 住宿分配/異動匯入")
        st.info("用於批次分配或更新人員的實際住宿房間。")
        
        # --- 核心修改點：更新範本欄位名稱 ---
        accommodation_template_df = pd.DataFrame({
            "雇主": ["範例：ABC公司"],
            "姓名": ["阮文雄"],
            "護照號碼 (選填)": ["C1234567"],
            "實際住宿地址": ["範例：彰化縣鹿港鎮中山路100號"],
            "房號": ["A01"],
            "入住日 (換宿/指定日期時填寫)": [date.today().strftime('%Y-%m-%d')]
        })
        st.download_button(
            label="📥 下載住宿分配匯入範本",
            data=to_excel(accommodation_template_df),
            file_name="accommodation_import_template.xlsx"
        )

        uploaded_accommodation_file = st.file_uploader("上傳【住宿分配】Excel 檔案", type=["xlsx"], key="accommodation_uploader")

        if uploaded_accommodation_file:
            try:
                df_accommodation = pd.read_excel(uploaded_accommodation_file, dtype=str).fillna('')
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_accommodation.head())
                if st.button("🚀 開始匯入住宿資料", type="primary", key="accommodation_import_btn"):
                    with st.spinner("正在處理與匯入住宿資料..."):
                        success, failed_df = importer_model.batch_import_accommodation(df_accommodation)
                    st.success(f"匯入完成！成功 {success} 筆。")
                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
                        st.download_button(
                            label="📥 下載失敗紀錄報告",
                            data=to_excel(failed_df),
                            file_name="accommodation_import_failed_report.xlsx",
                        )
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")

    st.markdown("---")
    with st.container(border=True):
        st.subheader("📄 房租合約匯入")
        st.info("用於批次新增宿舍的租賃合約紀錄。")
        
        lease_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮中山路100號"],
            "合約起始日": ["2025-01-01"],
            "合約截止日": ["2026-12-31"],
            "月租金": [25000],
            "押金": [50000],
            "租金含水電": ["False"]
        })
        st.download_button(
            label="📥 下載房租合約匯入範本",
            data=to_excel(lease_template_df),
            file_name="lease_import_template.xlsx"
        )

        uploaded_lease_file = st.file_uploader("上傳【房租合約】Excel 檔案", type=["xlsx"], key="lease_uploader")

        if uploaded_lease_file:
            try:
                df_lease = pd.read_excel(uploaded_lease_file)
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_lease.head())
                if st.button("🚀 開始匯入房租合約", type="primary", key="lease_import_btn"):
                    with st.spinner("正在處理與匯入房租合約..."):
                        success, failed_df, skipped_df = importer_model.batch_import_leases(df_lease)
                    
                    st.success(f"匯入完成！成功新增 {success} 筆。")

                    # --- 新增顯示「跳過」紀錄的區塊 ---
                    if not skipped_df.empty:
                        st.warning(f"有 {len(skipped_df)} 筆資料因重複而跳過：")
                        st.dataframe(skipped_df)
                        st.download_button(
                            label="📥 下載跳過紀錄報告",
                            data=to_excel(skipped_df),
                            file_name="lease_import_skipped_report.xlsx",
                        )

                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
                        st.download_button(
                            label="📥 下載失敗紀錄報告",
                            data=to_excel(failed_df),
                            file_name="lease_import_failed_report.xlsx",
                        )
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")
