import pandas as pd
import database


def _clean_text(value):
    if pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _clean_numeric(value):
    if pd.isna(value) or value == "":
        return None
    return float(value)


def get_all_workplaces():
    """
    獲取所有雇主工作地址清單
    回傳格式：[{'employer_id': '...', 'employer_name': '...', 'latitude': 25.0, 'longitude': 121.0, ...}, ...]
    """
    conn = database.get_db_connection()
    if not conn:
        return []
    try:
        query = 'SELECT * FROM "EmployerWorkplaces" ORDER BY employer_id NULLS LAST, employer_name'
        with conn.cursor() as cursor:
            cursor.execute(query)
            records = cursor.fetchall()
            return records
    except Exception as e:
        print(f"取得雇主工作地址失敗: {e}")
        return []
    finally:
        if conn:
            conn.close()


def get_workplace_editor_dataframe(search_term: str = None):
    """取得雇主工作地址維護頁所需資料。"""
    conn = database.get_db_connection()
    if not conn:
        return pd.DataFrame()

    try:
        query = """
            SELECT
                id,
                employer_id AS "雇主編號",
                employer_name AS "雇主簡稱",
                address AS "工作地址",
                latitude AS "緯度",
                longitude AS "經度"
            FROM "EmployerWorkplaces"
            WHERE 1 = 1
        """
        params = []

        if search_term:
            term = f"%{search_term}%"
            query += """
                AND (
                    employer_id ILIKE %s OR
                    employer_name ILIKE %s OR
                    address ILIKE %s
                )
            """
            params.extend([term, term, term])

        query += ' ORDER BY employer_id NULLS LAST, employer_name'
        with conn.cursor() as cursor:
            cursor.execute(query, tuple(params))
            records = cursor.fetchall()

        df = pd.DataFrame([dict(row) for row in records])
        if df.empty:
            return df
        for col in ["雇主編號", "雇主簡稱", "工作地址"]:
            if col in df.columns:
                df[col] = df[col].fillna("")
        return df
    except Exception as e:
        print(f"取得雇主工作地址維護資料失敗: {e}")
        return pd.DataFrame()
    finally:
        if conn:
            conn.close()


def batch_update_workplaces(edited_df: pd.DataFrame):
    """批次新增或更新雇主工作地址。"""
    if edited_df is None or edited_df.empty:
        return False, "沒有可儲存的資料。"

    conn = database.get_db_connection()
    if not conn:
        return False, "無法連接到資料庫"

    try:
        saved_count = 0
        with conn.cursor() as cursor:
            for _, row in edited_df.iterrows():
                workplace_id = row.get("id")
                employer_id = _clean_text(row.get("雇主編號"))
                employer_name = _clean_text(row.get("雇主簡稱"))
                address = _clean_text(row.get("工作地址"))
                latitude = _clean_numeric(row.get("緯度"))
                longitude = _clean_numeric(row.get("經度"))

                if not employer_name:
                    continue

                if latitude is not None and not (20 <= latitude <= 27):
                    conn.rollback()
                    return False, f"{employer_name} 的緯度超出台灣常用範圍，請確認。"
                if longitude is not None and not (118 <= longitude <= 123):
                    conn.rollback()
                    return False, f"{employer_name} 的經度超出台灣常用範圍，請確認。"
                if (latitude is None) != (longitude is None):
                    conn.rollback()
                    return False, f"{employer_name} 的經緯度需成對填寫，不能只填一邊。"

                if pd.isna(workplace_id):
                    cursor.execute(
                        """
                        INSERT INTO "EmployerWorkplaces" (employer_id, employer_name, latitude, longitude, address)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (employer_name)
                        DO UPDATE SET
                            employer_id = EXCLUDED.employer_id,
                            latitude = EXCLUDED.latitude,
                            longitude = EXCLUDED.longitude,
                            address = EXCLUDED.address
                        """,
                        (employer_id, employer_name, latitude, longitude, address)
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE "EmployerWorkplaces"
                        SET
                            employer_id = %s,
                            employer_name = %s,
                            latitude = %s,
                            longitude = %s,
                            address = %s
                        WHERE id = %s
                        """,
                        (employer_id, employer_name, latitude, longitude, address, int(workplace_id))
                    )
                saved_count += 1

        conn.commit()
        return True, f"已成功儲存 {saved_count} 筆雇主工作地址。"
    except Exception as e:
        if conn:
            conn.rollback()
        if isinstance(e, database.psycopg2.IntegrityError) and "unique constraint" in str(e).lower():
            return False, "儲存失敗：雇主簡稱不可重複。"
        return False, f"儲存雇主工作地址時發生錯誤: {e}"
    finally:
        if conn:
            conn.close()


def batch_import_workplaces(df: pd.DataFrame):
    """
    批次匯入或更新雇主工作地址
    df 需包含：雇主編號, 雇主簡稱, 座標 (如: 120.317056,23.798813)
    """
    if df.empty:
        return 0, pd.DataFrame()

    conn = database.get_db_connection()
    if not conn:
        return 0, df

    success_count = 0
    failed_records = []

    try:
        with conn.cursor() as cursor:
            for index, row in df.iterrows():
                try:
                    employer_id = str(row.get("雇主編號", "")).strip()
                    employer_name = str(row.get("雇主簡稱", "")).strip()
                    address = str(row.get("工作地址", "")).strip()
                    coord_str = str(row.get("座標", "")).strip()

                    if not employer_name:
                        raise ValueError("雇主簡稱不可為空")

                    latitude, longitude = None, None
                    if coord_str and coord_str.lower() != 'nan':
                        # 解析座標
                        parts = [p.strip() for p in coord_str.replace("，", ",").replace("、", ",").split(",")]
                        if len(parts) == 2:
                            first = float(parts[0])
                            second = float(parts[1])

                            # 判斷經緯度，台灣緯度約在 20-27，經度約在 118-123
                            if 20 <= first <= 27 and 118 <= second <= 123:
                                latitude, longitude = first, second
                            elif 118 <= first <= 123 and 20 <= second <= 27:
                                latitude, longitude = second, first
                            else:
                                raise ValueError("座標不在台灣常用範圍內")
                        else:
                            raise ValueError("座標格式不正確")

                    query = """
                    INSERT INTO "EmployerWorkplaces" (employer_id, employer_name, latitude, longitude, address)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (employer_name)
                    DO UPDATE SET
                        employer_id = EXCLUDED.employer_id,
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude,
                        address = EXCLUDED.address;
                    """
                    cursor.execute(query, (
                        employer_id if employer_id and employer_id.lower() != 'nan' else None,
                        employer_name,
                        latitude,
                        longitude,
                        address if address and address.lower() != 'nan' else None
                    ))
                    success_count += 1

                except Exception as row_e:
                    failed_record = row.to_dict()
                    failed_record["失敗原因"] = str(row_e)
                    failed_records.append(failed_record)

            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"批次匯入雇主工作地址發生錯誤: {e}")
        return 0, df
    finally:
        if conn:
            conn.close()

    return success_count, pd.DataFrame(failed_records)
