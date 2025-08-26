import pandas as pd
import sqlite3
import os

# 匯入我們自訂的模組
import database

def fix_all_date_formats():
    """
    遍歷資料庫中所有指定的日期欄位，並將其格式統一為 'YYYY-MM-DD'。
    【v2.0 修正版】改為使用 UPDATE 陳述句，避免使用 to_sql('replace') 破壞表格結構。
    回傳處理報告。
    """
    report_lines = []
    
    tables_and_columns = {
        'Workers': ['arrival_date', 'departure_date', 'work_permit_expiry_date', 
                    'accommodation_start_date', 'accommodation_end_date'],
        'Leases': ['lease_start_date', 'lease_end_date'],
        'DormitoryEquipment': ['last_replaced_date', 'next_check_date'],
        'AnnualExpenses': ['payment_date'],
        'UtilityBills': ['bill_start_date', 'bill_end_date'],
        'Dormitories': ['insurance_start_date', 'insurance_end_date',
                        'fire_safety_start_date', 'fire_safety_end_date']
    }

    conn = database.get_db_connection()
    if not conn:
        report_lines.append("錯誤：無法連接到資料庫。")
        return report_lines

    try:
        cursor = conn.cursor()
        total_updated_rows = 0
        
        for table, columns in tables_and_columns.items():
            report_lines.append(f"\n--- 正在處理表格: {table} ---")
            
            # 取得主鍵名稱 (假設都是單一主鍵)
            cursor.execute(f"PRAGMA table_info({table})")
            pk_col = next((col[1] for col in cursor.fetchall() if col[5] == 1), None)
            if not pk_col:
                report_lines.append(f"  WARNING: 找不到表格 '{table}' 的主鍵，已略過。")
                continue

            # 組合要查詢的欄位
            cols_to_select = f'"{pk_col}", ' + ', '.join(f'"{c}"' for c in columns)
            
            try:
                # 讀取資料時就嘗試解析日期
                df = pd.read_sql_query(f"SELECT {cols_to_select} FROM {table}", conn, parse_dates=columns)
            except Exception as e:
                if "no such column" in str(e):
                    report_lines.append(f"  INFO: 表格 '{table}' 結構不匹配或缺少日期欄位，已略過。")
                    continue
                else:
                    report_lines.append(f"  WARNING: 讀取表格 '{table}' 失敗: {e}")
                    continue

            if df.empty:
                report_lines.append("  INFO: 表格中無資料，無需校正。")
                continue

            updates_for_table = 0
            # 遍歷每一列來檢查並準備更新
            for index, row in df.iterrows():
                for col in columns:
                    if col in row and pd.notna(row[col]):
                        # 將 Timestamp 物件格式化為標準字串
                        formatted_date = row[col].strftime('%Y-%m-%d')
                        pk_value = row[pk_col]
                        
                        try:
                            # 產生並執行 UPDATE 指令
                            sql = f'UPDATE "{table}" SET "{col}" = ? WHERE "{pk_col}" = ?'
                            cursor.execute(sql, (formatted_date, pk_value))
                            updates_for_table += cursor.rowcount
                        except Exception as e:
                            report_lines.append(f"  ERROR: 更新 {table}.{col} (ID: {pk_value}) 失敗: {e}")
            
            if updates_for_table > 0:
                total_updated_rows += updates_for_table
                report_lines.append(f"  SUCCESS: 表格 '{table}' 中共有 {updates_for_table} 個日期欄位被校正。")
            else:
                report_lines.append(f"  INFO: 表格 '{table}' 的日期格式無需更新。")

        conn.commit() # 提交所有變更
        report_lines.append("\n--- 日期格式校正完成！ ---")
        if total_updated_rows > 0:
            report_lines.append(f"總共更新了 {total_updated_rows} 個欄位的值。您的資料庫結構保持不變。")
        else:
            report_lines.append("所有表格都已是最新狀態，或無資料可校正。")

    except Exception as e:
        report_lines.append(f"處理過程中發生嚴重錯誤: {e}")
        if conn: conn.rollback()
    finally:
        if conn:
            conn.close()
    
    return report_lines