import pandas as pd
from datetime import datetime
from dateutil.relativedelta import relativedelta
import database

def get_all_employers():
    """獲取所有不重複的雇主名稱列表，用於下拉選單。"""
    conn = database.get_db_connection()
    if not conn: return []
    try:
        query = "SELECT DISTINCT employer_name FROM Workers ORDER BY employer_name"
        employers = pd.read_sql_query(query, conn)
        return employers['employer_name'].tolist()
    finally:
        if conn: conn.close()

def get_employer_resident_details(employer_name: str):
    """根據指定的雇主名稱，查詢其所有在住員工的詳細住宿報告。"""
    if not employer_name:
        return pd.DataFrame()
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    try:
        query = """
            SELECT
                d.primary_manager AS "主要管理人",
                d.original_address AS "宿舍地址",
                r.room_number AS "房號",
                w.worker_name AS "姓名",
                w.gender AS "性別",
                w.nationality AS "國籍",
                w.monthly_fee AS "員工月費",
                w.special_status AS "特殊狀況"
            FROM Workers w
            LEFT JOIN Rooms r ON w.room_id = r.id
            LEFT JOIN Dormitories d ON r.dorm_id = d.id
            WHERE w.employer_name = ?
            AND (w.accommodation_end_date IS NULL OR w.accommodation_end_date = '' OR date(w.accommodation_end_date) > date('now', 'localtime'))
            ORDER BY d.original_address, r.room_number, w.worker_name
        """
        return pd.read_sql_query(query, conn, params=(employer_name,))
    finally:
        if conn: conn.close()

def get_employer_financial_summary(employer_name: str, year_month: str):
    """為指定雇主和月份，計算預估的收支與損益。"""
    conn = database.get_db_connection()
    if not conn: return {"total_income": 0, "total_expense": 0, "profit_loss": 0}
    try:
        # 1. 計算總收入
        income_query = """
            SELECT SUM(monthly_fee) as total_income
            FROM Workers
            WHERE employer_name = ?
            AND (accommodation_end_date IS NULL OR accommodation_end_date = '' OR date(accommodation_end_date) > date(?))
        """
        income_df = pd.read_sql_query(income_query, conn, params=(employer_name, f"{year_month}-01"))
        total_income = income_df['total_income'].sum() if not income_df.empty and pd.notna(income_df['total_income'].sum()) else 0

        # 2. 計算按比例分攤的總支出 (這是一個簡化計算，主要用於估算)
        # 找出該雇主員工住過的所有宿舍
        dorms_query = "SELECT DISTINCT r.dorm_id FROM Workers w JOIN Rooms r ON w.room_id = r.id WHERE w.employer_name = ?"
        dorms_df = pd.read_sql_query(dorms_query, conn, params=(employer_name,))
        if dorms_df.empty:
            return {"total_income": total_income, "total_expense": 0, "profit_loss": total_income}
            
        dorm_ids = tuple(dorms_df['dorm_id'].tolist())
        
        # 計算這些宿舍的總支出
        # ... 此處可複用 dashboard_model 中的複雜支出計算邏輯 ...
        # 為了簡化，我們先計算一個大概值：月租金 + (上月雜費 / 總人數 * 該雇主員工人數)
        total_expense = 0 # 預留給更複雜的計算

        return {
            "total_income": total_income,
            "total_expense": total_expense, # 暫時為0
            "profit_loss": total_income - total_expense
        }
    finally:
        if conn: conn.close()