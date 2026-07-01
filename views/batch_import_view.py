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
    st.markdown("---")

    # --- 區塊一：變動費用匯入 ---
    with st.container(border=True):
        st.subheader("💧 變動費用匯入 (水電、網路等)")
        st.info(
            """
            用於匯入水電、網路等每月變動的費用帳單。
            - **更新方式**：系統會以「宿舍地址 + 費用類型 + 帳單起始日 + 對應錶號」來判斷是否為同一筆紀錄。若紀錄已存在，則會**覆蓋**舊資料；若不存在，則會新增。
            """
        )
        
        expense_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮中山路100號"],
            "費用類型": ["電費"],
            "帳單金額": [6500],
            "用量(度/噸)": [1850.5],
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
        st.info(
            """
            用於匯入維修、消防安檢、傢俱等一次性支付，但效益橫跨多個月份的費用。
            - **更新方式**：系統會以「宿舍地址 + 費用項目 + 支付日期」來判斷是否為同一筆紀錄。若紀錄已存在，則會**覆蓋**舊資料。
            """
        )
        
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
        # --- 【核心修改 1】更新說明文字 ---
        st.info(
            """
            請下載建物申報專用範本，依照欄位填寫後上傳。
            - **更新方式**：系統會以「宿舍地址 + 申報項目 + 此次申報核准起日期」來判斷是否重複。若紀錄已存在，則會**跳過**不處理。
            """
        )
        
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
                        # --- 【核心修改 2】接收三個回傳值 ---
                        success, failed_df, skipped_df = importer_model.batch_import_building_permits(df_permit)
                    st.success(f"匯入完成！成功新增 {success} 筆。")
                    
                    # --- 【核心修改 3】顯示跳過的紀錄 ---
                    if not skipped_df.empty:
                        st.warning(f"有 {len(skipped_df)} 筆資料因重複而跳過：")
                        st.dataframe(skipped_df)

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
        st.info(
            """
            用於批次新增消防安檢的費用與憑證紀錄。
            - **更新方式**：系統會以「宿舍地址 + 支付日期 + 支付總金額」來判斷是否重複。若紀錄已存在，則會**跳過**不處理。
            """
        )

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
    # --- 【核心修改】區塊四：住宿分配匯入 (改為頁籤) ---
    with st.container(border=True):
        st.subheader("🏠 住宿分配/異動匯入")
        
        tab_move, tab_overwrite = st.tabs(["批次異動 (換宿)", "批次覆蓋 (修正資料)"])

        # 共用範本
        accommodation_template_df = pd.DataFrame({
            "雇主": ["範例：ABC公司"],
            "姓名": ["阮文雄"],
            "護照號碼 (選填)": ["C1234567"],
            "實際住宿地址": ["範例：彰化縣鹿港鎮中山路100號"],
            "房號": ["A01"],
            "床位編號 (選填)": ["A-01上"],
            "入住日 (換宿/指定日期時填寫)": [date.today().strftime('%Y-%m-%d')]
        })
        
        # --- 頁籤 1: 異動 (換宿) ---
        with tab_move:
            st.info(
                """
                **適用時機：** 員工實際「換宿」、從 `[未分配房間]` 狀態指定一個「新的」入住日。
                - **運作方式：**
                    - 系統會結束該員工上一筆住宿紀錄的 `end_date`。
                    - 並以 Excel 上的「入住日」(若無則為今天) 建立一筆**新的**住宿紀錄。
                    - 這會保留完整的住宿歷史。
                - **注意：** 此功能**不會**保留 `[未分配房間]` 的原始入住日。
                """
            )
            st.download_button(
                label="📥 下載匯入範本 (與覆蓋共用)",
                data=to_excel(accommodation_template_df),
                file_name="accommodation_import_template.xlsx",
                key="move_template_download"
            )
            uploaded_file_move = st.file_uploader("上傳【異動】Excel 檔案", type=["xlsx"], key="accommodation_uploader_move")
            
            if uploaded_file_move:
                try:
                    df_move = pd.read_excel(uploaded_file_move, dtype=str).fillna('')
                    st.markdown("##### 檔案內容預覽：")
                    st.dataframe(df_move.head())
                    if st.button("🚀 開始匯入異動資料", type="primary", key="accommodation_import_move_btn"):
                        with st.spinner("正在處理與匯入異動資料..."):
                            # 呼叫新的 "move" 函式
                            success, failed_df = importer_model.batch_import_accommodation_move(df_move)
                        st.success(f"匯入完成！成功 {success} 筆。")
                        if not failed_df.empty:
                            st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                            st.dataframe(failed_df)
                            st.download_button(
                                label="📥 下載失敗紀錄報告",
                                data=to_excel(failed_df),
                                file_name="accommodation_move_failed_report.xlsx",
                            )
                except Exception as e:
                    st.error(f"處理檔案時發生錯誤：{e}")

        # --- 頁籤 2: 覆蓋 (修正) ---
        with tab_overwrite:
            st.info(
                """
                **適用時機：** 修正錯誤資料，例如將 `[未分配房間]` 改為正確房號，且**希望保留原始入住日**。
                - **運作方式：**
                    - 系統會找到該員工**最新一筆**住宿紀錄 (無論是什麼房號)。
                    - **直接覆蓋**該筆紀錄的「房號」和「床號」。
                    - 如果 Excel 的「入住日」**為空**：會保留該筆紀錄**原始的** `start_date` (不會變)。
                    - 如果 Excel 的「入住日」**有填**：會**連同 `start_date` 一起覆蓋**成 Excel 上的日期。
                - **警告：** 此功能會修改歷史，不會產生新的住宿紀錄。
                """
            )
            st.download_button(
                label="📥 下載匯入範本 (與異動共用)",
                data=to_excel(accommodation_template_df),
                file_name="accommodation_import_template.xlsx",
                key="overwrite_template_download"
            )
            uploaded_file_overwrite = st.file_uploader("上傳【覆蓋】Excel 檔案", type=["xlsx"], key="accommodation_uploader_overwrite")
            
            if uploaded_file_overwrite:
                try:
                    df_overwrite = pd.read_excel(uploaded_file_overwrite, dtype=str).fillna('')
                    st.markdown("##### 檔案內容預覽：")
                    st.dataframe(df_overwrite.head())
                    if st.button("🚀 開始匯入覆蓋資料", type="primary", key="accommodation_import_overwrite_btn"):
                        with st.spinner("正在處理與匯入覆蓋資料..."):
                            # 呼叫新的 "overwrite" 函式
                            success, failed_df = importer_model.batch_import_accommodation_overwrite(df_overwrite)
                        st.success(f"匯入完成！成功 {success} 筆。")
                        if not failed_df.empty:
                            st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                            st.dataframe(failed_df)
                            st.download_button(
                                label="📥 下載失敗紀錄報告",
                                data=to_excel(failed_df),
                                file_name="accommodation_overwrite_failed_report.xlsx",
                            )
                except Exception as e:
                    st.error(f"處理檔案時發生錯誤：{e}")

    st.markdown("---")
    with st.container(border=True):
        st.subheader("📄 長期合約匯入")
        st.info(
            """
            用於批次新增宿舍的租賃合約紀錄。
            - **更新方式**：系統會以「宿舍地址 + 合約項目 + 合約起始日 + 月租金」來判斷是否重複。若紀錄已存在，則會**跳過**不處理。
            """
        )
        
        lease_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮中山路100號"],
            "合約項目": ["房租"],
            "房東/廠商": ["範例廠商-王大明"],
            "合約起始日": ["2025-01-01"],
            "合約截止日": ["2026-12-31"],
            "月租金": [25000],
            "押金": [50000],
            "租金含水電": ["False"],
            "備註": ["每半年付款一次"] 
        })
        st.download_button(
            label="📥 下載長期合約匯入範本",
            data=to_excel(lease_template_df),
            file_name="lease_import_template.xlsx"
        )
        uploaded_lease_file = st.file_uploader("上傳【長期合約】Excel 檔案", type=["xlsx"], key="lease_uploader")

        if uploaded_lease_file:
            try:
                df_lease = pd.read_excel(uploaded_lease_file)
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_lease.head())
                if st.button("🚀 開始匯入長期合約", type="primary", key="lease_import_btn"):
                    with st.spinner("正在處理與匯入長期合約..."):
                        success, failed_df, skipped_df = importer_model.batch_import_leases(df_lease)
                    
                    st.success(f"匯入完成！成功新增 {success} 筆。")

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

    st.markdown("---")
    with st.container(border=True):
        st.subheader("💰 其他收入匯入")
        st.info(
            """
            用於匯入冷氣卡儲值、販賣機等非房租的零星收入。
            - **更新方式**：系統會以「宿舍地址 + 收入項目 + 收入日期」來判斷是否為同一筆紀錄。若紀錄已存在，則會**覆蓋**舊資料。
            """
        )
        
        other_income_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮中山路100號"],
            "收入項目": ["冷氣卡儲值"],
            "房號 (選填)": ["A01"],
            "收入金額": [500],
            "收入日期": [date.today().strftime('%Y-%m-%d')],
            "備註": ["OOO儲值"]
        })
        st.download_button(
            label="📥 下載其他收入匯入範本",
            data=to_excel(other_income_template_df),
            file_name="other_income_import_template.xlsx"
        )

        uploaded_income_file = st.file_uploader("上傳【其他收入】Excel 檔案", type=["xlsx"], key="income_uploader")

        if uploaded_income_file:
            try:
                df_income = pd.read_excel(uploaded_income_file)
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_income.head())
                if st.button("🚀 開始匯入其他收入", type="primary", key="income_import_btn"):
                    with st.spinner("正在處理與匯入資料..."):
                        success, failed_df = importer_model.batch_import_other_income(df_income)
                    st.success(f"匯入完成！成功 {success} 筆。")
                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")

    st.markdown("---")
    with st.container(border=True):
            st.subheader("🏢 宿舍房間資訊匯入")
            st.info(
                """
                用於更新現有宿舍的房間資訊，或為已存在的宿舍批次新增房間。
                - **更新方式**：請確保 Excel 中的「宿舍地址」已存在於系統中。系統會以「宿舍地址 + 房號」判斷紀錄。若房間已存在，則**覆蓋**舊資料；若不存在，則會在該宿舍下新增此房間。
                """
            )
            
            dorm_room_template_df = pd.DataFrame({
                "宿舍地址": ["範例：彰化縣鹿港鎮中山路100號", "範例：彰化縣鹿港鎮中山路100號", "範例：雲林縣麥寮鄉工業路1號"],
                "房號": ["A01", "A02", "101"],
                "容量": [4, 6, 4],
                "性別限制": ["僅限男性", "可混住", "不限"],
                "國籍限制": ["單一國籍", "不限", "不限"],
                "房間備註": ["", "只提供A雇主員工", ""]
            })
            st.download_button(
                label="📥 下載宿舍與房間匯入範本",
                data=to_excel(dorm_room_template_df),
                file_name="dorm_room_import_template.xlsx"
            )

            uploaded_dorm_room_file = st.file_uploader("上傳【宿舍與房間】Excel 檔案", type=["xlsx"], key="dorm_room_uploader")

            if uploaded_dorm_room_file:
                try:
                    df_dorm_room = pd.read_excel(uploaded_dorm_room_file)
                    st.markdown("##### 檔案內容預覽：")
                    st.dataframe(df_dorm_room.head())
                    if st.button("🚀 開始匯入宿舍與房間", type="primary", key="dorm_room_import_btn"):
                        with st.spinner("正在處理與匯入資料..."):
                            success, failed_df = importer_model.batch_import_dorms_and_rooms(df_dorm_room)
                        st.success(f"匯入完成！成功處理 {success} 筆房間紀錄。")
                        if not failed_df.empty:
                            st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                            st.dataframe(failed_df)
                            st.download_button(
                                label="📥 下載失敗紀錄報告",
                                data=to_excel(failed_df),
                                file_name="dorm_room_import_failed_report.xlsx",
                                key="failed_dorm_room_download"
                            )
                except Exception as e:
                    st.error(f"處理檔案時發生錯誤：{e}")

    st.markdown("---")
    with st.container(border=True):
        st.subheader("🔧 廠商資料匯入")
        st.info(
            """
            用於將您現有的廠商聯絡人 Excel 檔案批次匯入系統。
            - **更新方式**：系統會以「廠商名稱 + 服務項目」來判斷是否為同一筆紀錄。若紀錄已存在，則會**覆蓋**舊資料。
            """
        )
        
        vendor_template_df = pd.DataFrame({
            "服務項目": ["範例：房東"],
            "廠商名稱": ["王大明"],
            "聯絡人": ["王大明"],
            "聯絡電話": ["0912345678"],
            "統一編號": ["12345678"],
            "匯款資訊": ["XX銀行 YY分行\n帳號: 123-456-789012"],
            "備註": ["僅收現金"]
        })
        st.download_button(
            label="📥 下載廠商資料匯入範本",
            data=to_excel(vendor_template_df),
            file_name="vendor_import_template.xlsx"
        )

        uploaded_vendor_file = st.file_uploader("上傳【廠商資料】Excel/XLS 檔案", type=["xlsx", "xls"], key="vendor_uploader")

        if uploaded_vendor_file:
            try:
                df_vendor = pd.read_excel(uploaded_vendor_file)
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_vendor.head())
                if st.button("🚀 開始匯入廠商資料", type="primary", key="vendor_import_btn"):
                    with st.spinner("正在處理與匯入廠商資料..."):
                        success, failed_df = importer_model.batch_import_vendors(df_vendor)
                    st.success(f"匯入完成！成功處理 {success} 筆廠商紀錄。")
                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
                        st.download_button(
                            label="📥 下載失敗紀錄報告",
                            data=to_excel(failed_df),
                            file_name="vendor_import_failed_report.xlsx",
                            key="failed_vendor_download"
                        )
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")

    st.markdown("---")
    with st.container(border=True):
        st.subheader("🛠️ 維修紀錄批次處理")
        
        tab1, tab2 = st.tabs(["批次新增", "批次更新"])

        with tab1:
            st.info(
                """
                用於將【全新】的維修案件紀錄，從 Excel 檔案批次匯入系統。
                - **更新方式**：系統會以「宿舍地址 + 修理細項說明 + 收到通知日期」判斷是否重複。若紀錄已存在，將會自動**跳過**。
                """
            )
            
            maintenance_template_df = pd.DataFrame({
                "收到通知日期": [date.today().strftime('%Y-%m-%d')],
                "宿舍地址": ["範例：彰化縣鹿港鎮中山路100號"],
                "修理細項說明": ["A01房門鎖損壞"],
                "項目類型": ["門窗"],
                "維修廠商": ["範例廠商-金冠不鏽鋼"],
                "公司內部通知人": ["王大明"],
                "聯絡廠商日期": [None],
                "鑰匙": ["警衛室領取"],
                "廠商回報完成日期": [None],
                "付款人": ["我司"],
                "維修費用": [1500],
                "請款日期": [None],
                "發票": ["抬頭: XXX, 統編: 12345678"],
                "備註": ["房客回報"],
                "狀態": ["待處理"]
            })
            st.download_button(
                label="📥 下載新增維修紀錄範本",
                data=to_excel(maintenance_template_df),
                file_name="maintenance_import_template.xlsx"
            )

            uploaded_maintenance_file = st.file_uploader("上傳【新維修紀錄】Excel 檔案", type=["xlsx", "xls"], key="maintenance_uploader")

            if uploaded_maintenance_file:
                try:
                    df_maintenance = pd.read_excel(uploaded_maintenance_file)
                    st.markdown("##### 檔案內容預覽：")
                    st.dataframe(df_maintenance.head())
                    if st.button("🚀 開始新增維修紀錄", type="primary", key="maintenance_import_btn"):
                        with st.spinner("正在處理與匯入維修紀錄..."):
                            success, failed_df = importer_model.batch_insert_maintenance_logs(df_maintenance)
                        st.success(f"匯入完成！成功新增 {success} 筆維修紀錄。")
                        if not failed_df.empty:
                            st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                            st.dataframe(failed_df)
                            st.download_button(
                                label="📥 下載失敗紀錄報告",
                                data=to_excel(failed_df),
                                file_name="maintenance_import_failed_report.xlsx",
                                key="failed_maintenance_download"
                            )
                except Exception as e:
                    st.error(f"處理檔案時發生錯誤：{e}")
        
        with tab2:
            st.info(
                """
                用於批次【更新】費用、發票等後續資訊。
                - **更新方式**：請先下載目前的維修紀錄，系統會以檔案中的 **ID** 欄位為基準，**覆蓋**您在 Excel 中修改的欄位資料。
                """
            )

            if st.button("📥 下載待更新的維修紀錄檔"):
                with st.spinner("正在產生檔案..."):
                    df_to_export = importer_model.export_maintenance_logs_for_update()
                if df_to_export.empty:
                    st.warning("目前沒有可供更新的維修紀錄。")
                else:
                    st.download_button(
                        label="✅ 檔案已產生！點此下載",
                        data=to_excel(df_to_export),
                        file_name=f"maintenance_update_export_{date.today().strftime('%Y%m%d')}.xlsx"
                    )

            uploaded_update_file = st.file_uploader("上傳【已填寫的維修紀錄】Excel 檔案", type=["xlsx", "xls"], key="maintenance_updater")

            if uploaded_update_file:
                try:
                    df_update = pd.read_excel(uploaded_update_file)
                    st.markdown("##### 檔案內容預覽：")
                    st.dataframe(df_update.head())
                    if st.button("🚀 開始更新維修紀錄", type="primary", key="maintenance_update_btn"):
                        with st.spinner("正在處理與更新維修紀錄..."):
                            success, failed_df = importer_model.batch_update_maintenance_logs(df_update)
                        st.success(f"更新完成！成功處理 {success} 筆維修紀錄。")
                        if not failed_df.empty:
                            st.error(f"有 {len(failed_df)} 筆資料更新失敗：")
                            st.dataframe(failed_df)
                            st.download_button(
                                label="📥 下載失敗紀錄報告",
                                data=to_excel(failed_df),
                                file_name="maintenance_update_failed_report.xlsx",
                                key="failed_maintenance_update_download"
                            )
                except Exception as e:
                    st.error(f"處理檔案時發生錯誤：{e}")
    st.markdown("---")
    with st.container(border=True):
        st.subheader("⚙️ 設備匯入")
        st.info(
            """
            用於批次新增或更新宿舍內的各項設備資產。
            - **更新方式**：系統會以「宿舍地址 + 設備名稱 + 位置」來判斷是否為同一筆資料。若紀錄已存在，則會**覆蓋**舊資料；若不存在，則會新增。
            """
        )
        
        equipment_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮中山路100號"],
            "設備名稱": ["2F飲水機"],
            "設備分類": ["飲水設備"],
            "位置": ["2F走廊"],
            "供應廠商": ["範例廠商-賀眾牌"],
            "品牌/型號": ["賀眾牌 UR-123"],
            "序號/批號": ["SN-98765"],
            "安裝/啟用日期": [date(2025, 1, 15).strftime('%Y-%m-%d')],
            "採購金額": [18000],
            "一般保養週期(月)": [3],
            "上次保養日期": [date(2025, 7, 15).strftime('%Y-%m-%d')],
            "下次保養/檢查日期": [date(2025, 10, 15).strftime('%Y-%m-%d')],
            "合規檢測週期(月)": [6], 
            "首次合規檢測日期": [date(2025, 7, 20).strftime('%Y-%m-%d')], 
            "下次合規檢測日期": [date(2026, 1, 20).strftime('%Y-%m-%d')], 
            "首次合規檢測費用": [800], 
            "狀態": ["正常"],
            "備註": ["定期更換濾心"]
        })
        st.download_button(
            label="📥 下載設備匯入範本",
            data=to_excel(equipment_template_df),
            file_name="equipment_import_template.xlsx"
        )

        uploaded_equipment_file = st.file_uploader("上傳【設備】Excel 檔案", type=["xlsx"], key="equipment_uploader")

        if uploaded_equipment_file:
            try:
                df_equipment = pd.read_excel(uploaded_equipment_file)
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_equipment.head())
                if st.button("🚀 開始匯入設備", type="primary", key="equipment_import_btn"):
                    with st.spinner("正在處理與匯入設備資料..."):
                        success, failed_df = importer_model.batch_import_equipment(df_equipment)
                    st.success(f"匯入完成！成功處理 {success} 筆紀錄。")
                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
                        st.download_button(
                            label="📥 下載失敗紀錄報告",
                            data=to_excel(failed_df),
                            file_name="equipment_import_failed_report.xlsx",
                            key="failed_equipment_download"
                        )
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")

    st.markdown("---")
    with st.container(border=True):
        st.subheader("🏢 宿舍發票資訊匯入")
        st.info(
            """
            用於批次新增或更新宿舍的發票資訊（抬頭/統編）。
            - **更新方式**：系統會以 Excel 中的「宿舍地址」為基準，**覆蓋**資料庫中對應宿舍的發票資訊。請確保地址完全相符。
            """
        )

        invoice_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮中山路100號"],
            "發票抬頭/統編": ["範例公司 OOO\n12345678"],
        })
        st.download_button(
            label="📥 下載發票資訊匯入範本",
            data=to_excel(invoice_template_df),
            file_name="invoice_info_import_template.xlsx"
        )

        uploaded_invoice_file = st.file_uploader("上傳【宿舍發票資訊】Excel 檔案", type=["xlsx"], key="invoice_uploader")

        if uploaded_invoice_file:
            try:
                df_invoice = pd.read_excel(uploaded_invoice_file)
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_invoice.head())
                if st.button("🚀 開始匯入發票資訊", type="primary", key="invoice_import_btn"):
                    with st.spinner("正在處理與匯入資料..."):
                        success, failed_df = importer_model.batch_import_invoice_info(df_invoice)
                    st.success(f"匯入完成！成功處理 {success} 筆紀錄。")
                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
                        st.download_button(
                            label="📥 下載失敗紀錄報告",
                            data=to_excel(failed_df),
                            file_name="invoice_import_failed_report.xlsx",
                            key="failed_invoice_download"
                        )
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")

    with st.container(border=True):
        st.subheader("🏡 宿舍房東資訊匯入")
        st.info(
            """
            用於批次關聯宿舍與房東。
            - **更新方式**：系統會以「宿舍地址」為基準，**覆蓋**資料庫中對應宿舍的房東欄位。請確保房東名稱已存在於「廠商管理」（服務項目需為 "房東"）。
            """
        )

        landlord_template_df = pd.DataFrame({
            "宿舍地址": ["範例：彰化縣鹿港鎮成功路123號"],
            "房東": ["王大明"],
        })
        st.download_button(
            label="📥 下載房東資訊匯入範本",
            data=to_excel(landlord_template_df),
            file_name="landlord_info_import_template.xlsx"
        )

        uploaded_landlord_file = st.file_uploader("上傳【宿舍房東資訊】Excel 檔案", type=["xlsx"], key="landlord_uploader")

        if uploaded_landlord_file:
            try:
                df_landlord = pd.read_excel(uploaded_landlord_file)
                st.markdown("##### 檔案內容預覽：")
                st.dataframe(df_landlord.head())
                if st.button("🚀 開始匯入房東資訊", type="primary", key="landlord_import_btn"):
                    with st.spinner("正在處理與匯入資料..."):
                        success, failed_df = importer_model.batch_import_landlord_info(df_landlord)
                    st.success(f"匯入完成！成功處理 {success} 筆紀錄。")
                    if not failed_df.empty:
                        st.error(f"有 {len(failed_df)} 筆資料匯入失敗：")
                        st.dataframe(failed_df)
                        st.download_button(
                            label="📥 下載失敗紀錄報告",
                            data=to_excel(failed_df),
                            file_name="landlord_import_failed_report.xlsx",
                            key="failed_landlord_download"
                        )
            except Exception as e:
                st.error(f"處理檔案時發生錯誤：{e}")