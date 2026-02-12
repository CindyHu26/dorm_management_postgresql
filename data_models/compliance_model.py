import database
import pandas as pd
import json

def get_compliance_flat_report(dorm_id=None, record_type=None):
    """取得展平後的合規資料，並依下次申報止倒序排序"""
    conn = database.get_db_connection()
    if not conn: return pd.DataFrame()
    
    try:
        query = """
            SELECT 
                c.id,
                d.original_address AS "宿舍",
                c.record_type AS "類別",
                c.details->>'declaration_item' AS "申報項目",
                c.details->>'approval_start_date' AS "核准起",
                c.details->>'approval_end_date' AS "核准止",
                c.details->>'next_declaration_start' AS "下次申報起",
                c.details->>'next_declaration_end' AS "下次申報止",
                (c.details->>'amount_pre_tax')::numeric AS "金額(未稅)",
                c.details->>'architect_name' AS "代辦人",
                c.details->>'invoice_date' AS "發票日期",
                c.details->>'area_legal' AS "法定面積",
                c.details AS "raw_details"
            FROM "ComplianceRecords" c
            JOIN "Dormitories" d ON c.dorm_id = d.id
            WHERE 1=1
        """
        params = []
        if dorm_id:
            query += " AND d.id = %s"
            params.append(dorm_id)
        if record_type:
            query += " AND c.record_type = %s"
            params.append(record_type)
            
        # 【修改點】改為 DESC 進行倒序排序
        query += " ORDER BY c.details->>'next_declaration_end' DESC"
        
        with conn.cursor() as cursor:
            cursor.execute(query, params)
            records = cursor.fetchall()
            df = pd.DataFrame(records) if records else pd.DataFrame()
        
        if not df.empty:
            # 確保型別正確以供編輯器使用
            date_cols = ["核准起", "核准止", "下次申報起", "下次申報止", "發票日期"]
            for col in date_cols:
                if col in df.columns:
                    df[col] = pd.to_datetime(df[col], errors='coerce').dt.date
                
        return df
    finally:
        conn.close()

def update_compliance_batch(edited_rows_dict, original_df):
    """批次更新合規紀錄 JSONB 內容"""
    conn = database.get_db_connection()
    if not conn: return False, "資料庫連線失敗"
    
    try:
        with conn.cursor() as cursor:
            for row_idx_str, changes in edited_rows_dict.items():
                row_idx = int(row_idx_str)
                record_id = int(original_df.iloc[row_idx]['id'])
                current_details = original_df.iloc[row_idx]['raw_details'] or {}
                
                mapping = {
                    "申報項目": "declaration_item",
                    "核准起": "approval_start_date",
                    "核准止": "approval_end_date",
                    "下次申報起": "next_declaration_start",
                    "下次申報止": "next_declaration_end",
                    "金額(未稅)": "amount_pre_tax",
                    "代辦人": "architect_name",
                    "發票日期": "invoice_date",
                    "法定面積": "area_legal"
                }
                
                for ui_col, new_val in changes.items():
                    if ui_col in mapping:
                        if hasattr(new_val, 'isoformat'):
                            new_val = new_val.isoformat()
                        current_details[mapping[ui_col]] = new_val
                
                cursor.execute(
                    'UPDATE "ComplianceRecords" SET details = %s WHERE id = %s',
                    (json.dumps(current_details), record_id)
                )
        conn.commit()
        return True, "更新成功"
    except Exception as e:
        conn.rollback()
        return False, f"更新錯誤: {e}"
    finally:
        conn.close()

def delete_compliance_record(record_id):
    """刪除合規紀錄"""
    conn = database.get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute('DELETE FROM "ComplianceRecords" WHERE id = %s', (record_id,))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()