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
    config_path = os.path.join(os.path.dirname(__file__), 'config.ini')
    config.read(config_path, encoding='utf-8')
    return config

# --- 【本次修改】全新的導航狀態管理 ---
def set_page(nav_key):
    """
    這是一個回呼函式(Callback)，當任何一個 radio group 被點擊時，
    它會被觸發，並將選中的頁面名稱儲存到 session_state 中。
    """
    st.session_state.page = st.session_state[nav_key]

def main():
    """主應用程式"""
    st.set_page_config(layout="wide", page_title="宿舍與移工綜合管理系統")
    
    # 初始化 session state
    if 'log_messages' not in st.session_state:
        st.session_state.log_messages = []
    # 初始化當前頁面，預設為儀表板
    if 'page' not in st.session_state:
        st.session_state.page = "儀表板"

    config = load_config()
    
    # --- 側邊欄導航 ---
    with st.sidebar:
        st.title("宿舍管理系統")
        
        # 為了避免點選一個 radio group 時，其他 group 的選項被重設，
        # 我們需要確保每個 radio 的預設值是它自己目前的狀態值
        
        with st.expander("📊 總覽與報表", expanded=st.session_state.page in ["儀表板", "匯出報表"]):
            st.radio(
                "總覽與報表", 
                ["儀表板", "匯出報表"], 
                key="nav1", 
                label_visibility="collapsed",
                on_change=set_page, 
                args=("nav1",),
                index=["儀表板", "匯出報表"].index(st.session_state.page) if st.session_state.page in ["儀表板", "匯出報表"] else 0
            )

        with st.expander("⚙️ 核心業務管理", expanded=st.session_state.page in [
            "人員管理", "地址管理", "房租管理", "費用管理", 
            "年度費用", "合約管理", "設備管理", "電水錶管理"
        ]):
            core_pages = [
                "人員管理", "地址管理", "房租管理", "費用管理", 
                "年度費用", "合約管理", "設備管理", "電水錶管理"
            ]
            st.radio(
                "核心業務管理", 
                core_pages,
                key="nav2", 
                label_visibility="collapsed",
                on_change=set_page, 
                args=("nav2",),
                index=core_pages.index(st.session_state.page) if st.session_state.page in core_pages else 0
            )

        with st.expander("💾 資料匯入與同步", expanded=st.session_state.page in ["批次匯入", "系統爬取"]):
            data_pages = ["批次匯入", "系統爬取"]
            st.radio(
                "資料匯入與同步", 
                data_pages,
                key="nav3",
                label_visibility="collapsed",
                on_change=set_page,
                args=("nav3",),
                index=data_pages.index(st.session_state.page) if st.session_state.page in data_pages else 0
            )

    # --- 根據儲存的頁面狀態，渲染對應的UI元件 ---
    page = st.session_state.page
    st.title(page) # 在主畫面上方顯示當前頁面的大標題

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