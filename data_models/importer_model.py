import pandas as pd
import database
import json
from data_processor import normalize_taiwan_address
import numpy as np

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

def clean_nan_for_json(data_dict):
    """遞迴地將字典中的 NaN, NaT 等值轉換為 None。"""
    for key, value in data_dict.items():
        if isinstance(value, dict):
            clean_nan_for_json(value)
        elif pd.isna(value):
            data_dict[key] = None
    return data_dict

def batch_import_expenses(df: pd.DataFrame):
    """
    【v1.3 修改版】批次匯入【每月/變動費用】的核心邏輯。
    修正「備註」欄位存為 nan 的問題。
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

                    meter_id = None
                    meter_number = row.get('對應錶號')
                    if meter_number and pd.notna(meter_number):
                        meter_number = str(meter_number).strip()
                        meter_key = (dorm_id, meter_number)
                        if meter_key in meters_map:
                            meter_id = meters_map[meter_key]
                        else:
                            raise ValueError(f"在宿舍 '{original_address}' 中找不到錶號為 '{meter_number}' 的紀錄")
                    
                    def to_bool(val):
                        if pd.isna(val): return False
                        return str(val).strip().upper() in ['TRUE', '1', 'Y', 'YES', '是']

                    usage_val = pd.to_numeric(row.get('用量(度/噸) (選填)'), errors='coerce')
                    usage_amount = usage_val if pd.notna(usage_val) else None
                    
                    notes_val = row.get('備註')
                    notes = str(notes_val).strip() if pd.notna(notes_val) and str(notes_val).strip() else None

                    details = {
                        "dorm_id": dorm_id, "meter_id": meter_id,
                        "bill_type": str(row.get('費用類型', '')).strip(),
                        "amount": int(pd.to_numeric(row.get('帳單金額'), errors='coerce')),
                        "usage_amount": usage_amount,
                        "bill_start_date": pd.to_datetime(row.get('帳單起始日'), errors='coerce').strftime('%Y-%m-%d'),
                        "bill_end_date": pd.to_datetime(row.get('帳單結束日'), errors='coerce').strftime('%Y-%m-%d'),
                        "payer": str(row.get('支付方', '我司')).strip(),
                        "is_pass_through": to_bool(row.get('是否為代收代付')),
                        "is_invoiced": to_bool(row.get('是否已請款')),
                        "notes": notes
                    }
                    
                    query = 'SELECT id FROM "UtilityBills" WHERE dorm_id = %s AND bill_type = %s AND bill_start_date = %s'
                    params = [details['dorm_id'], details['bill_type'], details['bill_start_date']]
                    
                    if meter_id:
                        query += " AND meter_id = %s"
                        params.append(meter_id)
                    else:
                        query += " AND meter_id IS NULL"
                        
                    cursor.execute(query, tuple(params))
                    existing = cursor.fetchone()

                    if existing:
                        existing_id = existing['id']
                        fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
                        values = list(details.values()) + [existing_id]
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

def batch_import_building_permits(df: pd.DataFrame):
    """
    批次匯入【建物申報】的核心邏輯。
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
            dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, original_address, normalized_address FROM "Dormitories"')
            original_addr_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
            normalized_addr_map = {d['normalized_address']: d['id'] for _, d in dorms_df.iterrows()}

            for index, row in df.iterrows():
                try:
                    original_address = row.get('宿舍地址')
                    if not original_address or pd.isna(original_address):
                        raise ValueError("宿舍地址為空")

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
                    
                    # 處理布林值
                    def to_bool(val):
                        if pd.isna(val): return None
                        # 處理 'TRUE', 'FALSE', 1, 0, 'Y', 'N' 等情況
                        return str(val).strip().upper() in ['TRUE', '1', 'Y', 'YES', '是']

                    permit_details = {
                        "architect_name": row.get('建築師'),
                        "gov_document_exists": to_bool(row.get('政府是否發文')),
                        "next_declaration_start": pd.to_datetime(row.get('下次申報起日期')).strftime('%Y-%m-%d') if pd.notna(row.get('下次申報起日期')) else None,
                        "next_declaration_end": pd.to_datetime(row.get('下次申報迄日期')).strftime('%Y-%m-%d') if pd.notna(row.get('下次申報迄日期')) else None,
                        "declaration_item": row.get('申報項目'),
                        "area_legal": row.get('申報面積（合法）'),
                        "area_total": row.get('申報面積（合法加違規）'),
                        "amount_pre_tax": int(pd.to_numeric(row.get('金額（未稅）'), errors='coerce')) if pd.notna(row.get('金額（未稅）')) else None,
                        "usage_license_exists": to_bool(row.get('使用執照有無')),
                        "property_deed_exists": to_bool(row.get('權狀有無')),
                        "landlord_id_exists": to_bool(row.get('房東證件有無')),
                        "improvements_made": to_bool(row.get('現場是否改善')),
                        "insurance_exists": to_bool(row.get('保險有無')),
                        "submission_date": pd.to_datetime(row.get('申報文件送出日期')).strftime('%Y-%m-%d') if pd.notna(row.get('申報文件送出日期')) else None,
                        "registered_mail_date": pd.to_datetime(row.get('掛號憑證日期')).strftime('%Y-%m-%d') if pd.notna(row.get('掛號憑證日期')) else None,
                        "certificate_received_date": pd.to_datetime(row.get('收到憑證日期')).strftime('%Y-%m-%d') if pd.notna(row.get('收到憑證日期')) else None,
                        "invoice_date": pd.to_datetime(row.get('請款日')).strftime('%Y-%m-%d') if pd.notna(row.get('請款日')) else None,
                        "approval_start_date": pd.to_datetime(row.get('此次申報核准起日期')).strftime('%Y-%m-%d') if pd.notna(row.get('此次申報核准起日期')) else None,
                        "approval_end_date": pd.to_datetime(row.get('此次申報核准迄日期')).strftime('%Y-%m-%d') if pd.notna(row.get('此次申報核准迄日期')) else None
                    }

                    expense_details = {
                        "dorm_id": dorm_id,
                        "expense_item": f"建物申報-{permit_details['declaration_item']}" if permit_details.get('declaration_item') else "建物申報",
                        "payment_date": pd.to_datetime(row.get('支付日期')).strftime('%Y-%m-%d') if pd.notna(row.get('支付日期')) else None,
                        "total_amount": int(pd.to_numeric(row.get('總金額（含稅）'), errors='coerce')) if pd.notna(row.get('總金額（含稅）')) else None,
                        "amortization_start_month": pd.to_datetime(row.get('攤提起始月')).strftime('%Y-%m') if pd.notna(row.get('攤提起始月')) else None,
                        "amortization_end_month": pd.to_datetime(row.get('攤提結束月')).strftime('%Y-%m') if pd.notna(row.get('攤提結束月')) else None,
                    }

                    # 【核心修改】在轉換為 JSON 前，清洗 NaN 值
                    cleaned_permit_details = clean_nan_for_json(permit_details)
                    details_json = json.dumps(cleaned_permit_details, ensure_ascii=False)

                    compliance_sql = 'INSERT INTO "ComplianceRecords" (dorm_id, record_type, details) VALUES (%s, %s, %s) RETURNING id;'
                    cursor.execute(compliance_sql, (dorm_id, '建物申報', details_json))
                    new_compliance_id = cursor.fetchone()['id']

                    expense_details['compliance_record_id'] = new_compliance_id
                    expense_columns = ', '.join(f'"{k}"' for k in expense_details.keys())
                    expense_placeholders = ', '.join(['%s'] * len(expense_details))
                    expense_sql = f'INSERT INTO "AnnualExpenses" ({expense_columns}) VALUES ({expense_placeholders})'
                    cursor.execute(expense_sql, tuple(expense_details.values()))
                    
                    success_count += 1
                except Exception as row_error:
                    row['錯誤原因'] = str(row_error)
                    failed_records.append(row)
        
        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"批次匯入建物申報時發生嚴重錯誤: {e}")
    finally:
        if conn: conn.close()
            
    return success_count, pd.DataFrame(failed_records)

def batch_import_accommodation(df: pd.DataFrame):
    """
    【v1.4 修改版】批次匯入【住宿分配/異動】的核心邏輯。
    修正日期運算錯誤。
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
            # 預先載入所有宿舍和房間資料，提高效率
            dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, original_address, normalized_address FROM "Dormitories"')
            original_addr_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
            normalized_addr_map = {d['normalized_address']: d['id'] for _, d in dorms_df.iterrows()}
            
            rooms_df = _execute_query_to_dataframe(conn, 'SELECT id, dorm_id, room_number FROM "Rooms"')
            room_map = {(r['dorm_id'], r['room_number']): r['id'] for _, r in rooms_df.iterrows()}

            for index, row in df.iterrows():
                try:
                    # --- 1. 智慧識別工人 ---
                    employer = str(row.get('雇主', '')).strip()
                    name = str(row.get('姓名', '')).strip()
                    passport = str(row.get('護照號碼 (選填)', '')).strip()
                    if not employer or not name:
                        raise ValueError("雇主和姓名為必填欄位")

                    worker_id = None
                    if passport:
                        unique_id = f"{employer}_{name}_{passport}"
                        cursor.execute('SELECT unique_id FROM "Workers" WHERE unique_id = %s', (unique_id,))
                        worker_record = cursor.fetchone()
                        if worker_record:
                            worker_id = worker_record['unique_id']
                        else:
                             raise ValueError(f"找不到工人: {unique_id}")
                    else:
                        cursor.execute(
                            'SELECT unique_id FROM "Workers" WHERE employer_name = %s AND worker_name = %s',
                            (employer, name)
                        )
                        workers_found = cursor.fetchall()
                        if len(workers_found) == 1:
                            worker_id = workers_found[0]['unique_id']
                        elif len(workers_found) == 0:
                            raise ValueError(f"找不到工人: {employer}_{name}")
                        else:
                            raise ValueError(f"找到 {len(workers_found)} 位同名工人，請提供護照號碼以作區分")
                    
                    if not worker_id:
                        raise ValueError("無法確定唯一的工人紀錄")

                    # --- 2. 識別或建立宿舍與房間 ---
                    address = row.get('實際住宿地址')
                    room_number_str = str(row.get('房號')).strip()
                    if not address or pd.isna(address) or not room_number_str:
                        raise ValueError("實際住宿地址和房號為必填欄位")
                    addr_stripped = str(address).strip()
                    dorm_id = original_addr_map.get(addr_stripped) or normalized_addr_map.get(normalize_taiwan_address(addr_stripped)['full'])
                    if not dorm_id:
                        raise ValueError(f"找不到宿舍地址: {address}")
                    room_key = (dorm_id, room_number_str)
                    new_room_id = room_map.get(room_key)
                    if not new_room_id:
                        room_details = {'dorm_id': dorm_id, 'room_number': room_number_str, 'capacity': 4, 'gender_policy': '可混住'}
                        cols = ', '.join(f'"{k}"' for k in room_details.keys())
                        vals = ', '.join(['%s'] * len(room_details))
                        cursor.execute(f'INSERT INTO "Rooms" ({cols}) VALUES ({vals}) RETURNING id', tuple(room_details.values()))
                        new_room_id = cursor.fetchone()['id']
                        room_map[room_key] = new_room_id

                    # --- 3. 執行智慧判斷與更新邏輯 ---
                    move_in_date_input = row.get('入住日 (換宿/指定日期時填寫)')
                    cursor.execute("""
                        SELECT ah.id, r.room_number, ah.room_id, ah.start_date
                        FROM "AccommodationHistory" ah JOIN "Rooms" r ON ah.room_id = r.id
                        WHERE ah.worker_unique_id = %s AND ah.end_date IS NULL
                        ORDER BY ah.start_date DESC, ah.id DESC LIMIT 1
                    """, (worker_id,))
                    latest_history = cursor.fetchone()
                    if latest_history and latest_history['room_id'] == new_room_id:
                        continue
                    if latest_history and latest_history['room_number'] == '[未分配房間]' and (pd.isna(move_in_date_input) or not move_in_date_input):
                        cursor.execute('UPDATE "AccommodationHistory" SET room_id = %s WHERE id = %s', (new_room_id, latest_history['id']))
                    else:
                        effective_date = pd.to_datetime(move_in_date_input).date() if pd.notna(move_in_date_input) and move_in_date_input else date.today()
                        if latest_history:
                            # --- 改用 timedelta 計算，並移除多餘的 .date() ---
                            end_date = effective_date - timedelta(days=1)
                            cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE id = %s', (end_date, latest_history['id']))
                        cursor.execute('INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date) VALUES (%s, %s, %s)', (worker_id, new_room_id, effective_date))
                    
                    # --- 4. 更新 Workers 表的快取和標記 ---
                    cursor.execute('UPDATE "Workers" SET room_id = %s, data_source = %s WHERE unique_id = %s', (new_room_id, '手動調整', worker_id))
                    success_count += 1
                
                except Exception as row_error:
                    row['錯誤原因'] = str(row_error)
                    failed_records.append(row)

        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"批次匯入住宿資料時發生嚴重錯誤: {e}")
        remaining_rows = df.iloc[len(failed_records):].copy()
        remaining_rows['錯誤原因'] = f"系統層級錯誤: {e}"
        failed_records.extend(remaining_rows.to_dict('records'))

    finally:
        if conn: conn.close()

    return success_count, pd.DataFrame(failed_records)

def batch_import_leases(df: pd.DataFrame):
    """
    【v1.1 修改版】批次匯入【房租合約】的核心邏輯。
    新增回傳重複的紀錄。
    """
    success_count = 0
    failed_records = []
    skipped_records = [] # 新增一個列表來存放被跳過的紀錄
    conn = database.get_db_connection()
    if not conn:
        error_df = df.copy()
        error_df['錯誤原因'] = "無法連接到資料庫"
        return 0, error_df, pd.DataFrame()

    try:
        with conn.cursor() as cursor:
            dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, original_address, normalized_address FROM "Dormitories"')
            original_addr_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
            normalized_addr_map = {d['normalized_address']: d['id'] for _, d in dorms_df.iterrows()}
            
            for index, row in df.iterrows():
                try:
                    address = row.get('宿舍地址')
                    if not address or pd.isna(address):
                        raise ValueError("宿舍地址為空")
                        
                    addr_stripped = str(address).strip()
                    dorm_id = original_addr_map.get(addr_stripped) or normalized_addr_map.get(normalize_taiwan_address(addr_stripped)['full'])
                    if not dorm_id:
                        raise ValueError(f"在資料庫中找不到對應的宿舍地址: {address}")

                    def to_bool(val):
                        if pd.isna(val): return False
                        return str(val).strip().upper() in ['TRUE', '1', 'Y', 'YES', '是']

                    details = {
                        "dorm_id": dorm_id,
                        "lease_start_date": pd.to_datetime(row.get('合約起始日')).strftime('%Y-%m-%d') if pd.notna(row.get('合約起始日')) else None,
                        "lease_end_date": pd.to_datetime(row.get('合約截止日')).strftime('%Y-%m-%d') if pd.notna(row.get('合約截止日')) else None,
                        "monthly_rent": int(pd.to_numeric(row.get('月租金'), errors='coerce')) if pd.notna(row.get('月租金')) else None,
                        "deposit": int(pd.to_numeric(row.get('押金'), errors='coerce')) if pd.notna(row.get('押金')) else None,
                        "utilities_included": to_bool(row.get('租金含水電')),
                    }
                    
                    cursor.execute(
                        'SELECT id FROM "Leases" WHERE dorm_id = %s AND lease_start_date = %s AND monthly_rent = %s',
                        (details['dorm_id'], details['lease_start_date'], details['monthly_rent'])
                    )
                    if cursor.fetchone():
                        # --- 將跳過的紀錄加入 skipped_records ---
                        row['錯誤原因'] = "資料重複，已跳過"
                        skipped_records.append(row)
                        continue

                    columns = ', '.join(f'"{k}"' for k in details.keys())
                    placeholders = ', '.join(['%s'] * len(details))
                    sql = f'INSERT INTO "Leases" ({columns}) VALUES ({placeholders})'
                    cursor.execute(sql, tuple(details.values()))
                    success_count += 1
                
                except Exception as row_error:
                    row['錯誤原因'] = str(row_error)
                    failed_records.append(row)
        
        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"批次匯入房租合約時發生嚴重錯誤: {e}")
    finally:
        if conn: conn.close()
            
    # --- 回傳三個結果 ---
    return success_count, pd.DataFrame(failed_records), pd.DataFrame(skipped_records)

def batch_import_fire_safety(df: pd.DataFrame):
    """
    批次匯入【消防安檢】的核心邏輯。
    """
    success_count = 0
    failed_records = []
    skipped_records = []
    # finance_model.add_compliance_record 函式需要從 data_models 導入
    from . import finance_model

    conn = database.get_db_connection()
    if not conn:
        error_df = df.copy()
        error_df['錯誤原因'] = "無法連接到資料庫"
        return 0, error_df, pd.DataFrame()

    try:
        with conn.cursor() as cursor:
            dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, original_address, normalized_address FROM "Dormitories"')
            original_addr_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
            normalized_addr_map = {d['normalized_address']: d['id'] for _, d in dorms_df.iterrows()}
            
            for index, row in df.iterrows():
                try:
                    address = row.get('宿舍地址')
                    if not address or pd.isna(address):
                        raise ValueError("宿舍地址為空")
                    
                    addr_stripped = str(address).strip()
                    dorm_id = original_addr_map.get(addr_stripped) or normalized_addr_map.get(normalize_taiwan_address(addr_stripped)['full'])
                    if not dorm_id:
                        raise ValueError(f"在資料庫中找不到對應的宿舍地址: {address}")

                    # 將 Excel 日期轉換為字串，處理空值
                    def format_date(date_val):
                        if pd.isna(date_val): return None
                        return pd.to_datetime(date_val).strftime('%Y-%m-%d')

                    payment_date = pd.to_datetime(row.get('支付日期')).date() if pd.notna(row.get('支付日期')) else None
                    total_amount = int(pd.to_numeric(row.get('支付總金額'), errors='coerce')) if pd.notna(row.get('支付總金額')) else 0
                    
                    # 檢查重複：如果同一宿舍、同一支付日期、同一金額的消防安檢已存在，則跳過
                    cursor.execute(
                        'SELECT id FROM "AnnualExpenses" WHERE dorm_id = %s AND payment_date = %s AND total_amount = %s AND expense_item = %s',
                        (dorm_id, payment_date, total_amount, '消防安檢')
                    )
                    if cursor.fetchone():
                        row['錯誤原因'] = "資料重複，已跳過"
                        skipped_records.append(row)
                        continue

                    amort_start = pd.to_datetime(row.get('攤提起始日')).date() if pd.notna(row.get('攤提起始日')) else payment_date
                    amort_period = int(pd.to_numeric(row.get('攤提月數'), errors='coerce')) if pd.notna(row.get('攤提月數')) else 12
                    amort_end_obj = amort_start + relativedelta(months=amort_period - 1)
                    
                    # 準備傳遞給後端函式的資料
                    record_details = {"dorm_id": dorm_id, "details": {
                        "vendor": row.get('支出對象/廠商'),
                        "declaration_item": row.get('申報項目'),
                        "submission_date": format_date(row.get('申報文件送出日期')),
                        "registered_mail_date": format_date(row.get('掛號憑證日期')),
                        "certificate_date": format_date(row.get('收到憑證日期')),
                        "next_declaration_start": format_date(row.get('下次申報起始日期')),
                        "next_declaration_end": format_date(row.get('下次申報結束日期')),
                        "approval_start_date": format_date(row.get('此次申報核准起始日期')),
                        "approval_end_date": format_date(row.get('此次申報核准結束日期')),
                    }}
                    
                    expense_details = {
                        "dorm_id": dorm_id,
                        "expense_item": str(row.get('申報項目')).strip() or '消防安檢',
                        "payment_date": payment_date,
                        "total_amount": total_amount,
                        "amortization_start_month": amort_start.strftime('%Y-%m'),
                        "amortization_end_month": amort_end_obj.strftime('%Y-%m')
                    }

                    # 呼叫通用的 add_compliance_record 函式
                    success, message, _ = finance_model.add_compliance_record('消防安檢', record_details, expense_details)
                    if success:
                        success_count += 1
                    else:
                        raise Exception(message)

                except Exception as row_error:
                    row['錯誤原因'] = str(row_error)
                    failed_records.append(row)
        
        # 注意：這裡不執行 conn.commit()，因為 add_compliance_record 內部已經處理了交易
    except Exception as e:
        # conn.rollback() 已在 add_compliance_record 內部處理
        print(f"批次匯入消防安檢時發生嚴重錯誤: {e}")
    finally:
        if conn: conn.close()

    return success_count, pd.DataFrame(failed_records), pd.DataFrame(skipped_records)