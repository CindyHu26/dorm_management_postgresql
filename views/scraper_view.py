import streamlit as st
from datetime import datetime
import os

# 匯入我們建立的後端模組
import scraper
import data_processor
import updater

def log_message(message: str):
    """將帶有時間戳的日誌訊息附加到 session_state 中。"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    st.session_state.log_messages.insert(0, f"[{timestamp}] {message}")

def _run_download_only(url, auth, temp_dir):
    """執行「僅下載」的後端流程。"""
    log_message("流程啟動：僅下載最新報表...")
    query_ranges = scraper.generate_code_ranges()
    downloaded_files = scraper.download_all_reports(
        target_url=url,
        auth_credentials=auth,
        query_ranges=query_ranges,
        temp_dir=temp_dir,
        log_callback=log_message
    )
    if downloaded_files:
        log_message(f"下載完成！共 {len(downloaded_files)} 個檔案已存放於 '{temp_dir}' 資料夾。")
        st.success(f"下載成功！檔案已暫存，您可以隨時執行「寫入資料庫」。")
    else:
        log_message("下載流程結束，但未獲取任何檔案。")
        st.warning("下載完成，但未收到任何檔案。")

def _run_write_only(temp_dir):
    """
    執行「僅寫入資料庫」的後端流程。
    【v1.1 核心修改】不再依賴 session_state，而是直接掃描暫存資料夾。
    """
    log_message("流程啟動：處理暫存檔案並寫入資料庫...")
    
    if not os.path.exists(temp_dir) or not any(f.endswith('.xls') for f in os.listdir(temp_dir)):
        st.error(f"錯誤：在 '{temp_dir}' 資料夾中找不到任何報表檔案。")
        log_message(f"錯誤：在 '{temp_dir}' 中找不到報表檔案，請先執行「僅下載資料」。")
        return

    file_paths = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.endswith('.xls')]
    log_message(f"在 '{temp_dir}' 中找到 {len(file_paths)} 個報表檔案，開始處理...")
    
    processed_df = data_processor.parse_and_process_reports(
        file_paths=file_paths,
        log_callback=log_message
    )
    
    if processed_df is not None and not processed_df.empty:
        updater.run_update_process(
            fresh_df=processed_df,
            log_callback=log_message
        )
        st.success("資料庫更新成功！詳情請見日誌。")
    else:
        log_message("資料處理後為空，沒有需要更新到資料庫的內容。")
        st.warning("資料處理完成，但沒有內容可寫入資料庫。")
    
    log_message("流程結束。")

def render(config):
    """渲染「系統爬取」頁面"""

    url = config.get('System', 'URL', fallback='http://127.0.0.1')
    account = config.get('System', 'ACCOUNT', fallback='')
    password = config.get('System', 'PASSWORD', fallback='')
    temp_dir = config.get('System', 'TEMP_DIR', fallback='temp_downloads')

    with st.sidebar:
        st.header("系統連線設定")
        target_url = st.text_input("內網系統URL", url)
        st_account = st.text_input("帳號", account)
        st_password = st.text_input("密碼", password, type="password")
        
    auth_credentials = (st_account, st_password)

    st.info("請在左側側邊欄確認您的帳號密碼，然後選擇下方的執行按鈕。")

    # --- 【說明文字】 ---
    with st.expander("點此查看三種「資料來源」狀態的更新邏輯"):
        st.markdown(
            """
            系統會根據員工的「資料來源」狀態，決定如何更新資料：

            ### 1. 系統自動更新
            * **這是誰？**：所有從爬蟲新加入的員工，或是已「解除鎖定」的員工。
            * **更新邏輯**：
                * **爬蟲名單上「有」此人**：
                    * **住宿異動**：
                        * **情況A (換宿舍/重新入職)**：如果爬蟲抓到的宿舍地址 *不同於* 目前宿舍，**或者** 員工是「離住超過7天後」重新出現，系統會自動執行「換宿」（結束舊紀錄、新增一筆 `[未分配房間]` 紀錄）。
                        * **情況B (短暫消失/復活)**：如果員工只是「離住少於7天」後重新出現，系統會「復活」他原本的住宿紀錄（將 `end_date` 設回 `NULL`）。
                    * **離住日**：如果爬蟲資料中的「出境日期」有值，系統會**同時更新** `Workers` 主表和 `AccommodationHistory` 歷史表中的 `end_date`。
                    * **基本資料**：會用爬蟲的資料**覆蓋**所有基本資料（姓名、護照號碼、國籍等）。
                * **爬蟲名單上「沒有」此人**：
                    * 系統會**同時更新兩張表**：
                    * 1. `Workers` 表：設定 `accommodation_end_date` (離住日期) 為今天。
                    * 2. `AccommodationHistory` 表：將**最新一筆**住宿紀錄的 `end_date` (結束日) 也設為今天。

            ### 2. 手動調整
            * **這是誰？**：您曾經在「房間分配」、「批次編輯」或「人員管理」中手動修改過住宿的員工。
            * **更新邏輯**：
                * **爬蟲名單上「有」此人**：
                    * **住宿異動**：**[受保護]** 系統**不會**更動此員工的住宿歷史（`AccommodationHistory`）。即使爬蟲抓到不同地址，他也會留在您手動指定的房間。
                    * **離住日**：**[會更新]** 如果爬蟲的「出境日期」有值（或變更），系統會**同時更新** `Workers.accommodation_end_date` 和 `AccommodationHistory.end_date`。
                    * **基本資料**：**[會更新]** 系統會更新基本資料（姓名、護照號碼等）。
                * **爬蟲名單上「沒有」此人**：
                    * **[會更新]** 系統會**同時更新兩張表**：
                    * 1. `Workers` 表：設定 `accommodation_end_date` (離住日期) 為今天。
                    * 2. `AccommodationHistory` 表：將**最新一筆**住宿紀錄的 `end_date` (結束日) 也設為今天。

            ### 3. 手動管理(他仲)
            * **這是誰？**：您在「人員管理」中手動新增的員工，或是您手動「完全鎖定」的員工。
            * **更新邏輯**：**[完全鎖定]**
                * `updater.py` 會**完全跳過**這些員工。
                * 無論爬蟲名單上有沒有此人，系統**不會**更新他們的住宿、離住日或任何基本資料。
            """
        )
    # --- 【說明文字結束】 ---
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("① 僅下載資料", help="從內網系統下載最新的報表，並存放於暫存資料夾。"):
            st.session_state.log_messages = []
            with st.spinner("正在連線並下載報表..."):
                _run_download_only(target_url, auth_credentials, temp_dir)

    with col2:
        if st.button("② 僅寫入資料庫", help="讀取暫存資料夾中的所有報表，進行處理與比對，並更新至資料庫。"):
            st.session_state.log_messages = []
            with st.spinner("正在掃描檔案並更新資料庫..."):
                _run_write_only(temp_dir)
    
    with col3:
        if st.button("🚀 下載並直接寫入 (全自動)", type="primary", help="自動化執行步驟①和②。"):
            st.session_state.log_messages = []
            with st.spinner("正在執行全自動同步..."):
                _run_download_only(target_url, auth_credentials, temp_dir)
                # 檢查檔案是否真的存在於資料夾中
                if os.path.exists(temp_dir) and any(f.endswith('.xls') for f in os.listdir(temp_dir)):
                    _run_write_only(temp_dir)

    st.header("執行日誌")
    with st.expander("點此展開/收合詳細日誌", expanded=True):
        log_container = st.container(height=400)
        for message in st.session_state.get('log_messages', []):
            log_container.text(message)