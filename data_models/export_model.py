import pandas as pd
import os
import gspread
from gspread_dataframe import set_with_dataframe
from oauth2client.service_account import ServiceAccountCredentials
import database
import traceback

# 匯入其他 model 以複用查詢邏輯
from . import worker_model 

# --- 設定 ---
GSHEET_NAME = "宿舍外部儀表板數據"
CREDENTIALS_FILE = "credentials.json"
# --- 設定結束 ---

def get_data_for_export():
    """
    從本地資料庫中，獲取【經過篩選】的人員清冊數據。
    【v1.4 修改】增加篩選邏輯：只選擇「我司管理」且「在住」的人員。
    """
    print("INFO: 正在從本地資料庫查詢最新人員清冊...")
    
    # 1. 先獲取所有人員的完整資料
    # 我們傳遞一個空的 filter，代表先不篩選，拿到最原始的數據
    full_df = worker_model.get_workers_for_view(filters={})

    if full_df.empty:
        print("INFO: 資料庫中沒有任何人員資料。")
        return pd.DataFrame()
        
    # 2. 在記憶體中進行精準篩選
    filtered_df = full_df[
        (full_df['主要管理人'] == '我司') & 
        (full_df['在住狀態'] == '在住')
    ].copy() # 使用 .copy() 避免 pandas 的 SettingWithCopyWarning

    print(f"INFO: 查詢完成，共篩選出 {len(filtered_df)} 筆符合條件 (我司管理、在住) 的人員資料。")
    return filtered_df

def get_equipment_for_export():
    """
    從本地資料庫中，獲取所有「我司管理」宿舍的設備清單。
    """
    print("INFO: 正在從本地資料庫查詢最新設備清單...")
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                d.original_address AS "宿舍地址",
                e.equipment_name AS "設備名稱",
                e.location AS "位置",
                e.next_check_date AS "下次更換/檢查日",
                e.status AS "狀態"
            FROM DormitoryEquipment e
            JOIN Dormitories d ON e.dorm_id = d.id
            WHERE d.primary_manager = '我司'
              AND e.next_check_date IS NOT NULL AND e.next_check_date != ''
            ORDER BY date(e.next_check_date) ASC
        """
        df = pd.read_sql_query(query, conn)
        print(f"INFO: 查詢完成，共獲取 {len(df)} 筆設備資料。")
        return df
    finally:
        if conn: conn.close()

def update_google_sheet(data_to_upload: dict):
    """
    將 DataFrame 上傳至 Google Sheet，並提供詳細的偵錯日誌。
    """
    print(f"\n--- DEBUG: 進入 update_google_sheet 函式 ---")
    print(f"INFO: 準備將數據上傳至 Google Sheet: '{GSHEET_NAME}'...")
    
    try:
        # 1. 認證
        print("--- DEBUG: 步驟 1/5 - 正在讀取憑證檔案... ---")
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        base_path = os.path.dirname(os.path.abspath(__file__))
        creds_path = os.path.join(base_path, '..', CREDENTIALS_FILE)

        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
        # print(f"--- DEBUG: 憑證讀取成功，服務帳戶 Email: {creds.service_account_email} ---")

        client = gspread.authorize(creds)
        # print("--- DEBUG: 步驟 2/5 - Google API 客戶端授權成功。 ---")

        # 2. 開啟或建立 Google Sheet
        # print(f"--- DEBUG: 步驟 3/5 - 正在嘗試開啟 GSheet 檔案 '{GSHEET_NAME}'... ---")
        try:
            spreadsheet = client.open(GSHEET_NAME)
            # print("--- DEBUG: GSheet 檔案開啟成功。 ---")
        except gspread.exceptions.SpreadsheetNotFound:
            # print(f"--- DEBUG: 找不到 GSheet 檔案，正在嘗試建立新的... ---")
            spreadsheet = client.create(GSHEET_NAME)
            # 請將 your_email@gmail.com 換成您的 Email
            spreadsheet.share('your_email@gmail.com', perm_type='user', role='writer')
            # print("--- DEBUG: 新 GSheet 檔案建立並分享成功。 ---")

        # 3. 遍歷並更新每一個工作表
        # print("--- DEBUG: 步驟 4/5 - 準備開始更新工作表... ---")
        for sheet_name, df in data_to_upload.items():
            # print(f"  > 正在處理工作表: '{sheet_name}'...")
            try:
                worksheet = spreadsheet.worksheet(sheet_name)
                # print(f"    - 工作表 '{sheet_name}' 已存在，準備清空。")
            except gspread.WorksheetNotFound:
                # print(f"    - 工作表 '{sheet_name}' 不存在，正在建立新的。")
                worksheet = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols="30")

            worksheet.clear()
            # print(f"    - 工作表 '{sheet_name}' 已清空。")
            
            df_to_upload = df.fillna('')
            data_list = [df_to_upload.columns.values.tolist()] + df_to_upload.values.tolist()
            
            # print(f"    - 準備寫入 {len(data_list) - 1} 筆資料...")
            worksheet.update(data_list, value_input_option='RAW')
            # print(f"    - 工作表 '{sheet_name}' 已成功更新。")
        
        # print("--- DEBUG: 步驟 5/5 - 所有工作表更新完畢。 ---")
        return True, "數據上傳成功！"

    except FileNotFoundError:
        print(f"--- DEBUG: 致命錯誤 - 找不到憑證檔案 '{CREDENTIALS_FILE}'。 ---")
        return False, f"錯誤：在專案根目錄下找不到憑證檔案 '{CREDENTIALS_FILE}'。"
    except Exception as e:
        # 【核心修改】打印出最詳細的錯誤訊息
        print(f"--- DEBUG: 致命錯誤 - 與 Google API 互動時發生未知問題 ---")
        print(traceback.format_exc()) # 打印完整的錯誤追蹤
        return False, f"與 Google Sheets API 互動時發生錯誤: {e}"