import pandas as pd
import database

def get_all_meters_for_selection():
    """
    獲取所有「我司管理」宿舍的電水錶列表，用於下拉選單。
    """
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = """
            SELECT
                m.id,
                d.original_address,
                m.meter_type,
                m.meter_number
            FROM Meters m
            JOIN Dormitories d ON m.dorm_id = d.id
            WHERE d.primary_manager = '我司'
            ORDER BY d.original_address, m.meter_type, m.meter_number
        """
        records = pd.read_sql_query(query, conn)
        return records.to_dict('records')
    finally:
        if conn: conn.close()

def get_bill_history_for_meter(meter_id: int):
    """
    根據指定的電水錶ID，查詢其所有的歷史帳單紀錄。
    """
    if not meter_id:
        return pd.DataFrame()

    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                bill_start_date AS "帳單起始日",
                bill_end_date AS "帳單結束日",
                amount AS "帳單金額"
            FROM UtilityBills
            WHERE meter_id = ?
            ORDER BY bill_end_date ASC
        """
        df = pd.read_sql_query(query, conn, params=(meter_id,))
        # 將日期欄位轉換為真正的日期格式，以便圖表繪製
        if not df.empty:
            df['帳單結束日'] = pd.to_datetime(df['帳單結束日'])
        return df
    finally:
        if conn: conn.close()

def find_expense_anomalies():
    """
    使用統計學方法 (IQR)，找出所有我司管理宿舍中，費用異常升高或降低的帳單紀錄。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                d.original_address,
                m.meter_type,
                m.meter_number,
                b.bill_start_date,
                b.bill_end_date,
                b.amount
            FROM UtilityBills b
            JOIN Meters m ON b.meter_id = m.id
            JOIN Dormitories d ON b.dorm_id = d.id
            WHERE d.primary_manager = '我司'
        """
        df = pd.read_sql_query(query, conn)
        if df.empty or len(df) < 4: # 數據太少，無法進行有意義的統計
            return pd.DataFrame()

        # 按每個電錶進行分組
        anomalies = []
        for meter, group in df.groupby(['original_address', 'meter_type', 'meter_number']):
            if len(group) < 4: continue # 樣本數小於4的組別不進行分析

            Q1 = group['amount'].quantile(0.25)
            Q3 = group['amount'].quantile(0.75)
            IQR = Q3 - Q1
            
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            
            # 找出離群值
            outliers = group[(group['amount'] < lower_bound) | (group['amount'] > upper_bound)].copy()
            
            if not outliers.empty:
                outliers['reason'] = outliers['amount'].apply(lambda x: '費用過高' if x > upper_bound else '費用過低')
                anomalies.append(outliers)

        if not anomalies:
            return pd.DataFrame()
            
        result_df = pd.concat(anomalies)
        result_df.rename(columns={
            'original_address': '宿舍地址',
            'meter_type': '類型',
            'meter_number': '錶號',
            'bill_start_date': '帳單起日',
            'bill_end_date': '帳單迄日',
            'amount': '帳單金額',
            'reason': '判斷'
        }, inplace=True)
        
        return result_df[['宿舍地址', '類型', '錶號', '帳單迄日', '帳單金額', '判斷']]

    finally:
        if conn: conn.close()