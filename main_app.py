import streamlit as st
import configparser
import os

# 從 views 資料夾中，匯入所有頁面的模組
from views import (
    dashboard_view,
    reminder_view, 
    dorm_analyzer_view, 
    employer_dashboard_view,
    analytics_view,
    scraper_view, 
    dormitory_view,
    placement_view,  
    worker_view, 
    rent_view,
    income_view,
    expense_view, 
    annual_expense_view, 
    lease_view, 
    equipment_view, 
    meter_view, 
    batch_import_view, 
    report_view,
    maintenance_view
)

def load_config():
    """載入設定檔"""
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
    if os.path.exists(config_path):
        config.read(config_path, encoding='utf-8')
    return config

# --- 將頁面結構化 ---
PAGES = {
    "總覽與報表": {
        "儀表板": dashboard_view,
        "智慧提醒": reminder_view,
        "宿舍深度分析": dorm_analyzer_view,
        "雇主儀表板": employer_dashboard_view,
        "費用分析": analytics_view,
        "匯出報表": report_view
    },
    "核心業務管理": {
        "人員管理": worker_view,
        "地址管理": dormitory_view,
        "空床位查詢": placement_view,
        "工人房租管理": rent_view,
        "其他收入管理": income_view,
        "費用管理": expense_view,
        "年度費用": annual_expense_view,
        "房租合約管理": lease_view,
        "設備管理": equipment_view,
        "電水錶管理": meter_view
    },
    "資料與系統維護": {
        "批次匯入": batch_import_view,
        "系統爬取": scraper_view,
        "系統維護": maintenance_view
    }
}

def main():
    """主應用程式"""
    st.set_page_config(layout="wide", page_title="宿舍與移工綜合管理系統")
    
    if 'log_messages' not in st.session_state:
        st.session_state.log_messages = []

    config = load_config()
    
    # --- 全新的階層式導航 ---
    with st.sidebar:
        st.title("宿舍管理系統")
        
        # 步驟一：選擇功能群組
        group_options = list(PAGES.keys())
        selected_group = st.selectbox("選擇功能群組：", group_options)
        
        st.markdown("---")
        
        # 步驟二：根據選擇的群組，顯示對應的頁面選項
        if selected_group:
            page_options = list(PAGES[selected_group].keys())
            selected_page = st.radio(
                f"{selected_group} - 頁面列表",
                page_options,
                label_visibility="collapsed"
            )
    
    # --- 根據選擇的頁面，渲染對應的UI元件 ---
    if selected_group and selected_page:
        st.title(selected_page)
        
        # 取得要執行的 render 函式
        page_to_render = PAGES[selected_group][selected_page]

        # 檢查是否需要傳遞 config
        if selected_page == "系統爬取":
            page_to_render.render(config)
        else:
            page_to_render.render()

if __name__ == "__main__":
    main()