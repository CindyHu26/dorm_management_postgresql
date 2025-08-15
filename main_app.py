import streamlit as st
import configparser
import os

# 從 views 資料夾中，匯入各個頁面的模組
from views import dashboard_view, scraper_view, dormitory_view, worker_view, rent_view, expense_view, batch_import_view, annual_expense_view

def load_config():
    """載入設定檔"""
    config = configparser.ConfigParser()
    config.read('config.ini', encoding='utf-8')
    return config

def main():
    """主應用程式"""
    st.set_page_config(layout="wide", page_title="宿舍與移工綜合管理系統")
    
    if 'log_messages' not in st.session_state:
        st.session_state.log_messages = []

    config = load_config()
    st.title("宿舍與移工綜合管理系統")

    with st.sidebar:
        st.header("功能選單")
        
        page_options = ["儀表板", "房租管理", "費用管理", "年度費用", "系統爬取", "地址管理", "人員管理", "批次匯入"]
        page = st.radio("請選擇功能頁面：", page_options, index=0) # index=0 讓儀表板成為預設頁面

    # 根據選擇的頁面，呼叫對應的 render 函式
    if page == "儀表板":
        dashboard_view.render()
    elif page == "房租管理":
        rent_view.render()
    elif page == "費用管理":
        expense_view.render()
    elif page == "年度費用":
        annual_expense_view.render()
    elif page == "系統爬取":
        scraper_view.render(config)
    elif page == "地址管理":
        dormitory_view.render()
    elif page == "人員管理":
        worker_view.render()
    elif page == "批次匯入":
        batch_import_view.render()

if __name__ == "__main__":
    main()