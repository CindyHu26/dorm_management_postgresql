import streamlit as st
import configparser
import os

# 從新的 views 資料夾中，匯入各個頁面的 render 函式
from views import scraper_view, dormitory_view, worker_view, report_view

def load_config():
    """載入設定檔"""
    config = configparser.ConfigParser()
    config.read('config.ini', encoding='utf-8')
    return config

def main():
    """主應用程式"""
    st.set_page_config(layout="wide", page_title="宿舍與移工綜合管理系統")
    
    # 初始化 session state
    if 'log_messages' not in st.session_state:
        st.session_state.log_messages = []

    config = load_config()
    st.title("宿舍與移工綜合管理系統")

    with st.sidebar:
        st.header("功能選單")
        page_options = ["系統爬取", "地址管理", "人員管理", "匯出報表"]
        page = st.radio("請選擇功能頁面：", page_options)

    # 根據選擇的頁面，呼叫對應的 render 函式
    if page == "系統爬取":
        scraper_view.render(config) # 將設定傳遞給爬蟲頁面
    elif page == "地址管理":
        dormitory_view.render()
    elif page == "人員管理":
        worker_view.render() # 目前是預留的空頁面
    elif page == "匯出報表":
        report_view.render() # 目前是預留的空頁面

if __name__ == "__main__":
    main()