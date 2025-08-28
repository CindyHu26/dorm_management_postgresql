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
            dorms_df = _execute_query_to_dataframe(conn, 'SELECT id, original_address FROM "Dormitories"')
            dorms_map = {d['original_address']: d['id'] for _, d in dorms_df.iterrows()}
            
            meters_df = _execute_query_to_dataframe(conn, 'SELECT id, dorm_id, meter_number FROM "Meters"')
            meters_map = {(row['dorm_id'], row['meter_number']): row['id'] for _, row in meters_df.iterrows()}

            for index, row in df.iterrows():
                try:
                    # ... (地址比對等邏輯維持不變) ...
                    original_address = row.get('宿舍地址')
                    if not original_address or pd.isna(original_address):
                        raise ValueError("宿舍地址為空")
                    dorm_id = dorms_map.get(str(original_address).strip())
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
                    
                    # 【核心修改】在 details 字典中加入對新欄位的處理
                    def to_bool(val):
                        if pd.isna(val): return False # 預設為 False
                        return str(val).strip().upper() in ['TRUE', '1', 'Y', 'YES', '是']

                    details = {
                        "dorm_id": dorm_id, "meter_id": meter_id,
                        "bill_type": str(row.get('費用類型', '')).strip(),
                        "amount": int(pd.to_numeric(row.get('帳單金額'), errors='coerce')),
                        "bill_start_date": pd.to_datetime(row.get('帳單起始日'), errors='coerce').strftime('%Y-%m-%d'),
                        "bill_end_date": pd.to_datetime(row.get('帳單結束日'), errors='coerce').strftime('%Y-%m-%d'),
                        "payer": str(row.get('支付方', '我司')).strip(), # 新增，預設為 '我司'
                        "is_pass_through": to_bool(row.get('是否為代收代付')), # 新增
                        "is_invoiced": to_bool(row.get('是否已請款')),
                        "notes": str(row.get('備註', ''))
                    }
                    
                    # 查重邏輯 (維持不變)
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
                        raise ValueError("新增失敗：已存在完全相同的費用紀錄。")
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