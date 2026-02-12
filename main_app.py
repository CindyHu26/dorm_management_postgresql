import streamlit as st
import configparser
import os

# 從 views 資料夾中，匯入所有頁面的模組
from views import (
    dashboard_view,
    reminder_view,
    residency_analyzer_view,
    dorm_analyzer_view, 
    employer_dashboard_view,
    analytics_view,
    fee_dashboard_view,
    loss_analyzer_view,
    operations_analyzer_view,
    scraper_view, 
    dormitory_view,
    placement_view,  
    compliance_overview_view,
    room_assignment_view,
    worker_view, 
    photo_upload_view,
    rent_view,
    batch_operations_view,
    batch_history_editor_view,
    income_view,
    expense_view, 
    meter_expense_view,
    annual_expense_view,
    maintenance_view,
    lease_view, 
    contract_view,
    equipment_view, 
    meter_view,
    vendor_view,
    batch_import_view, 
    report_view,
    inventory_view,
    cleaning_schedule_view,
    accounting_scraper_view,
    unassigned_worker_view,
    guide_view,
    finance_dashboard_view,
)

def load_config():
    """載入設定檔"""
    config = configparser.ConfigParser()
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.ini')
    if os.path.exists(config_path):
        config.read(config_path, encoding='utf-8')
    return config

# 頁面結構化 (維持不變)
PAGES = {
    "📊 數據決策儀表板": {
        "系統總覽儀表板": dashboard_view,
        "費用基準與異常分析": fee_dashboard_view,      # 抓出收費異常
        "雇主損益分析": employer_dashboard_view, # 算雇主賺賠
        "虧損宿舍分析": loss_analyzer_view,      # 算宿舍賺賠
        "水電用量分析": analytics_view,          # 抓水電異常
        "宿舍深度分析": dorm_analyzer_view,      # 查單一宿舍詳情
        "歷史在住查詢": residency_analyzer_view, # 查歷史名單
        "營運優化建議": operations_analyzer_view,# 抓未設定房租的人
        "智慧提醒": reminder_view               # 到期提醒
    },

    "🏠 宿舍與人員營運": {
        "人員管理": worker_view,                # 增刪修人員
        "住宿照片批次上傳": photo_upload_view,
        "地址與房間管理": dormitory_view,        # 增刪修宿舍
        "空床位查詢": placement_view,            # 找空床
        "房間分配 (入住/換宿)": room_assignment_view, # 派房
        "未分配房間人員總覽": unassigned_worker_view, # 抓漏網之魚
        "進階批次作業": batch_operations_view,   # 批次換宿/離住
        "歷史紀錄修正": batch_history_editor_view, # 修錯資料
        "設備資產管理": equipment_view,          # 管冷氣/飲水機
        "庫存物品管理": inventory_view,          # 管備品/鑰匙
        "清掃排程管理": cleaning_schedule_view,  # 管打掃
        "合規資料與費用總覽": compliance_overview_view,
        "電水錶號管理": meter_view,               # 管錶號 (非費用)
        "廠商資料管理": vendor_view,                 # 建房東/廠商
    },

    "💰 財務收支管理": {
        "變動費用 (水電帳單)": expense_view,         # 輸入每月帳單
        "錶號費用 (快速輸入)": meter_expense_view,   # 依錶號輸費用
        "年度/攤銷費用": annual_expense_view,        # 輸入消防/保險/稅
        "維修追蹤與費用": maintenance_view,          # 輸入維修費
        "長期合約 (房租/網/清潔等)": lease_view,            # 輸入固定租金
        "合約項目總覽": contract_view,               # 看合約列表
        "其他收入管理": income_view,                 # 輸入雜項收入/補貼
        "工人房租設定": rent_view,                   # 設定跟工人收多少錢
        "宿舍別財務收支總覽": finance_dashboard_view,
    },

    "⚙️ 資料與系統維護": {
        "批次資料匯入": batch_import_view,           # Excel 匯入
        "移工系統同步 (爬蟲)": scraper_view,          # 抓人
        "財務系統同步 (B04)": accounting_scraper_view, # 抓錢
        "報表匯出中心": report_view                  # 下載報表
    },
    "📘 系統使用指南": {
        "操作手冊": guide_view
    },
}

# 輔助函式：根據頁面名稱反查其所屬的群組
def find_group_by_page(page_name):
    for group, pages in PAGES.items():
        if page_name in pages:
            return group
    return None

def main():
    """主應用程式"""
    st.set_page_config(layout="wide", page_title="宿舍與移工綜合管理系統")
    
    if 'log_messages' not in st.session_state:
        st.session_state.log_messages = []

    config = load_config()

    # --- 【核心修改：狀態管理邏輯】 ---

    # 1. 首次執行時，從 URL 初始化 session_state
    if 'page' not in st.session_state:
        query_page = st.query_params.get("page")
        # 檢查 URL 的頁面是否合法，不合法就用預設值
        if query_page and find_group_by_page(query_page):
            st.session_state.page = query_page
        else:
            st.session_state.page = "系統總覽儀表板" # 預設首頁
        # 第一次也需要設定 URL
        st.query_params["page"] = st.session_state.page

    # 2. 建立回呼函式，用於在使用者操作時更新狀態
    def on_group_change():
        # 當群組改變時，自動跳到該群組的第一個頁面
        new_group = st.session_state.group_selector
        st.session_state.page = list(PAGES[new_group].keys())[0]
        # 更新 URL
        st.query_params["page"] = st.session_state.page

    def on_page_change():
        # 當頁面改變時，直接更新 session_state 和 URL
        st.session_state.page = st.session_state.page_selector
        st.query_params["page"] = st.session_state.page
        
    # 3. 根據 session_state 來決定元件的預設值
    current_page = st.session_state.page
    current_group = find_group_by_page(current_page)
    
    # 如果狀態出錯（例如頁面被移除），則重置回首頁
    if not current_group:
        current_group = list(PAGES.keys())[0]
        current_page = list(PAGES[current_group].keys())[0]
        st.session_state.page = current_page
        st.query_params["page"] = current_page

    group_options = list(PAGES.keys())
    page_options = list(PAGES[current_group].keys())

    # --- 側邊欄導航 ---
    with st.sidebar:
        st.title("宿舍管理系統")
        
        st.selectbox(
            "選擇功能群組：", 
            group_options,
            index=group_options.index(current_group),
            key="group_selector",
            on_change=on_group_change
        )
        
        st.markdown("---")
        
        st.radio(
            f"{current_group} - 頁面列表",
            page_options,
            index=page_options.index(current_page),
            label_visibility="collapsed",
            key="page_selector",
            on_change=on_page_change
        )
    
    # --- 渲染頁面 ---
    page_to_render = PAGES[current_group][current_page]
    st.title(current_page)
    
    # 【這裡修正了判斷條件】
    if current_page == "移工系統同步 (爬蟲)" or current_page == "財務系統同步 (B04)": 
        page_to_render.render(config)
    else:
        page_to_render.render()

if __name__ == "__main__":
    main()