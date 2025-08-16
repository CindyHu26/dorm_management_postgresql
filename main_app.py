import streamlit as st
import configparser
import os

# 從 views 資料夾中，匯入所有頁面的模組
from views import (
    dashboard_view, 
    scraper_view, 
    dormitory_view, 
    worker_view, 
    rent_view, 
    expense_view, 
    annual_expense_view, 
    lease_view, 
    equipment_view, 
    meter_view, 
    batch_import_view, 
    report_view
)

def load_config():
    """載入設定檔"""
    config = configparser.ConfigParser()
    # 確保路徑的正確性，即使從子目錄執行
    config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
    config.read(config_path, encoding='utf-8')
    return config

def main():
    """主應用程式"""
    st.set_page_config(layout="wide", page_title="宿舍與移工綜合管理系統")
    
    # 初始化 session state
    if 'log_messages' not in st.session_state:
        st.session_state.log_messages = []

    config = load_config()
    
    # --- 【本次修改】全新的分組側邊欄導航 ---
    with st.sidebar:
        st.title("宿舍管理系統")
        
        # 預設展開第一個群組
        with st.expander("📊 總覽與報表", expanded=True):
            page1 = st.radio(" ", ["儀表板", "匯出報表"], key="nav1")

        with st.expander("⚙️ 核心業務管理", expanded=False):
            page2 = st.radio(" ", [
                "人員管理", "地址管理", "房租管理", "費用管理", 
                "年度費用", "合約管理", "設備管理", "電水錶管理"
            ], key="nav2")

        with st.expander("💾 資料匯入與同步", expanded=False):
            page3 = st.radio(" ", ["批次匯入", "系統爬取"], key="nav3")

    # 偵測哪個 radio group 被選中
    # Streamlit 的 radio group 如果沒被選中，其 session state 值會是初始值
    ctx = st.runtime.scriptrunner.get_script_run_ctx()
    last_interaction = ctx.widget_ids_this_run
    
    # 預設頁面
    page = st.session_state.get('page', "儀表板")

    if 'nav1' in last_interaction:
        page = st.session_state.nav1
    elif 'nav2' in last_interaction:
        page = st.session_state.nav2
    elif 'nav3' in last_interaction:
        page = st.session_state.nav3
    
    st.session_state.page = page

    # --- 根據選擇的頁面，渲染對應的UI元件 ---
    # 為了讓標題和頁面內容匹配，我們在這裡顯示大標題
    st.title(page)

    if page == "儀表板":
        dashboard_view.render()
    elif page == "匯出報表":
        report_view.render()
    elif page == "人員管理":
        worker_view.render()
    elif page == "地址管理":
        dormitory_view.render()
    elif page == "房租管理":
        rent_view.render()
    elif page == "費用管理":
        expense_view.render()
    elif page == "年度費用":
        annual_expense_view.render()
    elif page == "合約管理":
        lease_view.render()
    elif page == "設備管理":
        equipment_view.render()
    elif page == "電水錶管理":
        meter_view.render()
    elif page == "批次匯入":
        batch_import_view.render()
    elif page == "系統爬取":
        scraper_view.render(config)

if __name__ == "__main__":
    main()