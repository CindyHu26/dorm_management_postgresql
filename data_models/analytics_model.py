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
    """
    【v1.3 修正版】根據指定的電水錶ID，查詢其所有的歷史帳單紀錄。
    在讀取後立刻將 Decimal 型別轉為 float，以確保前端顯示正常。
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
                amount AS "帳單金額",
                usage_amount AS "用量(度/噸)"
            FROM "UtilityBills"
            WHERE meter_id = %(meter_id)s
            ORDER BY bill_end_date ASC
        """
        df = _execute_query_to_dataframe(conn, query, {"meter_id": meter_id})
        
        if not df.empty:
            # 在資料回傳給前端之前，就先將所有數字欄位轉換為標準的 float 格式
            if "用量(度/噸)" in df.columns:
                df["用量(度/噸)"] = pd.to_numeric(df["用量(度/噸)"], errors='coerce')
            if "帳單金額" in df.columns:
                df["帳單金額"] = pd.to_numeric(df["帳單金額"], errors='coerce')

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

def find_usage_anomalies(threshold_percent: float = 10.0):
    """
    【v1.1 修正版】分析所有電水錶的「用量」，找出與「上一期」或「去年同期」相比，波動超過指定百分比的紀錄。
    修正 Decimal 與 float 型別不相容的錯誤。
    """
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                d.original_address, m.meter_type, m.meter_number,
                b.bill_end_date, b.usage_amount, b.payer, b.is_pass_through
            FROM "UtilityBills" b
            JOIN "Meters" m ON b.meter_id = m.id
            JOIN "Dormitories" d ON b.dorm_id = d.id
            WHERE d.primary_manager = '我司' AND b.usage_amount IS NOT NULL
        """
        df = _execute_query_to_dataframe(conn, query)
        if df.empty:
            return pd.DataFrame()

        df['bill_end_date'] = pd.to_datetime(df['bill_end_date'])
        df.sort_values(by=['original_address', 'meter_type', 'meter_number', 'bill_end_date'], inplace=True)
        
        anomalies = []
        
        for meter, group in df.groupby(['original_address', 'meter_type', 'meter_number']):
            if len(group) < 2: continue

            group['prev_usage'] = group['usage_amount'].shift(1)
            group['prev_date'] = group['bill_end_date'].shift(1)
            
            group['year'] = group['bill_end_date'].dt.year
            group['month'] = group['bill_end_date'].dt.month
            group['last_year_avg'] = group.groupby('month')['usage_amount'].transform(lambda x: x.shift(1).expanding().mean())

            for _, row in group.iterrows():
                # --- 將所有運算元都轉為 float 型別 ---
                current_usage = float(row['usage_amount'])
                
                # 與上期比
                prev_usage = row['prev_usage']
                if pd.notna(prev_usage) and prev_usage > 0:
                    prev_usage = float(prev_usage)
                    percent_diff = ((current_usage - prev_usage) / prev_usage) * 100
                    if abs(percent_diff) > threshold_percent:
                        reason = f"較上期 ({row['prev_date'].strftime('%Y-%m-%d')}) {'增加' if percent_diff > 0 else '減少'} {abs(percent_diff):.0f}%"
                        anomalies.append({
                            "宿舍地址": meter[0], "類型": meter[1], "錶號": meter[2],
                            "帳單迄日": row['bill_end_date'].strftime('%Y-%m-%d'),
                            "本期用量": current_usage, "比較基準": prev_usage,
                            "支付方": row['payer'], "代收代付?": row['is_pass_through'],
                            "判斷": "用量過高" if percent_diff > 0 else "用量過低",
                            "分析說明": reason
                        })
                        continue

                # 與去年同期比
                last_year_avg = row['last_year_avg']
                if pd.notna(last_year_avg) and last_year_avg > 0:
                    percent_diff = ((current_usage - last_year_avg) / last_year_avg) * 100
                    if abs(percent_diff) > threshold_percent:
                        reason = f"較去年同期平均 ({last_year_avg:.1f}) {'增加' if percent_diff > 0 else '減少'} {abs(percent_diff):.0f}%"
                        anomalies.append({
                            "宿舍地址": meter[0], "類型": meter[1], "錶號": meter[2],
                            "帳單迄日": row['bill_end_date'].strftime('%Y-%m-%d'),
                            "本期用量": current_usage, "比較基準": last_year_avg,
                            "支付方": row['payer'], "代收代付?": row['is_pass_through'],
                            "判斷": "用量過高" if percent_diff > 0 else "用量過低",
                            "分析說明": reason
                        })

        return pd.DataFrame(anomalies)
    finally:
        if conn: conn.close()