import pandas as pd
import database

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

def get_all_meters_for_selection():
    """獲取所有「我司管理」宿舍的電水錶列表，用於下拉選單。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = """
            SELECT
                m.id,
                d.original_address,
                m.meter_type,
                m.meter_number
            FROM "Meters" m
            JOIN "Dormitories" d ON m.dorm_id = d.id
            WHERE d.primary_manager = '我司'
            ORDER BY d.original_address, m.meter_type, m.meter_number
        """
        with conn.cursor() as cursor:
            cursor.execute(query)
            records = cursor.fetchall()
            return [dict(row) for row in records]
    finally:
        if conn: conn.close()

def get_bill_history_for_meter(meter_id: int):
    """根據指定的電水錶ID，查詢其所有的歷史帳單紀錄。"""
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
            FROM "UtilityBills"
            WHERE meter_id = %(meter_id)s
            ORDER BY bill_end_date ASC
        """
        df = _execute_query_to_dataframe(conn, query, {"meter_id": meter_id})
        if not df.empty:
            df['帳單結束日'] = pd.to_datetime(df['帳單結束日'])
        return df
    finally:
        if conn: conn.close()

def find_expense_anomalies():
    """
    【v1.1 修改版】使用統計學方法 (IQR)，找出所有我司管理宿舍中，費用異常升高或降低的帳單紀錄。
    新增「支付方」和「是否為代收代付」欄位。
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
                b.amount,
                b.payer,
                b.is_pass_through
            FROM "UtilityBills" b
            JOIN "Meters" m ON b.meter_id = m.id
            JOIN "Dormitories" d ON b.dorm_id = d.id
            WHERE d.primary_manager = '我司'
        """
        df = _execute_query_to_dataframe(conn, query)
        if df.empty or len(df) < 4:
            return pd.DataFrame()

        anomalies = []
        for meter, group in df.groupby(['original_address', 'meter_type', 'meter_number']):
            if len(group) < 4: continue

            Q1 = group['amount'].quantile(0.25)
            Q3 = group['amount'].quantile(0.75)
            IQR = Q3 - Q1
            
            lower_bound = Q1 - 1.5 * IQR
            upper_bound = Q3 + 1.5 * IQR
            
            outliers = group[(group['amount'] < lower_bound) | (group['amount'] > upper_bound)].copy()
            
            if not outliers.empty:
                outliers['判斷'] = outliers['amount'].apply(lambda x: '費用過高' if x > upper_bound else '費用過低')
                outliers['正常範圍'] = f"{int(lower_bound):,} ~ {int(upper_bound):,}"
                anomalies.append(outliers)

        if not anomalies:
            return pd.DataFrame()
            
        result_df = pd.concat(anomalies)
        
        result_df.rename(columns={
            'original_address': '宿舍地址',
            'meter_type': '類型',
            'meter_number': '錶號',
            'bill_end_date': '帳單迄日',
            'amount': '異常金額',
            'payer': '支付方',
            'is_pass_through': '是否為代收代付'
        }, inplace=True)
        
        return result_df[['宿舍地址', '類型', '錶號', '帳單迄日', '異常金額', '支付方', '是否為代收代付', '正常範圍', '判斷']]
    finally:
        if conn: conn.close()