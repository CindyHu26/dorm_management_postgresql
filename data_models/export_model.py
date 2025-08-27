import pandas as pd
import os
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import database
import utils

# --- 設定 ---
GSHEET_NAME = "宿舍外部儀表板數據"
CREDENTIALS_FILE = "credentials.json"
# --- 設定結束 ---

def _execute_query_to_dataframe(conn, query, params=None):
    """一個輔助函式，用來手動執行查詢並回傳 DataFrame。"""
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        records = cursor.fetchall()
        if not records:
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return pd.DataFrame([], columns=columns)
        
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(records, columns=columns)

def get_data_for_export():
    """
    從本地資料庫中，獲取【經過篩選】的人員清冊數據 (已為 PostgreSQL 優化)。
    """
    print("INFO: 正在從本地資料庫查詢最新人員清冊...")
    
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                d.primary_manager AS "主要管理人",
                d.normalized_address as "宿舍地址",
                r.room_number as "房號",
                w.employer_name AS "雇主",
                w.worker_name AS "姓名",
                w.gender AS "性別",
                w.nationality AS "國籍",
                w.monthly_fee as "月費",
                w.special_status as "特殊狀況"
            FROM "Workers" w
            LEFT JOIN "Rooms" r ON w.room_id = r.id
            LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE 
                d.primary_manager = '我司' AND
                (w.accommodation_end_date IS NULL OR w.accommodation_end_date > CURRENT_DATE)
            ORDER BY d.normalized_address, r.room_number, w.worker_name
        """
        df = _execute_query_to_dataframe(conn, query)
        print(f"INFO: 查詢完成，共篩選出 {len(df)} 筆符合條件 (我司管理、在住) 的人員資料。")
        return df
    finally:
        if conn: conn.close()

def get_equipment_for_export():
    """
    從本地資料庫中，獲取所有「我司管理」宿舍的設備清單 (已為 PostgreSQL 優化)。
    """
    print("INFO: 正在從本地資料庫查詢最新設備清單...")
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                d.normalized_address AS "宿舍地址",
                e.equipment_name AS "設備名稱",
                e.location AS "位置",
                e.next_check_date AS "下次更換/檢查日",
                e.status AS "狀態",
                e.report_path AS "文件路徑"
            FROM "DormitoryEquipment" e
            JOIN "Dormitories" d ON e.dorm_id = d.id
            WHERE d.primary_manager = '我司'
              AND e.next_check_date IS NOT NULL
            ORDER BY e.next_check_date ASC
        """
        df = _execute_query_to_dataframe(conn, query)
        print(f"INFO: 查詢完成，共獲取 {len(df)} 筆設備資料。")
        return df
    finally:
        if conn: conn.close()

def update_google_sheet(data_to_upload: dict):
    """
    將一個包含多個 DataFrame 的字典，上傳並覆蓋到指定的 Google Sheet 的不同工作表中。
    """
    print(f"INFO: 準備將數據上傳至 Google Sheet: '{GSHEET_NAME}'...")
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        
        creds_path = utils.get_resource_path(CREDENTIALS_FILE)

        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
        client = gspread.authorize(creds)

        try:
            spreadsheet = client.open(GSHEET_NAME)
        except gspread.exceptions.SpreadsheetNotFound:
            spreadsheet = client.create(GSHEET_NAME)
            spreadsheet.share('your_email@gmail.com', perm_type='user', role='writer')

        for sheet_name, df in data_to_upload.items():
            try:
                worksheet = spreadsheet.worksheet(sheet_name)
            except gspread.WorksheetNotFound:
                worksheet = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols="30")

            worksheet.clear()
            df_to_upload = df.fillna('')
            
            data_list = [df_to_upload.columns.values.tolist()] + df_to_upload.values.tolist()
            worksheet.update(data_list, value_input_option='RAW')
            
            print(f"  > 工作表 '{sheet_name}' 已成功更新。")
        
        return True, f"數據上傳成功！您的雲端儀表板現在包含最新的資料。"

    except FileNotFoundError:
        return False, f"錯誤：在專案根目錄下找不到憑證檔案 '{CREDENTIALS_FILE}'。"
    except Exception as e:
        return False, f"與 Google Sheets API 互動時發生錯誤: {e}"