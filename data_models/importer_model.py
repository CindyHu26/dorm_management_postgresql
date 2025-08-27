import pandas as pd
import database
# 匯入地址正規化函式
from data_processor import normalize_taiwan_address

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

def batch_import_expenses(df: pd.DataFrame):
    """
    批次匯入【每月/變動費用】的核心邏輯 (已為 PostgreSQL 優化)。
    """
    success_count = 0
    failed_records = []
    conn = database.get_db_connection()
    if not conn:
        error_df = df.copy()
        error_df['錯誤原因'] = "無法連接到資料庫"
        return 0, error_df
        
    try:
        with conn.cursor() as cursor:
            # 【核心修改】讀取更多地址欄位，並建立多個 mapping
            dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, original_address, normalized_address FROM "Dormitories"')
            original_addr_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
            normalized_addr_map = {d['normalized_address']: d['id'] for _, d in dorms_df.iterrows()}
            
            meters_df = _execute_query_to_dataframe(conn, 'SELECT id, dorm_id, meter_number FROM "Meters"')
            meters_map = {(row['dorm_id'], row['meter_number']): row['id'] for _, row in meters_df.iterrows()}

            for index, row in df.iterrows():
                try:
                    original_address = row.get('宿舍地址')
                    if not original_address or pd.isna(original_address):
                        raise ValueError("宿舍地址為空")

                    # 【核心修改】智慧型地址比對邏輯
                    dorm_id = None
                    addr_stripped = str(original_address).strip()
                    # 階段一：精確比對
                    if addr_stripped in original_addr_map:
                        dorm_id = original_addr_map[addr_stripped]
                    elif addr_stripped in normalized_addr_map:
                        dorm_id = normalized_addr_map[addr_stripped]
                    else:
                        # 階段二：模糊比對 (正規化後比對)
                        normalized_input = normalize_taiwan_address(addr_stripped)['full']
                        if normalized_input in normalized_addr_map:
                            dorm_id = normalized_addr_map[normalized_input]

                    if not dorm_id:
                        raise ValueError(f"在資料庫中找不到對應的宿舍地址: {original_address}")

                    meter_id = None
                    meter_number = row.get('對應錶號')
                    if meter_number and pd.notna(meter_number):
                        meter_number = str(meter_number).strip()
                        meter_key = (dorm_id, meter_number)
                        if meter_key in meters_map:
                            meter_id = meters_map[meter_key]
                        else:
                            raise ValueError(f"在宿舍 '{original_address}' 中找不到錶號為 '{meter_number}' 的紀錄")
                    
                    details = {
                        "dorm_id": dorm_id, "meter_id": meter_id,
                        "bill_type": str(row.get('費用類型')).strip(),
                        "amount": int(pd.to_numeric(row.get('帳單金額'), errors='coerce')),
                        "bill_start_date": pd.to_datetime(row.get('帳單起始日'), errors='coerce').strftime('%Y-%m-%d'),
                        "bill_end_date": pd.to_datetime(row.get('帳單結束日'), errors='coerce').strftime('%Y-%m-%d'),
                        "is_invoiced": True if str(row.get('是否已請款')).strip().upper() in ['Y', 'TRUE', 'V', '是', '1'] else False,
                        "notes": str(row.get('備註', ''))
                    }
                    
                    query = 'SELECT id FROM "UtilityBills" WHERE dorm_id = %s AND bill_type = %s AND bill_start_date = %s AND amount = %s'
                    params = [details['dorm_id'], details['bill_type'], details['bill_start_date'], details['amount']]
                    
                    if meter_id:
                        query += " AND meter_id = %s"
                        params.append(meter_id)
                    else:
                        query += " AND meter_id IS NULL"
                    
                    cursor.execute(query, tuple(params))
                    existing = cursor.fetchone()

                    if existing:
                        fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
                        values = list(details.values()) + [existing['id']]
                        update_sql = f'UPDATE "UtilityBills" SET {fields} WHERE id = %s'
                        cursor.execute(update_sql, tuple(values))
                    else:
                        columns = ', '.join(f'"{k}"' for k in details.keys())
                        placeholders = ', '.join(['%s'] * len(details))
                        insert_sql = f'INSERT INTO "UtilityBills" ({columns}) VALUES ({placeholders})'
                        cursor.execute(insert_sql, tuple(details.values()))

                    success_count += 1
                except Exception as row_error:
                    row['錯誤原因'] = str(row_error)
                    failed_records.append(row)

        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"批次匯入每月費用時發生嚴重錯誤: {e}")
    finally:
        if conn: conn.close()

    return success_count, pd.DataFrame(failed_records)


def batch_import_annual_expenses(df: pd.DataFrame):
    """
    批次匯入【年度/長期】費用的核心邏輯 (已為 PostgreSQL 優化)。
    """
    success_count = 0
    failed_records = []
    conn = database.get_db_connection()
    if not conn:
        error_df = df.copy()
        error_df['錯誤原因'] = "無法連接到資料庫"
        return 0, error_df

    try:
        with conn.cursor() as cursor:
            # 【核心修改】讀取更多地址欄位，並建立多個 mapping
            dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, original_address, normalized_address FROM "Dormitories"')
            original_addr_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
            normalized_addr_map = {d['normalized_address']: d['id'] for _, d in dorms_df.iterrows()}
            
            for index, row in df.iterrows():
                try:
                    original_address = row.get('宿舍地址')
                    if not original_address or pd.isna(original_address):
                        raise ValueError("宿舍地址為空")
                        
                    # 【核心修改】智慧型地址比對邏輯
                    dorm_id = None
                    addr_stripped = str(original_address).strip()
                    if addr_stripped in original_addr_map:
                        dorm_id = original_addr_map[addr_stripped]
                    elif addr_stripped in normalized_addr_map:
                        dorm_id = normalized_addr_map[addr_stripped]
                    else:
                        normalized_input = normalize_taiwan_address(addr_stripped)['full']
                        if normalized_input in normalized_addr_map:
                            dorm_id = normalized_addr_map[normalized_input]

                    if not dorm_id:
                        raise ValueError(f"在資料庫中找不到對應的宿舍地址: {original_address}")
                        
                    expense_item = row.get('費用項目')
                    total_amount = pd.to_numeric(row.get('總金額'), errors='coerce')

                    if not all([expense_item, pd.notna(total_amount)]):
                        raise ValueError("必填欄位(費用項目,總金額)有缺漏或格式錯誤")
                        
                    details = {
                        "dorm_id": dorm_id, "expense_item": str(expense_item).strip(),
                        "payment_date": pd.to_datetime(row.get('支付日期')).strftime('%Y-%m-%d'),
                        "total_amount": int(total_amount),
                        "amortization_start_month": pd.to_datetime(row.get('攤提起始月')).strftime('%Y-%m'),
                        "amortization_end_month": pd.to_datetime(row.get('攤提結束月')).strftime('%Y-%m'),
                        "notes": str(row.get('備註', ''))
                    }
                    
                    query = 'SELECT id FROM "AnnualExpenses" WHERE dorm_id = %s AND expense_item = %s AND payment_date = %s'
                    cursor.execute(query, (dorm_id, details['expense_item'], details['payment_date']))
                    existing = cursor.fetchone()
                    
                    if existing:
                        fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
                        values = list(details.values()) + [existing['id']]
                        update_sql = f'UPDATE "AnnualExpenses" SET {fields} WHERE id = %s'
                        cursor.execute(update_sql, tuple(values))
                    else:
                        columns = ', '.join(f'"{k}"' for k in details.keys())
                        placeholders = ', '.join(['%s'] * len(details))
                        insert_sql = f'INSERT INTO "AnnualExpenses" ({columns}) VALUES ({placeholders})'
                        cursor.execute(insert_sql, tuple(details.values()))

                    success_count += 1
                except Exception as row_error:
                    row['錯誤原因'] = str(row_error)
                    failed_records.append(row)
        
        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"批次匯入年度費用時發生嚴重錯誤: {e}")
    finally:
        if conn: conn.close()
            
    return success_count, pd.DataFrame(failed_records)