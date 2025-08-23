import pandas as pd
import sqlite3

# 只依賴最基礎的 database 模組
import database
from data_processor import normalize_taiwan_address

def batch_import_expenses(df: pd.DataFrame):
    """
    批次匯入【每月/變動費用】的核心邏輯。
    (已更新為自給自足模式)
    """
    success_count = 0
    failed_records = []

    conn = database.get_db_connection()
    if not conn:
        print("ERROR: importer_model 無法連接到資料庫。")
        return 0, pd.DataFrame()
        
    try:
        cursor = conn.cursor()
        dorms_df = pd.read_sql_query("SELECT id, original_address FROM Dormitories", conn)
        dorms_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
        
        for index, row in df.iterrows():
            original_address = row.get('宿舍地址')
            billing_month_raw = row.get('費用月份')

            if not original_address or pd.isna(billing_month_raw):
                row['錯誤原因'] = "宿舍地址或費用月份為空"
                failed_records.append(row)
                continue
            
            try:
                billing_month = pd.to_datetime(billing_month_raw).strftime('%Y-%m')
            except (ValueError, TypeError):
                row['錯誤原因'] = f"費用月份 '{billing_month_raw}' 格式不正確"
                failed_records.append(row)
                continue
                
            dorm_id = dorms_map.get(original_address)
            if not dorm_id:
                row['錯誤原因'] = f"在資料庫中找不到對應的宿舍地址: {original_address}"
                failed_records.append(row)
                continue

            meter_id = None
            meter_number = row.get('對應錶號')
            if meter_number and pd.notna(meter_number):
                meter_number = str(meter_number).strip()
                cursor.execute("SELECT id FROM Meters WHERE dorm_id = ? AND meter_number = ?", (dorm_id, meter_number))
                meter_result = cursor.fetchone()
                if meter_result:
                    meter_id = meter_result['id']
                else:
                    row['錯誤原因'] = f"在宿舍 '{original_address}' 中找不到錶號為 '{meter_number}' 的紀錄"
                    failed_records.append(row)
                    continue
                
            details = {
                "dorm_id": dorm_id, "meter_id": meter_id,
                "bill_type": row.get('費用類型'),
                "amount": pd.to_numeric(row.get('帳單金額'), errors='coerce'),
                "bill_start_date": pd.to_datetime(row.get('帳單起始日'), errors='coerce').strftime('%Y-%m-%d'),
                "bill_end_date": pd.to_datetime(row.get('帳單結束日'), errors='coerce').strftime('%Y-%m-%d'),
                "is_invoiced": True if str(row.get('是否已請款')).strip().upper() in ['Y', 'TRUE', 'V', '是'] else False,
                "notes": str(row.get('備註', ''))
            }
            
            # Upsert 邏輯
            query = "SELECT id FROM UtilityBills WHERE dorm_id = ? AND bill_type = ? AND bill_start_date = ? AND amount = ?"
            params = [details['dorm_id'], details['bill_type'], details['bill_start_date'], details['amount']]
            if meter_id:
                query += " AND meter_id = ?"
                params.append(meter_id)
            else:
                query += " AND meter_id IS NULL"
            
            cursor.execute(query, tuple(params))
            existing = cursor.fetchone()

            if existing:
                # 更新
                fields = ', '.join([f'"{key}" = ?' for key in details.keys()])
                values = list(details.values())
                values.append(existing['id'])
                update_sql = f"UPDATE UtilityBills SET {fields} WHERE id = ?"
                cursor.execute(update_sql, tuple(values))
            else:
                # 新增
                columns = ', '.join(f'"{k}"' for k in details.keys())
                placeholders = ', '.join(['?'] * len(details))
                insert_sql = f"INSERT INTO UtilityBills ({columns}) VALUES ({placeholders})"
                cursor.execute(insert_sql, tuple(details.values()))

            success_count += 1

    except Exception as e:
        print(f"批次匯入每月費用時發生錯誤: {e}")
        if conn: conn.rollback()
    finally:
        if conn:
            conn.commit()
            conn.close()

    return success_count, pd.DataFrame(failed_records)


def batch_import_annual_expenses(df: pd.DataFrame):
    """
    批次匯入【年度/長期】費用的核心邏輯。
    """
    success_count = 0
    failed_records = []
    
    conn = database.get_db_connection()
    if not conn:
        print("ERROR: importer_model 無法連接到資料庫。")
        return 0, pd.DataFrame()

    try:
        cursor = conn.cursor()
        dorms_df = pd.read_sql_query("SELECT id, original_address FROM Dormitories", conn)
        dorms_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
        
        for index, row in df.iterrows():
            original_address = row.get('宿舍地址')
            expense_item = row.get('費用項目')
            payment_date_raw = row.get('支付日期')
            total_amount = pd.to_numeric(row.get('總金額'), errors='coerce')
            start_month_raw = row.get('攤提起始月')
            end_month_raw = row.get('攤提結束月')

            try:
                payment_date = pd.to_datetime(payment_date_raw).strftime('%Y-%m-%d')
                start_month = pd.to_datetime(start_month_raw).strftime('%Y-%m')
                end_month = pd.to_datetime(end_month_raw).strftime('%Y-%m')
            except (ValueError, TypeError):
                row['錯誤原因'] = "一個或多個日期/月份欄位格式不正確"
                failed_records.append(row)
                continue

            if not all([original_address, expense_item, pd.notna(total_amount)]):
                row['錯誤原因'] = "必填欄位(地址,項目,總金額)有缺漏或格式錯誤"
                failed_records.append(row)
                continue
                
            dorm_id = dorms_map.get(original_address)
            if not dorm_id:
                row['錯誤原因'] = f"在資料庫中找不到對應的宿舍地址: {original_address}"
                failed_records.append(row)
                continue
                
            details = {
                "dorm_id": dorm_id, "expense_item": expense_item,
                "payment_date": payment_date, "total_amount": int(total_amount),
                "amortization_start_month": start_month, "amortization_end_month": end_month,
                "notes": str(row.get('備註', ''))
            }
            
            query = "SELECT id FROM AnnualExpenses WHERE dorm_id = ? AND expense_item = ? AND payment_date = ?"
            cursor.execute(query, (dorm_id, expense_item, details['payment_date']))
            existing = cursor.fetchone()
            
            if existing:
                fields = ', '.join([f'"{key}" = ?' for key in details.keys()])
                values = list(details.values())
                values.append(existing['id'])
                update_sql = f"UPDATE AnnualExpenses SET {fields} WHERE id = ?"
                cursor.execute(update_sql, tuple(values))
            else:
                columns = ', '.join(f'"{k}"' for k in details.keys())
                placeholders = ', '.join(['?'] * len(details))
                insert_sql = f"INSERT INTO AnnualExpenses ({columns}) VALUES ({placeholders})"
                cursor.execute(insert_sql, tuple(details.values()))

            success_count += 1

    except Exception as e:
        print(f"批次匯入年度費用時發生錯誤: {e}")
        if conn: conn.rollback()
    finally:
        if conn:
            conn.commit()
            conn.close()
            
    return success_count, pd.DataFrame(failed_records)