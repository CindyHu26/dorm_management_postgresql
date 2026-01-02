import pandas as pd
import database

def _execute_query_to_dataframe(conn, query, params=None):
    with conn.cursor() as cursor:
        cursor.execute(query, params)
        records = cursor.fetchall()
        if not records:
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            return pd.DataFrame([], columns=columns)
        columns = [desc[0] for desc in cursor.description]
        return pd.DataFrame(records, columns=columns)

def get_utility_bills_details(start_date, end_date, dorm_ids=None):
    """取得變動費用(UtilityBills)細項"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                d.original_address AS "宿舍",
                b.bill_type AS "費用類型",
                b.amount AS "金額",
                b.bill_start_date AS "帳單起始",
                b.bill_end_date AS "帳單結束",
                b.usage_amount AS "用量",
                m.meter_number AS "對應錶號",
                b.payer AS "支付方",
                b.notes AS "備註"
            FROM "UtilityBills" b
            JOIN "Dormitories" d ON b.dorm_id = d.id
            LEFT JOIN "Meters" m ON b.meter_id = m.id
            WHERE b.bill_end_date BETWEEN %s AND %s
        """
        params = [start_date, end_date]
        if dorm_ids:
            query += " AND d.id = ANY(%s)"
            params.append(list(dorm_ids))
        query += " ORDER BY d.original_address, b.bill_end_date DESC"
        return _execute_query_to_dataframe(conn, query, tuple(params))
    finally:
        if conn: conn.close()

def get_annual_expenses_details(start_date, end_date, dorm_ids=None):
    """取得年度費用/攤銷(AnnualExpenses)細項"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 這裡以「支付日期」為準來篩選
        query = """
            SELECT 
                d.original_address AS "宿舍",
                ae.expense_item AS "費用項目",
                ae.total_amount AS "金額",
                ae.payment_date AS "支付日期",
                ae.amortization_start_month AS "攤提起始",
                ae.amortization_end_month AS "攤提結束",
                ae.notes AS "備註"
            FROM "AnnualExpenses" ae
            JOIN "Dormitories" d ON ae.dorm_id = d.id
            WHERE ae.payment_date BETWEEN %s AND %s
        """
        params = [start_date, end_date]
        if dorm_ids:
            query += " AND d.id = ANY(%s)"
            params.append(list(dorm_ids))
        query += " ORDER BY d.original_address, ae.payment_date DESC"
        return _execute_query_to_dataframe(conn, query, tuple(params))
    finally:
        if conn: conn.close()

def get_lease_contracts(dorm_ids=None):
    """取得租賃合約(Leases)細項 (列出目前所有合約)"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                d.original_address AS "宿舍",
                l.contract_item AS "合約項目",
                l.monthly_rent AS "月租金額",
                l.payer AS "支付方",
                l.lease_start_date AS "合約起日",
                l.lease_end_date AS "合約迄日",
                v.vendor_name AS "廠商/房東"
            FROM "Leases" l
            JOIN "Dormitories" d ON l.dorm_id = d.id
            LEFT JOIN "Vendors" v ON l.vendor_id = v.id
            WHERE (l.lease_end_date IS NULL OR l.lease_end_date >= CURRENT_DATE)
        """
        params = []
        if dorm_ids:
            query += " AND d.id = ANY(%s)"
            params.append(list(dorm_ids))
        query += " ORDER BY d.original_address, l.lease_start_date DESC"
        return _execute_query_to_dataframe(conn, query, tuple(params))
    finally:
        if conn: conn.close()

def get_maintenance_details(start_date, end_date, dorm_ids=None):
    """取得維修(MaintenanceLog)細項"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                d.original_address AS "宿舍",
                l.item_type AS "維修類型",
                l.description AS "說明",
                l.cost AS "金額",
                l.payer AS "支付方",
                l.status AS "狀態",
                l.notification_date AS "通報日",
                l.completion_date AS "完成日",
                v.vendor_name AS "維修廠商"
            FROM "MaintenanceLog" l
            JOIN "Dormitories" d ON l.dorm_id = d.id
            LEFT JOIN "Vendors" v ON l.vendor_id = v.id
            WHERE l.notification_date BETWEEN %s AND %s
            AND l.cost > 0
        """
        params = [start_date, end_date]
        if dorm_ids:
            query += " AND d.id = ANY(%s)"
            params.append(list(dorm_ids))
        query += " ORDER BY d.original_address, l.notification_date DESC"
        return _execute_query_to_dataframe(conn, query, tuple(params))
    finally:
        if conn: conn.close()

def get_other_income_details(start_date, end_date, dorm_ids=None):
    """取得其他收入(OtherIncome)細項"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT 
                d.original_address AS "宿舍",
                i.income_item AS "收入項目",
                i.amount AS "金額",
                i.transaction_date AS "收入日期",
                i.target_employer AS "來源雇主",
                i.notes AS "備註"
            FROM "OtherIncome" i
            JOIN "Dormitories" d ON i.dorm_id = d.id
            WHERE i.transaction_date BETWEEN %s AND %s
        """
        params = [start_date, end_date]
        if dorm_ids:
            query += " AND d.id = ANY(%s)"
            params.append(list(dorm_ids))
        query += " ORDER BY d.original_address, i.transaction_date DESC"
        return _execute_query_to_dataframe(conn, query, tuple(params))
    finally:
        if conn: conn.close()

def get_worker_fee_details(start_date, end_date, dorm_ids=None):
    """取得人員總收租(FeeHistory)細項"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        # 這裡會嘗試透過 AccommodationHistory 找尋當時的宿舍，如果找不到則回退到目前房間
        query = """
            SELECT 
                COALESCE(d.original_address, '未知(歷史紀錄)') AS "宿舍",
                w.worker_name AS "姓名",
                w.employer_name AS "雇主",
                fh.fee_type AS "費用項目",
                fh.amount AS "金額",
                fh.effective_date AS "生效/收費日期"
            FROM "FeeHistory" fh
            JOIN "Workers" w ON fh.worker_unique_id = w.unique_id
            -- 嘗試關聯歷史住宿以取得準確地點
            LEFT JOIN "AccommodationHistory" ah ON fh.worker_unique_id = ah.worker_unique_id
                AND ah.start_date <= fh.effective_date
                AND (ah.end_date IS NULL OR ah.end_date >= fh.effective_date)
            LEFT JOIN "Rooms" r ON ah.room_id = r.id
            LEFT JOIN "Dormitories" d ON r.dorm_id = d.id
            WHERE fh.effective_date BETWEEN %s AND %s
        """
        params = [start_date, end_date]
        if dorm_ids:
            query += " AND d.id = ANY(%s)"
            params.append(list(dorm_ids))
        query += " ORDER BY d.original_address, w.worker_name"
        return _execute_query_to_dataframe(conn, query, tuple(params))
    finally:
        if conn: conn.close()