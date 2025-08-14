import streamlit as st
import pandas as pd
from datetime import datetime
import os
import configparser

# 匯入我們自己建立的後端模組
import database
import scraper
import data_processor
import updater

# --- 應用程式設定與初始化 ---

# 設定頁面為寬版模式，並給予標題
st.set_page_config(layout="wide", page_title="宿舍與移工綜合管理系統")

# 初始化 session state，用於在不同操作間傳遞資訊
if 'log_messages' not in st.session_state:
    st.session_state.log_messages = []
if 'downloaded_files' not in st.session_state:
    st.session_state.downloaded_files = None

# --- 後端功能調用 (包裝成函式) ---

def log_message(message):
    """將日誌訊息附加到 session state 中，以便在UI上顯示。"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    st.session_state.log_messages.append(f"[{timestamp}] {message}")

def run_download_only(url, auth, temp_dir):
    """執行「僅下載」流程"""
    st.session_state.log_messages = [] # 清空舊日誌
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

def run_write_only():
    """執行「僅寫入資料庫」流程"""
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
    if not processed_df.empty:
        updater.run_update_process(
            fresh_df=processed_df,
            log_callback=log_message
        )
        st.success("資料庫更新成功！詳情請見日誌。")
    else:
        log_message("資料處理後為空，沒有需要更新到資料庫的內容。")
        st.warning("資料處理完成，但沒有內容可寫入資料庫。")
        
    # 清除暫存
    st.session_state.downloaded_files = None
    log_message("流程結束，暫存檔案已清除。")


# --- UI 介面渲染 ---

st.title("宿舍與移工綜合管理系統 v3.0")

# 建立頁籤
tab1, tab2 = st.tabs(["⚙️ 主控台與日誌", "🏘️ 宿舍與人員管理"])

# --- TAB 1: 主控台 ---
with tab1:
    st.header("自動化流程控制台")

    # 將設定項放在側邊欄
    with st.sidebar:
        st.header("系統連線設定")
        # 未來可以從 config.ini 讀取預設值
        target_url = st.text_input("內網系統URL", "")
        account = st.text_input("帳號", "")
        password = st.text_input("密碼", "", type="password")
        
        auth_credentials = (account, password)
        temp_dir = "temp_downloads"

    st.info("請在左側側邊欄輸入您的帳號密碼，然後選擇下方的執行按鈕。")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("① 僅下載資料", help="從內網系統下載最新的報表，並暫存。此操作會覆蓋上一次的暫存檔。"):
            with st.spinner("正在下載中，請稍候..."):
                run_download_only(target_url, auth_credentials, temp_dir)

    with col2:
        if st.button("② 僅寫入資料庫", help="將已暫存的檔案進行處理與比對，並更新至資料庫。執行此步驟前必須先成功執行過步驟①。"):
            with st.spinner("正在處理資料並更新資料庫，請稍候..."):
                run_write_only()
    
    with col3:
        if st.button("🚀 下載並直接寫入 (全自動)", type="primary", help="自動化執行步驟①和②，完成一次完整的資料同步。"):
            with st.spinner("正在執行全自動同步，請稍候..."):
                run_download_only(target_url, auth_credentials, temp_dir)
                if st.session_state.get('downloaded_files'):
                    run_write_only()

    # 日誌輸出區
    st.header("執行日誌")
    log_container = st.container(height=400)
    for message in reversed(st.session_state.log_messages): # 倒序顯示，最新在最上面
        log_container.text(message)

# --- TAB 2: 宿舍管理 ---
with tab2:
    st.header("宿舍地址管理")

    # 使用 Expander 來折疊/展開表單，保持介面整潔
    with st.expander("➕ 新增宿舍地址"):
        with st.form("new_dorm_form", clear_on_submit=True):
            st.subheader("請填寫宿舍基本資料")
            
            # 建立多欄位佈局
            c1, c2 = st.columns(2)
            with c1:
                legacy_code = st.text_input("舊系統編號 (選填)")
                original_addr = st.text_input("原始地址 (必填)")
                managed_by = st.selectbox("管理方", ["我司代管", "雇主自行處理"])
            with c2:
                normalized_addr = st.text_input("正規化地址 (若留空，系統會自動產生)")
                legal_capacity = st.number_input("法定可住人數", min_value=0, step=1)
                dorm_notes = st.text_area("宿舍備註")
            
            # 法規相關
            st.markdown("---")
            st.subheader("法規與合約資訊")
            c3, c4, c5 = st.columns(3)
            with c3:
                insurance_policy_number = st.text_input("建築保險單號")
                insurance_status = st.selectbox("保險狀態", ["有效", "過期", "處理中", "無"])
                insurance_expiry_date = st.date_input("保險到期日", value=None)
            with c4:
                fire_inspection_status = st.selectbox("消防安檢狀態", ["合格", "不合格", "待改善", "無需"])
                next_fire_inspection_date = st.date_input("下次消防安檢日", value=None)
            with c5:
                 building_permit_info = st.text_input("建物使用執照號")

            submitted = st.form_submit_button("儲存新宿舍")
            if submitted:
                if not original_addr:
                    st.error("「原始地址」為必填欄位！")
                else:
                    # TODO: 呼叫 database.py 中的函式來儲存這些資料
                    # 這個功能我們將在下一階段實現
                    st.success(f"宿舍 '{original_addr}' 已成功紀錄 (功能開發中)。")
    
    st.markdown("---")
    
    st.subheader("現有宿舍總覽")
    
    if st.button("🔄 重新整理宿舍列表"):
        # 清除快取，以便下次能重新從資料庫讀取
        st.cache_data.clear()

    # 使用 st.cache_data 來快取資料庫查詢結果，避免重複讀取，提升效能
    @st.cache_data
    def get_all_dorms():
        try:
            conn = database.get_db_connection()
            df = pd.read_sql('SELECT id, legacy_dorm_code, original_address, normalized_address, managed_by, legal_capacity FROM Dormitories', conn)
            conn.close()
            return df
        except Exception as e:
            st.error(f"讀取宿舍資料失敗: {e}")
            return pd.DataFrame()

    dorms_df = get_all_dorms()
    
    if dorms_df.empty:
        st.info("目前資料庫中沒有任何宿舍資料，請使用上方表單新增。")
    else:
        st.dataframe(dorms_df, use_container_width=True)