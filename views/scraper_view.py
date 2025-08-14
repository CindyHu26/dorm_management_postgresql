import streamlit as st
from datetime import datetime

# 匯入我們建立的後端模組
import scraper
import data_processor
import updater

# --- 頁面輔助函式 ---

def log_message(message: str):
    """
    將帶有時間戳的日誌訊息附加到 session_state 中，以便在UI上即時顯示。
    """
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # 使用 insert(0, ...) 將最新訊息放在最前面
    st.session_state.log_messages.insert(0, f"[{timestamp}] {message}")

def _run_download_only(url, auth, temp_dir):
    """
    執行「僅下載」的後端流程。函式名稱前的底線表示這是一個內部輔助函式。
    """
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
        st.session_state.downloaded_files = downloaded_files
        log_message(f"下載完成！共 {len(downloaded_files)} 個檔案已暫存，可執行下一步「寫入資料庫」。")
        st.success("下載成功！詳情請見日誌。")
    else:
        st.session_state.downloaded_files = None
        log_message("下載流程結束，但未獲取任何檔案。")
        st.warning("下載完成，但未收到任何檔案。")

def _run_write_only():
    """執行「僅寫入資料庫」的後端流程。"""
    if not st.session_state.get('downloaded_files'):
        st.error("錯誤：沒有暫存的已下載檔案。請先執行「僅下載資料」流程。")
        log_message("錯誤：試圖在沒有下載檔案的情況下寫入資料庫。")
        return

    log_message("流程啟動：處理暫存檔案並寫入資料庫...")
    
    # 1. 處理資料
    processed_df = data_processor.parse_and_process_reports(
        file_paths=st.session_state.downloaded_files,
        log_callback=log_message
    )
    
    # 2. 更新資料庫
    if processed_df is not None and not processed_df.empty:
        updater.run_update_process(
            fresh_df=processed_df,
            log_callback=log_message
        )
        st.success("資料庫更新成功！詳情請見日誌。")
    else:
        log_message("資料處理後為空，沒有需要更新到資料庫的內容。")
        st.warning("資料處理完成，但沒有內容可寫入資料庫。")
        
    # 清除暫存，無論成功與否
    st.session_state.downloaded_files = None
    log_message("流程結束，暫存檔案已清除。")


# --- 主渲染函式 ---

def render(config):
    """
    渲染「系統爬取」頁面的所有 Streamlit UI 元件。
    """
    st.header("自動化資料同步控制台")

    # 從主應用程式傳入的 config 物件讀取設定
    url = config.get('System', 'URL', fallback='http://127.0.0.1')
    account = config.get('System', 'ACCOUNT', fallback='')
    password = config.get('System', 'PASSWORD', fallback='')
    temp_dir = config.get('System', 'TEMP_DIR', fallback='temp_downloads')

    # 將設定項統一放在側邊欄，讓主頁面保持整潔
    with st.sidebar:
        st.header("系統連線設定")
        target_url = st.text_input("內網系統URL", url)
        st_account = st.text_input("帳號", account)
        st_password = st.text_input("密碼", password, type="password")
        
    auth_credentials = (st_account, st_password)

    st.info("請在左側側邊欄輸入您的帳號密碼，然後選擇下方的執行按鈕。")

    # 使用欄位佈局讓按鈕並排
    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("① 僅下載資料", help="從內網系統下載最新的報表，並暫存。此操作會覆蓋上一次的暫存檔。"):
            st.session_state.log_messages = [] # 清空舊日誌
            with st.spinner("正在連線並下載報表，請稍候..."):
                _run_download_only(target_url, auth_credentials, temp_dir)

    with col2:
        if st.button("② 僅寫入資料庫", help="將已暫存的檔案進行處理與比對，並更新至資料庫。執行此步驟前必須先成功執行過步驟①。"):
            st.session_state.log_messages = [] # 清空舊日誌
            with st.spinner("正在處理資料並更新資料庫，請稍候..."):
                _run_write_only()
    
    with col3:
        if st.button("🚀 下載並直接寫入 (全自動)", type="primary", help="自動化執行步驟①和②，完成一次完整的資料同步。"):
            st.session_state.log_messages = [] # 清空舊日誌
            with st.spinner("正在執行全自動同步，過程可能需要數分鐘，請稍候..."):
                _run_download_only(target_url, auth_credentials, temp_dir)
                # 檢查下載是否有成功（session_state中是否有檔案列表）
                if st.session_state.get('downloaded_files'):
                    _run_write_only()

    # 日誌輸出區
    st.header("執行日誌")
    # 使用 st.expander 讓日誌可以折疊
    with st.expander("點此展開/收合詳細日誌", expanded=True):
        log_container = st.container(height=400)
        # 顯示日誌
        for message in st.session_state.get('log_messages', []):
            log_container.text(message)