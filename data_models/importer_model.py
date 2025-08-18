import pandas as pd
import generic_db_ops as db
from data_processor import normalize_taiwan_address

def batch_import_expenses(df: pd.DataFrame):
    """
    批次匯入【每月/變動費用】的核心邏輯。
    【v1.3 新增】支援匹配對應的電水錶號。
    """
    success_count = 0
    failed_records = []

    dorms_map = {d['original_address']: d['id'] for d in db.read_records("SELECT id, original_address FROM Dormitories")}
    
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

        # --- 【核心修改】查找對應的 meter_id ---
        meter_id = None
        meter_number = row.get('對應錶號')
        if meter_number and pd.notna(meter_number):
            meter_number = str(meter_number).strip()
            meter_query = "SELECT id FROM Meters WHERE dorm_id = ? AND meter_number = ?"
            meter_result = db.read_records(meter_query, params=(dorm_id, meter_number), fetch_one=True)
            if meter_result:
                meter_id = meter_result['id']
            else:
                row['錯誤原因'] = f"在宿舍 '{original_address}' 中找不到錶號為 '{meter_number}' 的紀錄"
                failed_records.append(row)
                continue
        # --- 修改結束 ---
            
        details = {
            "dorm_id": dorm_id,
            "meter_id": meter_id, # 將找到的 meter_id 加入
            "bill_type": row.get('費用類型'),
            "amount": pd.to_numeric(row.get('帳單金額'), errors='coerce'),
            "bill_start_date": pd.to_datetime(row.get('帳單起始日'), errors='coerce').strftime('%Y-%m-%d'),
            "bill_end_date": pd.to_datetime(row.get('帳單結束日'), errors='coerce').strftime('%Y-%m-%d'),
            "is_invoiced": True if str(row.get('是否已請款')).strip().upper() in ['Y', 'TRUE', 'V', '是'] else False,
            "notes": str(row.get('備註', ''))
        }
        
        query = "SELECT id FROM UtilityBills WHERE dorm_id = ? AND bill_type = ? AND bill_start_date = ? AND amount = ?"
        # 增加 meter_id 作為判斷依據
        if meter_id:
            query += " AND meter_id = ?"
            existing = db.read_records(query, params=(dorm_id, details['bill_type'], details['bill_start_date'], details['amount'], meter_id), fetch_one=True)
        else:
            query += " AND meter_id IS NULL"
            existing = db.read_records(query, params=(dorm_id, details['bill_type'], details['bill_start_date'], details['amount']), fetch_one=True)

        if existing:
            success, message = db.update_record('UtilityBills', existing['id'], details)
        else:
            success, message, _ = db.create_record('UtilityBills', details)
        
        if success:
            success_count += 1
        else:
            row['錯誤原因'] = message
            failed_records.append(row)

    return success_count, pd.DataFrame(failed_records)

def batch_import_annual_expenses(df: pd.DataFrame):
    """
    批次匯入【年度/長期】費用的核心邏輯。
    【v1.2 新增】對月份與日期進行智能格式化。
    """
    success_count = 0
    failed_records = []
    dorms_map = {d['original_address']: d['id'] for d in db.read_records("SELECT id, original_address FROM Dormitories")}
    
    for index, row in df.iterrows():
        original_address = row.get('宿舍地址')
        expense_item = row.get('費用項目')
        payment_date_raw = row.get('支付日期')
        total_amount = pd.to_numeric(row.get('總金額'), errors='coerce')
        start_month_raw = row.get('攤提起始月')
        end_month_raw = row.get('攤提結束月')

        # --- 【智能日期格式化】 ---
        try:
            payment_date = pd.to_datetime(payment_date_raw).strftime('%Y-%m-%d')
            start_month = pd.to_datetime(start_month_raw).strftime('%Y-%m')
            end_month = pd.to_datetime(end_month_raw).strftime('%Y-%m')
        except (ValueError, TypeError):
            row['錯誤原因'] = "一個或多個日期/月份欄位格式不正確"
            failed_records.append(row)
            continue
        # --- 格式化結束 ---

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
        existing = db.read_records(query, params=(dorm_id, expense_item, details['payment_date']), fetch_one=True)
        
        if existing:
            success, message = db.update_record('AnnualExpenses', existing['id'], details)
        else:
            success, message, _ = db.create_record('AnnualExpenses', details)
        
        if success:
            success_count += 1
        else:
            row['錯誤原因'] = message
            failed_records.append(row)

    return success_count, pd.DataFrame(failed_records)