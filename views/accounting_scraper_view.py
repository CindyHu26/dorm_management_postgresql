# views/accounting_scraper_view.py

import streamlit as st
import pandas as pd
import os
import json
from datetime import datetime, date
import scraper_b04  # 引用我們寫好的 B04 爬蟲模組
import data_processor
from data_models import finance_model

# --- 設定檔路徑 ---
FEE_CONFIG_FILE = "fee_config.json"

def load_fee_config():
    """讀取費用設定（包含「內部費用列表」與「對照表」）"""
    default_config = {
        "internal_types": ["房租", "水電費", "清潔費", "宿舍復歸費", "充電清潔費", "服務費"],
        "mapping": {
            "房租": "房租",
            "電費": "水電費",
            "水費": "水電費", 
            "清潔費": "清潔費",
            "服務費": "服務費"
        }
    }
    
    if os.path.exists(FEE_CONFIG_FILE):
        try:
            with open(FEE_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return default_config
    return default_config

def save_fee_config(config_data):
    """儲存設定到 JSON"""
    try:
        with open(FEE_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)
        return True
    except Exception as e:
        st.error(f"儲存設定失敗: {e}")
        return False

def log_message(message: str):
    """將帶有時間戳的日誌訊息附加到 session_state 中。"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if 'log_messages_acc' not in st.session_state:
        st.session_state.log_messages_acc = []
    st.session_state.log_messages_acc.insert(0, f"[{timestamp}] {message}")

# --- 執行邏輯 ---
def _run_download(url, auth, date_range, temp_dir):
    log_message(f"啟動下載流程 (目標: {temp_dir})...")
    files = scraper_b04.download_b04_in_batches(
        url_base=url, auth=auth, date_range=date_range, 
        temp_dir=temp_dir, log_callback=log_message
    )
    if files:
        log_message(f"下載完成，共 {len(files)} 個檔案。")
        st.success(f"下載成功！共 {len(files)} 個檔案，請繼續執行「寫入資料庫」。")
    else:
        st.warning("流程結束，但未下載到任何檔案。")

def _run_write(temp_dir, mapping):
    log_message(f"啟動資料庫寫入流程 (來源: {temp_dir})...")
    if not os.path.exists(temp_dir):
        st.error(f"錯誤：找不到資料夾 '{temp_dir}'。")
        return
    
    file_paths = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if f.endswith('.xls')]
    if not file_paths:
        st.warning("資料夾中無 Excel 檔案，請先下載。")
        return

    total_success = 0
    total_skipped = 0
    
    for file_path in file_paths:
        log_message(f"處理檔案: {os.path.basename(file_path)}")
        # 解析
        df = data_processor.parse_b04_xml(file_path, mapping)
        if df.empty:
            log_message("  -> 解析結果為空 (可能無符合對照表的費用)。")
            continue
        
        # 寫入
        success, skipped, errors = finance_model.batch_import_external_fees(df)
        total_success += success
        total_skipped += skipped
        
        log_message(f"  -> 寫入成功: {success}, 跳過: {skipped}")
        if errors:
            for err in errors[:3]: # 只顯示前3個錯誤避免洗版
                log_message(f"     * 錯誤: {err}")

    st.success(f"全部完成！共新增/更新 {total_success} 筆費用，跳過 {total_skipped} 筆。")
    log_message("=== 全部流程結束 ===")


def render(config):
    """渲染頁面"""

    # 初始化日誌
    if 'log_messages_acc' not in st.session_state:
        st.session_state.log_messages_acc = []

    # 1. 載入費用設定
    fee_config = load_fee_config()
    internal_types = fee_config.get("internal_types", [])
    current_mapping = fee_config.get("mapping", {})

    # ==============================================================================
    # 設定區塊：費用類型與對照表
    # ==============================================================================
    with st.expander("⚙️ 費用類型與對照表設定", expanded=True):
        
        tab_types, tab_mapping = st.tabs(["1. 管理內部費用類型", "2. 設定匯入對照表"])
        
        # --- 分頁 1: 管理內部費用類型 ---
        with tab_types:
            st.info("在此定義系統內部支援的費用名稱 (如: 房租、網路費)。新增後，即可在對照表中使用。")
            c1, c2 = st.columns([3, 1])
            new_type = c1.text_input("輸入新費用名稱", placeholder="例如: 網路費", key="new_fee_type_input")
            
            if c2.button("➕ 新增", key="add_fee_type_btn"):
                if new_type and new_type not in internal_types:
                    internal_types.append(new_type)
                    fee_config["internal_types"] = internal_types
                    save_fee_config(fee_config)
                    st.success(f"已新增「{new_type}」！")
                    st.rerun()
                elif new_type in internal_types:
                    st.warning("此類型已存在。")

            st.write("目前可用的費用類型：")
            updated_types = st.multiselect("移除費用類型", options=internal_types, default=internal_types, key="remove_fee_types")
            
            if set(updated_types) != set(internal_types):
                if st.button("確認移除變更"):
                    fee_config["internal_types"] = updated_types
                    save_fee_config(fee_config)
                    st.success("費用列表已更新！")
                    st.rerun()

        # --- 分頁 2: 設定匯入對照表 ---
        with tab_mapping:
            st.info("設定外部 B04 報表的「帳款名稱」應對應到哪個「內部費用類型」。(名稱相同也要設定)")
            
            mapping_df = pd.DataFrame(list(current_mapping.items()), columns=["外部帳款名稱", "對應內部費用"])
            
            edited_mapping_df = st.data_editor(
                mapping_df,
                num_rows="dynamic",
                column_config={
                    "外部帳款名稱": st.column_config.TextColumn("外部 B04 帳款名稱", required=True),
                    "對應內部費用": st.column_config.SelectboxColumn("對應系統費用", options=internal_types, required=True)
                },
                width='stretch',
                key="fee_mapping_editor"
            )

            if st.button("💾 儲存對照表設定"):
                new_map = {}
                if not edited_mapping_df.empty:
                    for _, row in edited_mapping_df.iterrows():
                        ext = str(row["外部帳款名稱"]).strip()
                        internal = str(row["對應內部費用"]).strip()
                        if ext and internal:
                            new_map[ext] = internal
                
                fee_config["mapping"] = new_map
                save_fee_config(fee_config)
                st.success("設定已儲存！下次爬蟲將使用此規則。")
                current_mapping = new_map # 更新變數供下方使用

    st.markdown("---")

    # ==============================================================================
    # 操作區塊：系統連線與爬取
    # ==============================================================================
    st.subheader("🚀 執行爬取與匯入")

    # 讀取 Config
    b04_url = config.get('SystemB04', 'URL', fallback='http://192.168.1.168/labor')
    b04_acc = config.get('SystemB04', 'ACCOUNT', fallback='')
    b04_pwd = config.get('SystemB04', 'PASSWORD', fallback='')
    b04_temp_dir = config.get('SystemB04', 'TEMP_DIR', fallback='temp_downloads_accounting')

    with st.container(border=True):
        c_set1, c_set2 = st.columns(2)
        with c_set1:
            st.text_input("B04系統 URL", value=b04_url, disabled=True, help="請至 config.ini 修改")
            st.text_input("暫存資料夾", value=b04_temp_dir, disabled=True)
        with c_set2:
            st.text_input("帳號", value=b04_acc, type="password", disabled=True)
            st.text_input("密碼", value=b04_pwd, type="password", disabled=True)
    
    # 日期選擇
    dc1, dc2 = st.columns(2)
    start_d = dc1.date_input("帳務起始日", value=date.today().replace(day=1))
    end_d = dc2.date_input("帳務結束日", value=date.today())
    date_range = (start_d, end_d)

    # 按鈕區
    btn1, btn2, btn3 = st.columns(3)
    
    if btn1.button("① 僅下載報表"):
        st.session_state.log_messages_acc = []
        with st.spinner("下載中..."):
            _run_download(b04_url, (b04_acc, b04_pwd), date_range, b04_temp_dir)

    if btn2.button("② 僅寫入資料庫"):
        st.session_state.log_messages_acc = []
        with st.spinner("寫入中..."):
            _run_write(b04_temp_dir, current_mapping)

    if btn3.button("🚀 全自動同步 (下載+寫入)", type="primary"):
        st.session_state.log_messages_acc = []
        with st.spinner("全自動執行中..."):
            _run_download(b04_url, (b04_acc, b04_pwd), date_range, b04_temp_dir)
            if os.path.exists(b04_temp_dir) and any(f.endswith('.xls') for f in os.listdir(b04_temp_dir)):
                _run_write(b04_temp_dir, current_mapping)

    # 日誌區
    with st.expander("執行日誌", expanded=True):
        log_container = st.container(height=300)
        for msg in st.session_state.log_messages_acc:
            log_container.text(msg)