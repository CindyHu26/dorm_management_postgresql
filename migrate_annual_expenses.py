import database
import json

def migrate():
    """
    一個安全、一次性的腳本，用於將舊的 AnnualExpenses 結構遷移到
    新的 ComplianceRecords + AnnualExpenses 結構。
    """
    print("===== 開始執行攤銷費用表格的結構升級程序 =====")
    conn = database.get_db_connection()
    if not conn:
        print("CRITICAL: 無法連接到資料庫，程序中止。")
        return

    try:
        with conn.cursor() as cursor:
            # 步驟 1: 備份舊的 AnnualExpenses 資料到記憶體
            print("INFO: 步驟 1/4 - 正在備份現有的 AnnualExpenses 資料...")
            try:
                cursor.execute('SELECT * FROM "AnnualExpenses" ORDER BY id;')
                old_annual_expenses = cursor.fetchall()
                print(f"  - 成功備份 {len(old_annual_expenses)} 筆資料。")
            except Exception as e:
                print(f"  - 警告: 讀取舊的 AnnualExpenses 表格失敗: {e}")
                print("  - 可能是表格已是新結構，或不存在。若您已執行過此腳本，可忽略此訊息。")
                old_annual_expenses = []


            # 步驟 2: 在一個交易中，重建表格
            print("INFO: 步驟 2/4 - 正在重建表格結構...")
            
            # 刪除舊的表格 (CASCADE 會一併處理關聯)
            cursor.execute('DROP TABLE IF EXISTS "AnnualExpenses" CASCADE;')
            cursor.execute('DROP TABLE IF EXISTS "ComplianceRecords" CASCADE;')
            print("  - 成功刪除舊的表格。")

            # 建立新的 ComplianceRecords 表格
            cursor.execute("""
            CREATE TABLE "ComplianceRecords" (
                "id" SERIAL PRIMARY KEY,
                "dorm_id" INTEGER NOT NULL,
                "record_type" VARCHAR(50) NOT NULL,
                "details" JSONB,
                "created_at" TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE
            );
            """)
            # 建立新的 AnnualExpenses 表格
            cursor.execute("""
            CREATE TABLE "AnnualExpenses" (
                "id" SERIAL PRIMARY KEY,
                "dorm_id" INTEGER NOT NULL,
                "compliance_record_id" INTEGER UNIQUE,
                "expense_item" VARCHAR(100) NOT NULL,
                "payment_date" DATE,
                "total_amount" INTEGER NOT NULL,
                "amortization_start_month" VARCHAR(7),
                "amortization_end_month" VARCHAR(7),
                "notes" TEXT,
                FOREIGN KEY ("dorm_id") REFERENCES "Dormitories" ("id") ON DELETE CASCADE,
                FOREIGN KEY ("compliance_record_id") REFERENCES "ComplianceRecords" ("id") ON DELETE SET NULL
            );
            """)
            print("  - 成功建立新的表格結構。")

            # 步驟 3: 將備份的資料轉換並寫入新表格
            if old_annual_expenses:
                print("INFO: 步驟 3/4 - 正在遷移備份資料至新結構...")
                for record in old_annual_expenses:
                    record_dict = dict(record)
                    expense_item = record_dict.get('expense_item')
                    
                    # 判斷是否為需要建立 Compliance Record 的特殊類型
                    if '建物申報' in expense_item or '保險' in expense_item:
                        # 建立 Compliance Record
                        compliance_details = {
                            "原始費用項目": expense_item,
                            "原始備註": record_dict.get('notes')
                            # 新增的欄位會是空的，待使用者從 UI 編輯
                        }
                        
                        insert_compliance_sql = """
                            INSERT INTO "ComplianceRecords" (dorm_id, record_type, details)
                            VALUES (%s, %s, %s) RETURNING id;
                        """
                        cursor.execute(insert_compliance_sql, (
                            record_dict['dorm_id'],
                            '建物申報' if '建物申報' in expense_item else '保險',
                            json.dumps(compliance_details, ensure_ascii=False)
                        ))
                        new_compliance_id = cursor.fetchone()['id']
                        
                        # 建立關聯的 AnnualExpense 紀錄
                        insert_annual_sql = """
                            INSERT INTO "AnnualExpenses" (dorm_id, compliance_record_id, expense_item, payment_date, total_amount, amortization_start_month, amortization_end_month, notes)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                        """
                        cursor.execute(insert_annual_sql, (
                            record_dict['dorm_id'], new_compliance_id, expense_item,
                            record_dict['payment_date'], record_dict['total_amount'],
                            record_dict['amortization_start_month'], record_dict['amortization_end_month'],
                            f"詳細資料請見合規紀錄 ID: {new_compliance_id}"
                        ))
                    else:
                        # 對於一般費用，直接寫入 AnnualExpenses
                        insert_annual_sql = """
                            INSERT INTO "AnnualExpenses" (dorm_id, expense_item, payment_date, total_amount, amortization_start_month, amortization_end_month, notes)
                            VALUES (%s, %s, %s, %s, %s, %s, %s);
                        """
                        cursor.execute(insert_annual_sql, (
                            record_dict['dorm_id'], expense_item,
                            record_dict['payment_date'], record_dict['total_amount'],
                            record_dict['amortization_start_month'], record_dict['amortization_end_month'],
                            record_dict.get('notes')
                        ))
                print(f"  - 成功遷移 {len(old_annual_expenses)} 筆資料。")
            else:
                print("INFO: 步驟 3/4 - 無舊資料需要遷移。")


        # 步驟 4: 提交交易
        conn.commit()
        print("INFO: 步驟 4/4 - 成功提交所有變更。")
        print("\n===== 攤銷費用表格結構升級成功！ =====")

    except Exception as e:
        print(f"CRITICAL: 遷移過程中發生錯誤，所有操作已復原: {e}")
        if conn:
            conn.rollback()
    finally:
        if conn:
            conn.close()

if __name__ == '__main__':
    # 在執行前，詢問使用者以確保安全
    confirm = input("這個腳本將會重建您的 AnnualExpenses 和 ComplianceRecords 表格，\n並嘗試遷移現有資料。這是一個無法復原的操作。\n\n您確定要繼續嗎？ (請輸入 'yes' 來確認): ")
    if confirm.lower() == 'yes':
        migrate()
    else:
        print("操作已取消。")