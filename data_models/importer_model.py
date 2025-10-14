import pandas as pd
import database
import json
from data_processor import normalize_taiwan_address
import numpy as np
from datetime import date
from dateutil.relativedelta import relativedelta
from . import finance_model

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
    【v1.4 修正版】批次匯入【每月/變動費用】的核心邏輯。
    實現「有就更新，沒有就新增」(Upsert) 的功能，並修正讀取「用量」欄位的名稱。
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

                    # 【核心修改】修正讀取的欄位名稱，移除「 (選填)」
                    usage_val = pd.to_numeric(row.get('用量(度/噸)'), errors='coerce')
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
                        # 如果紀錄已存在，則執行 UPDATE 來覆蓋
                        existing_id = existing['id']
                        fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
                        values = list(details.values()) + [existing_id]
                        update_sql = f'UPDATE "UtilityBills" SET {fields} WHERE id = %s'
                        cursor.execute(update_sql, tuple(values))
                    else:
                        # 如果紀錄不存在，則執行 INSERT 來新增
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
    【v1.1 修改版】批次匯入【建物申報】的核心邏輯。
    新增重複檢查，若紀錄已存在則會跳過。
    """
    success_count = 0
    failed_records = []
    skipped_records = []  # 新增一個列表來存放跳過的紀錄
    conn = database.get_db_connection()
    if not conn:
        error_df = df.copy()
        error_df['錯誤原因'] = "無法連接到資料庫"
        return 0, error_df, pd.DataFrame() # 修改回傳值

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
                    
                    def to_bool(val):
                        if pd.isna(val): return None
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

                    # --- 【核心修改 1】新增重複檢查 ---
                    approval_start_date_str = permit_details.get("approval_start_date")
                    if not approval_start_date_str:
                        raise ValueError("「此次申報核准起日期」為判斷重複的必要欄位，不可為空")

                    check_query = """
                        SELECT id FROM "ComplianceRecords"
                        WHERE dorm_id = %s
                          AND record_type = '建物申報'
                          AND details ->> 'declaration_item' = %s
                          AND details ->> 'approval_start_date' = %s
                    """
                    cursor.execute(check_query, (dorm_id, permit_details.get("declaration_item"), approval_start_date_str))
                    
                    if cursor.fetchone():
                        row['錯誤原因'] = "資料重複，已跳過"
                        skipped_records.append(row)
                        continue # 跳到下一筆資料

                    # --- 若不重複，才執行新增 ---
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
            
    return success_count, pd.DataFrame(failed_records), pd.DataFrame(skipped_records) # 修改回傳值

def batch_import_accommodation(df: pd.DataFrame):
    """
    【v1.6 修正版】批次匯入【住宿分配/異動】的核心邏輯。
    修正日期計算的 TypeError。
    """
    success_count = 0
    failed_records = []
    conn = database.get_db_connection()
    if not conn:
        error_df = df.copy()
        error_df['錯誤原因'] = "無法連接到資料庫"
        return 0, error_df
        
    try:
        from datetime import date, timedelta # 匯入標準時間差函式庫

        with conn.cursor() as cursor:
            dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, original_address, normalized_address FROM "Dormitories"')
            original_addr_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
            normalized_addr_map = {d['normalized_address']: d['id'] for _, d in dorms_df.iterrows()}
            
            rooms_df = _execute_query_to_dataframe(conn, 'SELECT id, dorm_id, room_number FROM "Rooms"')
            room_map = {(r['dorm_id'], r['room_number']): r['id'] for _, r in rooms_df.iterrows()}

            for index, row in df.iterrows():
                try:
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
                    
                    bed_number_val = row.get('床位編號 (選填)')
                    bed_number = str(bed_number_val).strip() if pd.notna(bed_number_val) and str(bed_number_val).strip() else None

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
                        cursor.execute('UPDATE "AccommodationHistory" SET room_id = %s, bed_number = %s WHERE id = %s', (new_room_id, bed_number, latest_history['id']))
                    else:
                        effective_date = pd.to_datetime(move_in_date_input).date() if pd.notna(move_in_date_input) and move_in_date_input else date.today()
                        if latest_history:
                            # 【核心修改】使用 timedelta 計算
                            end_date = effective_date - timedelta(days=1)
                            cursor.execute('UPDATE "AccommodationHistory" SET end_date = %s WHERE id = %s', (end_date, latest_history['id']))
                        
                        cursor.execute(
                            'INSERT INTO "AccommodationHistory" (worker_unique_id, room_id, start_date, bed_number) VALUES (%s, %s, %s, %s)',
                            (worker_id, new_room_id, effective_date, bed_number)
                        )
                    
                    cursor.execute('UPDATE "Workers" SET data_source = %s WHERE unique_id = %s', ('手動調整', worker_id))
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
    skipped_records = [] 
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
            
            # --- 【核心修改 1】預載廠商資料 ---
            vendors_df = _execute_query_to_dataframe(conn, 'SELECT id, vendor_name FROM "Vendors"')
            vendor_map = {v['vendor_name']: v['id'] for _, v in vendors_df.iterrows()}
            
            for index, row in df.iterrows():
                try:
                    address = row.get('宿舍地址')
                    if not address or pd.isna(address):
                        raise ValueError("宿舍地址為空")
                        
                    addr_stripped = str(address).strip()
                    dorm_id = original_addr_map.get(addr_stripped) or normalized_addr_map.get(normalize_taiwan_address(addr_stripped)['full'])
                    if not dorm_id:
                        raise ValueError(f"在資料庫中找不到對應的宿舍地址: {address}")

                    # --- 【核心修改 2】找不到廠商時，明確拋出錯誤 ---
                    vendor_id = None
                    vendor_name = row.get('房東/廠商')
                    if pd.notna(vendor_name) and str(vendor_name).strip():
                        vendor_name_stripped = str(vendor_name).strip()
                        vendor_id = vendor_map.get(vendor_name_stripped)
                        # 如果 Excel 中有填寫廠商，但在資料庫找不到，就報錯
                        if not vendor_id:
                            raise ValueError(f"在廠商資料庫中找不到廠商: '{vendor_name_stripped}'，請先新增。")

                    def to_bool(val):
                        if pd.isna(val): return False
                        return str(val).strip().upper() in ['TRUE', '1', 'Y', 'YES', '是']
                    
                    # --- 【核心修改 3】將新欄位加入 details ---
                    details = {
                        "dorm_id": dorm_id,
                        "vendor_id": vendor_id, # <-- 新增
                        "contract_item": row.get('合約項目', '房租'),
                        "lease_start_date": pd.to_datetime(row.get('合約起始日')).strftime('%Y-%m-%d') if pd.notna(row.get('合約起始日')) else None,
                        "lease_end_date": pd.to_datetime(row.get('合約截止日')).strftime('%Y-%m-%d') if pd.notna(row.get('合約截止日')) else None,
                        "monthly_rent": int(pd.to_numeric(row.get('月租金'), errors='coerce')) if pd.notna(row.get('月租金')) else None,
                        "deposit": int(pd.to_numeric(row.get('押金'), errors='coerce')) if pd.notna(row.get('押金')) else None,
                        "utilities_included": to_bool(row.get('租金含水電')),
                        "notes": str(row.get('備註', '')) # <-- 新增
                    }
                    
                    cursor.execute(
                        'SELECT id FROM "Leases" WHERE dorm_id = %s AND contract_item = %s AND lease_start_date = %s AND monthly_rent = %s',
                        (details['dorm_id'], details['contract_item'], details['lease_start_date'], details['monthly_rent'])
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

def batch_import_other_income(df: pd.DataFrame):
    """
    【v1.2 房號報錯修正版】批次匯入【其他收入】的核心邏輯。
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
            
            rooms_df = _execute_query_to_dataframe(conn, 'SELECT id, dorm_id, room_number FROM "Rooms"')
            room_map = {(r['dorm_id'], str(r['room_number'])): r['id'] for _, r in rooms_df.iterrows()}
            
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
                        
                    room_id = None
                    room_number_val = row.get('房號 (選填)')
                    if pd.notna(room_number_val) and str(room_number_val).strip():
                        room_number_str = str(room_number_val).strip()
                        room_key = (dorm_id, room_number_str)
                        if room_key in room_map:
                            room_id = room_map[room_key]
                        else:
                            # --- 如果找不到房號，就直接拋出錯誤 ---
                            raise ValueError(f"在宿舍 '{original_address}' 中找不到房號 '{room_number_str}'")
                            
                    income_item = row.get('收入項目')
                    amount = pd.to_numeric(row.get('收入金額'), errors='coerce')
                    transaction_date = pd.to_datetime(row.get('收入日期'), errors='coerce')

                    if not all([income_item, pd.notna(amount), pd.notna(transaction_date)]):
                        raise ValueError("必填欄位(收入項目, 收入金額, 收入日期)有缺漏或格式錯誤")
                        
                    details = {
                        "dorm_id": dorm_id,
                        "room_id": room_id,
                        "income_item": str(income_item).strip(),
                        "transaction_date": transaction_date.strftime('%Y-%m-%d'),
                        "amount": int(amount),
                        "notes": str(row.get('備註', ''))
                    }
                    
                    query = 'SELECT id FROM "OtherIncome" WHERE dorm_id = %s AND income_item = %s AND transaction_date = %s'
                    cursor.execute(query, (dorm_id, details['income_item'], details['transaction_date']))
                    existing = cursor.fetchone()
                    
                    if existing:
                        fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
                        values = list(details.values()) + [existing['id']]
                        update_sql = f'UPDATE "OtherIncome" SET {fields} WHERE id = %s'
                        cursor.execute(update_sql, tuple(values))
                    else:
                        columns = ', '.join(f'"{k}"' for k in details.keys())
                        placeholders = ', '.join(['%s'] * len(details))
                        insert_sql = f'INSERT INTO "OtherIncome" ({columns}) VALUES ({placeholders})'
                        cursor.execute(insert_sql, tuple(details.values()))

                    success_count += 1
                except Exception as row_error:
                    row['錯誤原因'] = str(row_error)
                    failed_records.append(row)
        
        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"批次匯入其他收入時發生嚴重錯誤: {e}")
    finally:
        if conn: conn.close()
            
    return success_count, pd.DataFrame(failed_records)

def batch_import_dorms_and_rooms(df: pd.DataFrame):
    """
    【v1.1 修正版】批次匯入宿舍與房間的基本資料。
    採用「有就更新，沒有就新增」的邏輯。如果宿舍地址不存在，則直接報錯跳過。
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
            # 預載現有宿舍與房間資料以供比對
            dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, original_address, normalized_address FROM "Dormitories"')
            original_addr_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
            normalized_addr_map = {d['normalized_address']: d['id'] for _, d in dorms_df.iterrows()}
            
            rooms_df = _execute_query_to_dataframe(conn, 'SELECT id, dorm_id, room_number FROM "Rooms"')
            room_map = {(r['dorm_id'], str(r['room_number'])): r['id'] for _, r in rooms_df.iterrows()}

            # 使用 groupby 確保我們先處理完一個宿舍的所有房間再到下一個
            for address, group in df.groupby('宿舍地址'):
                dorm_id = None
                try:
                    # --- 步驟 1: 嚴格查找宿舍 ---
                    if not address or pd.isna(address):
                        raise ValueError("宿舍地址為空")

                    addr_stripped = str(address).strip()
                    dorm_id = original_addr_map.get(addr_stripped)
                    
                    if not dorm_id:
                        normalized_input = normalize_taiwan_address(addr_stripped)['full']
                        dorm_id = normalized_addr_map.get(normalized_input)

                    # --- 如果找不到 dorm_id，就拋出錯誤，而不是建立新的 ---
                    if not dorm_id:
                        raise ValueError(f"宿舍地址不存在: '{addr_stripped}'")

                    # --- 步驟 2: 遍歷該宿舍下的所有房間 ---
                    for _, row in group.iterrows():
                        try:
                            room_number = row.get('房號')
                            if not room_number or pd.isna(room_number):
                                continue # 如果沒有房號，就只處理宿舍，跳過這行

                            room_number_str = str(room_number).strip()
                            room_details = {
                                'capacity': int(pd.to_numeric(row.get('容量'), errors='coerce', downcast='integer')),
                                'gender_policy': row.get('性別限制', '可混住'),
                                'nationality_policy': row.get('國籍限制', '不限'),
                                'room_notes': row.get('房間備註')
                            }

                            room_key = (dorm_id, room_number_str)
                            existing_room_id = room_map.get(room_key)

                            if existing_room_id:
                                # 更新現有房間
                                fields = ', '.join([f'"{key}" = %s' for key in room_details.keys()])
                                values = list(room_details.values()) + [existing_room_id]
                                cursor.execute(f'UPDATE "Rooms" SET {fields} WHERE id = %s', tuple(values))
                            else:
                                # 新增房間
                                room_details['dorm_id'] = dorm_id
                                room_details['room_number'] = room_number_str
                                columns = ', '.join(f'"{k}"' for k in room_details.keys())
                                placeholders = ', '.join(['%s'] * len(room_details))
                                cursor.execute(f'INSERT INTO "Rooms" ({columns}) VALUES ({placeholders}) RETURNING id', tuple(room_details.values()))
                                new_room_id = cursor.fetchone()['id']
                                room_map[room_key] = new_room_id # 更新 map
                            
                            success_count += 1
                        except Exception as row_error:
                            # 這是處理單一房間匯入失敗的狀況
                            failed_row = row.copy()
                            failed_row['錯誤原因'] = str(row_error)
                            failed_records.append(failed_row)
                            
                except Exception as group_error:
                    # 這是處理整個宿舍（地址）層級失敗的狀況
                    for _, failed_row_in_group in group.iterrows():
                        failed_row = failed_row_in_group.copy()
                        failed_row['錯誤原因'] = str(group_error)
                        failed_records.append(failed_row)

        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"批次匯入宿舍與房間時發生嚴重錯誤: {e}")
    finally:
        if conn: conn.close()
            
    return success_count, pd.DataFrame(failed_records)

def batch_import_vendors(df: pd.DataFrame):
    """
    批次匯入廠商聯絡資料。
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
            # --- 【核心修改 1】更新欄位對應 ---
            column_mapping = {
                "服務項目": "service_category",
                "廠商名稱": "vendor_name",
                "聯絡人": "contact_person",
                "聯絡電話": "phone_number",
                "統一編號": "tax_id", # <-- 新增
                "匯款資訊": "remittance_info" # <-- 新增
            }
            df.rename(columns=column_mapping, inplace=True)

            for index, row in df.iterrows():
                try:
                    # 取得必要的欄位值，並清除前後空白
                    vendor_name = str(row.get('vendor_name', '')).strip()
                    service_category = str(row.get('service_category', '')).strip()

                    if not vendor_name and not service_category:
                        raise ValueError("「廠商名稱」和「服務項目」至少需要一項")
                    
                    # --- 【核心修改 2】將新欄位加入 details 字典 ---
                    details = {
                        'service_category': service_category,
                        'vendor_name': vendor_name,
                        'contact_person': str(row.get('contact_person', '')).strip(),
                        'phone_number': str(row.get('phone_number', '')).strip(),
                        'tax_id': str(row.get('tax_id', '')).strip(), # <-- 新增
                        'remittance_info': str(row.get('remittance_info', '')).strip(), # <-- 新增
                        'notes': str(row.get('備註', '')).strip()
                    }

                    # 判斷：如果廠商名稱和服務項目都相同，就視為同一筆資料
                    cursor.execute(
                        'SELECT id FROM "Vendors" WHERE vendor_name = %s AND service_category = %s',
                        (details['vendor_name'], details['service_category'])
                    )
                    existing = cursor.fetchone()
                    
                    if existing:
                        # 更新現有廠商
                        existing_id = existing['id']
                        fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
                        values = list(details.values()) + [existing_id]
                        update_sql = f'UPDATE "Vendors" SET {fields} WHERE id = %s'
                        cursor.execute(update_sql, tuple(values))
                    else:
                        # 新增廠商
                        columns = ', '.join(f'"{k}"' for k in details.keys())
                        placeholders = ', '.join(['%s'] * len(details))
                        insert_sql = f'INSERT INTO "Vendors" ({columns}) VALUES ({placeholders})'
                        cursor.execute(insert_sql, tuple(details.values()))

                    success_count += 1
                except Exception as row_error:
                    # 如果單筆資料處理失敗，記錄下來
                    original_row = row.rename(index={v: k for k, v in column_mapping.items()})
                    original_row['錯誤原因'] = str(row_error)
                    failed_records.append(original_row)

        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"批次匯入廠商資料時發生嚴重錯誤: {e}")
    finally:
        if conn: conn.close()
            
    return success_count, pd.DataFrame(failed_records)

# 【核心修改 1】新增一個專門用來「新增」維修紀錄的函式
def batch_insert_maintenance_logs(df: pd.DataFrame):
    """
    批次【新增】維修追蹤紀錄。
    如果紀錄已存在 (根據內容判斷)，則會跳過。
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
            
            vendors_df = _execute_query_to_dataframe(conn, 'SELECT id, vendor_name FROM "Vendors"')
            vendor_map = {v['vendor_name']: v['id'] for _, v in vendors_df.iterrows()}

            for index, row in df.iterrows():
                try:
                    address = row.get('宿舍地址')
                    if not address or pd.isna(address):
                        raise ValueError("宿舍地址為空")
                    addr_stripped = str(address).strip()
                    dorm_id = original_addr_map.get(addr_stripped) or normalized_addr_map.get(normalize_taiwan_address(addr_stripped)['full'])
                    if not dorm_id:
                        raise ValueError(f"找不到宿舍地址: '{addr_stripped}'")

                    vendor_id = None
                    vendor_name = row.get('維修廠商')
                    if pd.notna(vendor_name) and str(vendor_name).strip():
                        vendor_id = vendor_map.get(str(vendor_name).strip())

                    details = {
                        'dorm_id': dorm_id,
                        'vendor_id': vendor_id,
                        'status': row.get('狀態', '已完成'),
                        'notification_date': pd.to_datetime(row.get('收到通知日期')).date() if pd.notna(row.get('收到通知日期')) else None,
                        'reported_by': row.get('公司內部通知人'),
                        'item_type': row.get('項目類型'),
                        'description': row.get('修理細項說明'),
                        'contacted_vendor_date': pd.to_datetime(row.get('聯絡廠商日期')).date() if pd.notna(row.get('聯絡廠商日期')) else None,
                        'key_info': row.get('鑰匙'),
                        'completion_date': pd.to_datetime(row.get('廠商回報完成日期')).date() if pd.notna(row.get('廠商回報完成日期')) else None,
                        'cost': int(pd.to_numeric(row.get('維修費用'), errors='coerce')) if pd.notna(row.get('維修費用')) else None,
                        'payer': row.get('付款人'),
                        'invoice_date': pd.to_datetime(row.get('請款日期')).date() if pd.notna(row.get('請款日期')) else None,
                        'invoice_info': row.get('發票'),
                        'notes': row.get('備註')
                    }
                    
                    cursor.execute(
                        'SELECT id FROM "MaintenanceLog" WHERE dorm_id = %s AND description = %s AND notification_date = %s',
                        (details['dorm_id'], details['description'], details['notification_date'])
                    )
                    if cursor.fetchone():
                        continue

                    columns = ', '.join(f'"{k}"' for k in details.keys())
                    placeholders = ', '.join(['%s'] * len(details))
                    sql = f'INSERT INTO "MaintenanceLog" ({columns}) VALUES ({placeholders})'
                    cursor.execute(sql, tuple(v for v in details.values()))

                    success_count += 1
                except Exception as row_error:
                    row['錯誤原因'] = str(row_error)
                    failed_records.append(row)

        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"批次新增維修紀錄時發生嚴重錯誤: {e}")
    finally:
        if conn: conn.close()
            
    return success_count, pd.DataFrame(failed_records)

def batch_update_maintenance_logs(df: pd.DataFrame):
    """
    批次【更新】維修追蹤紀錄。
    只會根據提供的 ID 更新現有紀錄，不會新增。
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
            vendors_df = _execute_query_to_dataframe(conn, 'SELECT id, vendor_name FROM "Vendors"')
            vendor_map = {v['vendor_name']: v['id'] for _, v in vendors_df.iterrows()}

            for index, row in df.iterrows():
                try:
                    log_id = int(pd.to_numeric(row.get('ID'), errors='coerce'))
                    if not log_id:
                        raise ValueError("Excel 中缺少 ID 欄位，無法進行更新。請下載最新的待更新檔案。")

                    vendor_id = None
                    vendor_name = row.get('維修廠商')
                    if pd.notna(vendor_name) and str(vendor_name).strip():
                        vendor_name_stripped = str(vendor_name).strip()
                        vendor_id = vendor_map.get(vendor_name_stripped)

                    details = {
                        'vendor_id': vendor_id,
                        'status': row.get('狀態'),
                        'reported_by': row.get('公司內部通知人'),
                        'item_type': row.get('項目類型'),
                        'description': row.get('修理細項說明'),
                        'contacted_vendor_date': pd.to_datetime(row.get('聯絡廠商日期')).date() if pd.notna(row.get('聯絡廠商日期')) else None,
                        'key_info': row.get('鑰匙'),
                        'completion_date': pd.to_datetime(row.get('廠商回報完成日期')).date() if pd.notna(row.get('廠商回報完成日期')) else None,
                        'cost': int(pd.to_numeric(row.get('維修費用'), errors='coerce')) if pd.notna(row.get('維修費用')) else None,
                        'payer': row.get('付款人'),
                        'invoice_date': pd.to_datetime(row.get('請款日期')).date() if pd.notna(row.get('請款日期')) else None,
                        'invoice_info': row.get('發票'),
                        'notes': row.get('備註')
                    }
                    
                    update_details = {k: v for k, v in details.items() if pd.notna(v)}

                    if not update_details:
                        continue

                    fields = ', '.join([f'"{key}" = %s' for key in update_details.keys()])
                    values = list(update_details.values()) + [log_id]
                    sql = f'UPDATE "MaintenanceLog" SET {fields} WHERE id = %s'
                    cursor.execute(sql, tuple(values))

                    if cursor.rowcount == 0:
                        raise ValueError(f"在資料庫中找不到對應的維修 ID: {log_id}")

                    success_count += 1
                except Exception as row_error:
                    row['錯誤原因'] = str(row_error)
                    failed_records.append(row)

        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"批次更新維修紀錄時發生嚴重錯誤: {e}")
    finally:
        if conn: conn.close()
            
    return success_count, pd.DataFrame(failed_records)

def export_maintenance_logs_for_update():
    """匯出所有尚未歸檔的維修紀錄，用於批次更新。"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                l.id AS "ID",
                l.notification_date AS "收到通知日期",
                d.original_address AS "宿舍地址",
                l.description AS "修理細項說明",
                l.item_type AS "項目類型",
                v.vendor_name AS "維修廠商",
                l.reported_by AS "公司內部通知人",
                l.contacted_vendor_date AS "聯絡廠商日期",
                l.key_info AS "鑰匙",
                l.completion_date AS "廠商回報完成日期",
                l.payer AS "付款人",
                l.cost AS "維修費用",
                l.invoice_date AS "請款日期",
                l.invoice_info AS "發票",
                l.notes AS "備註",
                l.status AS "狀態"
            FROM "MaintenanceLog" l
            JOIN "Dormitories" d ON l.dorm_id = d.id
            LEFT JOIN "Vendors" v ON l.vendor_id = v.id
            WHERE l.is_archived_as_expense = FALSE
            ORDER BY l.notification_date DESC;
        """
        return _execute_query_to_dataframe(conn, query)
    finally:
        if conn: conn.close()

def batch_import_equipment(df: pd.DataFrame):
    """
    【v2.0 廠商關聯版】批次匯入【設備】的核心邏輯。
    可同時建立設備、採購費用、首次合規紀錄，並關聯供應廠商。
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
            # --- 【核心修改 1】預先載入所有需要的資料以供比對 ---
            dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, original_address, normalized_address FROM "Dormitories"')
            original_addr_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
            normalized_addr_map = {d['normalized_address']: d['id'] for _, d in dorms_df.iterrows()}
            
            equip_df = _execute_query_to_dataframe(conn, 'SELECT id, dorm_id, equipment_name, location FROM "DormitoryEquipment"')
            equip_map = {(row['dorm_id'], row['equipment_name'], str(row['location'] or '')): row['id'] for _, row in equip_df.iterrows()}

            vendors_df = _execute_query_to_dataframe(conn, 'SELECT id, vendor_name FROM "Vendors"')
            vendor_map = {v['vendor_name']: v['id'] for _, v in vendors_df.iterrows()}

            for index, row in df.iterrows():
                try:
                    original_address = row.get('宿舍地址')
                    if pd.isna(original_address) or not str(original_address).strip():
                        raise ValueError("宿舍地址為必填欄位")

                    addr_stripped = str(original_address).strip()
                    dorm_id = original_addr_map.get(addr_stripped) or normalized_addr_map.get(normalize_taiwan_address(addr_stripped)['full'])
                    
                    if not dorm_id:
                        raise ValueError(f"在資料庫中找不到對應的宿舍地址: {original_address}")

                    equipment_name = row.get('設備名稱')
                    if pd.isna(equipment_name) or not str(equipment_name).strip():
                        raise ValueError("設備名稱為必填欄位")
                    
                    # --- 【核心修改 2】處理供應廠商欄位 ---
                    vendor_id = None
                    vendor_name = row.get('供應廠商')
                    if pd.notna(vendor_name) and str(vendor_name).strip():
                        vendor_name_stripped = str(vendor_name).strip()
                        vendor_id = vendor_map.get(vendor_name_stripped)
                        if not vendor_id:
                            raise ValueError(f"在廠商資料庫中找不到廠商: '{vendor_name_stripped}'，請先新增或確認名稱是否完全相符。")

                    def to_int_or_none(val):
                        if pd.isna(val) or val == '': return None
                        return int(val)
                    
                    def to_date_or_none(val):
                        if pd.isna(val): return None
                        return pd.to_datetime(val).date()

                    details = {
                        "dorm_id": dorm_id,
                        "vendor_id": vendor_id, # 將 vendor_id 加入
                        "equipment_name": str(equipment_name).strip(),
                        "equipment_category": str(row.get('設備分類', '')).strip() or None,
                        "location": str(row.get('位置', '')).strip() or None,
                        "brand_model": str(row.get('品牌/型號', '')).strip() or None,
                        "serial_number": str(row.get('序號/批號', '')).strip() or None,
                        "purchase_cost": to_int_or_none(row.get('採購金額')),
                        "installation_date": to_date_or_none(row.get('安裝/啟用日期')),
                        "maintenance_interval_months": to_int_or_none(row.get('一般保養週期(月)')),
                        "compliance_interval_months": to_int_or_none(row.get('合規檢測週期(月)')),
                        "last_maintenance_date": to_date_or_none(row.get('上次保養日期')),
                        "next_maintenance_date": to_date_or_none(row.get('下次保養/檢查日期')),
                        "status": str(row.get('狀態', '正常')).strip(),
                        "notes": str(row.get('備註', '')).strip() or None
                    }

                    lookup_key = (dorm_id, details['equipment_name'], details['location'] or '')
                    existing_id = equip_map.get(lookup_key)
                    
                    new_equipment_id = None
                    if existing_id:
                        fields = ', '.join([f'"{key}" = %s' for key in details.keys()])
                        values = list(details.values()) + [existing_id]
                        update_sql = f'UPDATE "DormitoryEquipment" SET {fields} WHERE id = %s'
                        cursor.execute(update_sql, tuple(values))
                        new_equipment_id = existing_id
                    else:
                        columns = ', '.join(f'"{k}"' for k in details.keys())
                        placeholders = ', '.join(['%s'] * len(details))
                        insert_sql = f'INSERT INTO "DormitoryEquipment" ({columns}) VALUES ({placeholders}) RETURNING id'
                        cursor.execute(insert_sql, tuple(details.values()))
                        new_equipment_id = cursor.fetchone()['id']
                    
                    first_compliance_date = to_date_or_none(row.get('首次合規檢測日期'))
                    compliance_cost = to_int_or_none(row.get('首次合規檢測費用'))

                    if first_compliance_date:
                        record_type = f"{details['equipment_category']}檢測" if details['equipment_category'] else "合規檢測"
                        record_details = {
                            "dorm_id": dorm_id, "equipment_id": new_equipment_id,
                            "details": {
                                "declaration_item": f"首次{record_type}",
                                "certificate_date": first_compliance_date,
                                "next_declaration_start": to_date_or_none(row.get('下次合規檢測日期'))
                            }
                        }
                        expense_details = None
                        if compliance_cost and compliance_cost > 0:
                            expense_details = {
                                "dorm_id": dorm_id, "expense_item": f"首次{record_type}",
                                "payment_date": first_compliance_date, "total_amount": compliance_cost,
                                "amortization_start_month": first_compliance_date.strftime('%Y-%m'),
                                "amortization_end_month": first_compliance_date.strftime('%Y-%m')
                            }
                        
                        comp_success, comp_message, _ = finance_model.add_compliance_record(record_type, record_details, expense_details)
                        if not comp_success:
                             raise Exception(f"設備已處理，但建立首次合規紀錄失敗: {comp_message}")
                    
                    success_count += 1
                except Exception as row_error:
                    row['錯誤原因'] = str(row_error)
                    failed_records.append(row)
        
        conn.commit()
    except Exception as e:
        if conn: conn.rollback()
        print(f"批次匯入設備時發生嚴重錯誤: {e}")
    finally:
        if conn: conn.close()
            
    return success_count, pd.DataFrame(failed_records)
