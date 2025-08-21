import pandas as pd
import sqlite3
import os

# 匯入我們自訂的模組
import database

def fix_all_date_formats():
    """
    遍歷資料庫中所有指定的日期欄位，並將其格式統一為 'YYYY-MM-DD'。
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
        total_updated_tables = 0
        
        for table, columns in tables_and_columns.items():
            report_lines.append(f"\n--- 正在處理表格: {table} ---")
            try:
                # 讀取時就直接轉換日期，效率更高
                df = pd.read_sql_query(f"SELECT * FROM {table}", conn, parse_dates=columns)
            except Exception as e:
                # 處理欄位不存在等問題
                if "no such column" in str(e):
                    report_lines.append(f"  INFO: 表格 '{table}' 結構不匹配或缺少日期欄位，已略過。")
                    continue
                else:
                    report_lines.append(f"  WARNING: 讀取表格 '{table}' 失敗: {e}")
                    continue

            if df.empty:
                report_lines.append("  INFO: 表格中無資料，無需校正。")
                continue

            # 將所有日期欄位格式化為標準字串
            for col in columns:
                if col in df.columns:
                    df[col] = df[col].dt.strftime('%Y-%m-%d').where(df[col].notna(), None)
            
            # 將整個表格寫回
            df.to_sql(table, conn, if_exists='replace', index=False)
            report_lines.append(f"  SUCCESS: 表格 '{table}' 的日期格式已成功校正並寫回。")
            total_updated_tables += 1

        report_lines.append("\n--- 日期格式校正完成！ ---")
        if total_updated_tables > 0:
            report_lines.append("您的資料庫現在擁有統一、標準的日期格式。")
        else:
            report_lines.append("所有表格都已是最新狀態，或無資料可校正。")

    except Exception as e:
        report_lines.append(f"處理過程中發生嚴重錯誤: {e}")
    finally:
        if conn:
            conn.close()
    
    return report_lines