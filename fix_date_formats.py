import pandas as pd
import sqlite3
import os

# 匯入我們自訂的模組
try:
    import database
except ImportError:
    print("錯誤：請確保此腳本與 database.py 在同一個資料夾中。")
    exit()

def fix_date_formats_in_db():
    """
    遍歷資料庫中所有指定的日期欄位，並將其格式統一為 'YYYY-MM-DD'。
    """
    print("--- 開始執行資料庫日期格式校正程序 ---")
    
    # 定義所有需要被校正的表格與欄位
    tables_and_columns = {
        'Workers': ['arrival_date', 'departure_date', 'work_permit_expiry_date', 
                    'accommodation_start_date', 'accommodation_end_date'],
        'Leases': ['lease_start_date', 'lease_end_date'],
        'DormitoryEquipment': ['last_replaced_date', 'next_check_date'],
        'AnnualExpenses': ['payment_date'],
        'UtilityBills': ['bill_start_date', 'bill_end_date']
    }

    conn = database.get_db_connection()
    if not conn:
        print("錯誤：無法連接到資料庫。")
        return

    try:
        total_updated_rows = 0
        
        for table, columns in tables_and_columns.items():
            print(f"\n--- 正在處理表格: {table} ---")
            try:
                df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
            except pd.errors.DatabaseError as e:
                print(f"  WARNING: 讀取表格 '{table}' 失敗 (可能不存在): {e}")
                continue

            if df.empty:
                print("  INFO: 表格中無資料，無需校正。")
                continue

            updates_made = False
            for col in columns:
                if col in df.columns:
                    # 使用 pandas.to_datetime 智能解析，並在出錯時保持原樣(NaT)
                    # errors='coerce' 參數是關鍵，它會將無法解析的內容變為 NaT (Not a Time)
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                    updates_made = True
            
            if updates_made:
                # 將整個表格寫回，pandas 會自動處理 NaT 為 NULL
                # 使用 'replace' 策略可以確保結構和格式都是最新的
                df.to_sql(table, conn, if_exists='replace', index=False)
                total_updated_rows += len(df)
                print(f"  SUCCESS: 表格 '{table}' 的日期格式已成功校正並寫回。")

        print("\n--- 日期格式校正完成！ ---")
        if total_updated_rows > 0:
            print("您的資料庫現在擁有統一、標準的日期格式。")
        else:
            print("所有表格都已是最新狀態，或無資料可校正。")

    except Exception as e:
        print(f"處理過程中發生嚴重錯誤: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    print("警告：此工具將會直接修改您現有的資料庫，將所有日期欄位統一為 'YYYY-MM-DD' 格式。")
    print("強烈建議在執行前，先手動備份您的 'dorm_management.db' 檔案。")
    confirm = input("我已了解風險並已備份檔案，確定要繼續嗎？ (請輸入 y 確認): ")
    
    if confirm.lower() == 'y':
        fix_date_formats_in_db()
    else:
        print("操作已取消。")