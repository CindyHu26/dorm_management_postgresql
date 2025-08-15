import pandas as pd
import generic_db_ops as db
from data_processor import normalize_taiwan_address

def batch_import_expenses(df: pd.DataFrame):
    """
    批次匯入每月費用的核心邏輯。
    """
    success_count = 0
    failed_records = []

    # 為了高效查詢，先一次性讀取所有宿舍的地址和ID
    dorms_map = {d['original_address']: d['id'] for d in db.read_records("SELECT id, original_address FROM Dormitories")}
    
    for index, row in df.iterrows():
        original_address = row.get('宿舍地址')
        billing_month = row.get('費用月份')

        # --- 1. 驗證基本資料 ---
        if not original_address or not billing_month:
            row['錯誤原因'] = "宿舍地址或費用月份為空"
            failed_records.append(row)
            continue
            
        # --- 2. 查找宿舍ID ---
        dorm_id = dorms_map.get(original_address)
        if not dorm_id:
            row['錯誤原因'] = f"在資料庫中找不到對應的宿舍地址: {original_address}"
            failed_records.append(row)
            continue
            
        # --- 3. 準備寫入資料 ---
        details = {
            "dorm_id": dorm_id,
            "billing_month": str(billing_month),
            "electricity_fee": pd.to_numeric(row.get('電費'), errors='coerce'),
            "water_fee": pd.to_numeric(row.get('水費'), errors='coerce'),
            "gas_fee": pd.to_numeric(row.get('瓦斯費'), errors='coerce'),
            "internet_fee": pd.to_numeric(row.get('網路費'), errors='coerce'),
            "other_fee": pd.to_numeric(row.get('其他費用'), errors='coerce'),
            "is_invoiced": True if str(row.get('是否已請款')).strip().upper() in ['Y', 'TRUE', 'V', '是'] else False
        }
        
        # --- 4. 執行寫入 (Upsert: 如果存在則更新，不存在則新增) ---
        query = "SELECT id FROM UtilityBills WHERE dorm_id = ? AND billing_month = ?"
        existing = db.read_records(query, params=(dorm_id, str(billing_month)), fetch_one=True)
        
        if existing:
            # 更新
            success, message = db.update_record('UtilityBills', existing['id'], details)
        else:
            # 新增
            success, message, _ = db.create_record('UtilityBills', details)
        
        if success:
            success_count += 1
        else:
            row['錯誤原因'] = message
            failed_records.append(row)

    return success_count, pd.DataFrame(failed_records)