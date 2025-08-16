import pandas as pd
import generic_db_ops as db
from data_processor import normalize_taiwan_address

def batch_import_expenses(df: pd.DataFrame):
    """
    批次匯入【每月】費用的核心邏輯。
    【v1.2 新增】對費用月份進行智能格式化。
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
            
        # --- 【智能日期格式化】 ---
        try:
            # 嘗試將輸入轉換為日期物件，然後格式化為 'YYYY-MM'
            billing_month = pd.to_datetime(billing_month_raw).strftime('%Y-%m')
        except (ValueError, TypeError):
            row['錯誤原因'] = f"費用月份 '{billing_month_raw}' 格式不正確，應為 YYYY-MM 或 YYYY/MM/DD"
            failed_records.append(row)
            continue
        # --- 格式化結束 ---
            
        dorm_id = dorms_map.get(original_address)
        if not dorm_id:
            row['錯誤原因'] = f"在資料庫中找不到對應的宿舍地址: {original_address}"
            failed_records.append(row)
            continue
            
        details = {
            "dorm_id": dorm_id, "billing_month": billing_month,
            "electricity_fee": pd.to_numeric(row.get('電費'), errors='coerce'),
            "water_fee": pd.to_numeric(row.get('水費'), errors='coerce'),
            "gas_fee": pd.to_numeric(row.get('瓦斯費'), errors='coerce'),
            "internet_fee": pd.to_numeric(row.get('網路費'), errors='coerce'),
            "other_fee": pd.to_numeric(row.get('其他費用'), errors='coerce'),
            "is_invoiced": True if str(row.get('是否已請款')).strip().upper() in ['Y', 'TRUE', 'V', '是'] else False
        }
        
        query = "SELECT id FROM UtilityBills WHERE dorm_id = ? AND billing_month = ?"
        existing = db.read_records(query, params=(dorm_id, str(billing_month)), fetch_one=True)
        
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