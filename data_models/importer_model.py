import pandas as pd
import database

def batch_import_expenses(df: pd.DataFrame):
    """
    批次匯入【每月/變動費用】的核心邏輯 (已為 PostgreSQL 優化)。
    """
    success_count = 0
    failed_records = []
    conn = database.get_db_connection()
    if not conn:
        # 建立一個包含錯誤原因的 DataFrame 回傳
        error_df = df.copy()
        error_df['錯誤原因'] = "無法連接到資料庫"
        return 0, error_df
        
    try:
        with conn.cursor() as cursor:
            # 一次性讀取所有需要的宿舍和電錶資料，提高效率
            dorms_df = pd.read_sql_query('SELECT id, original_address FROM "Dormitories"', conn)
            dorms_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
            
            meters_df = pd.read_sql_query('SELECT id, dorm_id, meter_number FROM "Meters"', conn)
            meters_map = {(row['dorm_id'], row['meter_number']): row['id'] for _, row in meters_df.iterrows()}

            for index, row in df.iterrows():
                try:
                    original_address = row.get('宿舍地址')
                    if not original_address or pd.isna(original_address):
                        row['錯誤原因'] = "宿舍地址為空"
                        failed_records.append(row)
                        continue

                    dorm_id = dorms_map.get(str(original_address).strip())
                    if not dorm_id:
                        row['錯誤原因'] = f"在資料庫中找不到對應的宿舍地址: {original_address}"
                        failed_records.append(row)
                        continue

                    meter_id = None
                    meter_number = row.get('對應錶號')
                    if meter_number and pd.notna(meter_number):
                        meter_number = str(meter_number).strip()
                        meter_key = (dorm_id, meter_number)
                        if meter_key in meters_map:
                            meter_id = meters_map[meter_key]
                        else:
                            row['錯誤原因'] = f"在宿舍 '{original_address}' 中找不到錶號為 '{meter_number}' 的紀錄"
                            failed_records.append(row)
                            continue
                    
                    details = {
                        "dorm_id": dorm_id, "meter_id": meter_id,
                        "bill_type": str(row.get('費用類型')).strip(),
                        "amount": int(pd.to_numeric(row.get('帳單金額'), errors='coerce')),
                        "bill_start_date": pd.to_datetime(row.get('帳單起始日'), errors='coerce').strftime('%Y-%m-%d'),
                        "bill_end_date": pd.to_datetime(row.get('帳單結束日'), errors='coerce').strftime('%Y-%m-%d'),
                        "is_invoiced": True if str(row.get('是否已請款')).strip().upper() in ['Y', 'TRUE', 'V', '是', '1'] else False,
                        "notes": str(row.get('備註', ''))
                    }
                    
                    # Upsert 邏輯 (Update or Insert)
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
                        # 更新
                        fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
                        values = list(details.values()) + [existing['id']]
                        update_sql = f'UPDATE "UtilityBills" SET {fields} WHERE id = %s'
                        cursor.execute(update_sql, tuple(values))
                    else:
                        # 新增
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
            dorms_df = pd.read_sql_query('SELECT id, original_address FROM "Dormitories"', conn)
            dorms_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
            
            for index, row in df.iterrows():
                try:
                    original_address = row.get('宿舍地址')
                    expense_item = row.get('費用項目')
                    total_amount = pd.to_numeric(row.get('總金額'), errors='coerce')

                    if not all([original_address, expense_item, pd.notna(total_amount)]):
                        raise ValueError("必填欄位(地址,項目,總金額)有缺漏或格式錯誤")

                    dorm_id = dorms_map.get(str(original_address).strip())
                    if not dorm_id:
                        raise ValueError(f"在資料庫中找不到對應的宿舍地址: {original_address}")
                        
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