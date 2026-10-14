import tempfile
import unittest
import io
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from docx import Document
from openpyxl import load_workbook

from data_models import mail_model
from views import mail_view


class MailDocumentTests(unittest.TestCase):
    def _items(self, count):
        return [
            {
                "sequence_no": index,
                "recipient_name_snapshot": f"收件人{index}",
                "recipient_address_snapshot": f"地址{index}",
                "item_description": f"文件{index}",
                "tracking_no": None,
                "shipping_fee": None,
            }
            for index in range(1, count + 1)
        ]

    def test_admin_code_hash_can_be_verified(self):
        encoded = mail_model._hash_admin_code("2468", iterations=1000)
        algorithm, iterations, salt_text, _ = encoded.split("$", 3)
        self.assertEqual("pbkdf2_sha256", algorithm)
        import base64

        recreated = mail_model._hash_admin_code(
            "2468",
            base64.urlsafe_b64decode(salt_text.encode("ascii")),
            int(iterations),
        )
        self.assertEqual(encoded, recreated)

    def test_shipping_fee_parser_accepts_editor_empty_and_display_values(self):
        self.assertIsNone(mail_model._parse_shipping_fee(None))
        self.assertIsNone(mail_model._parse_shipping_fee(""))
        self.assertIsNone(mail_model._parse_shipping_fee(float("nan")))
        self.assertEqual("28", str(mail_model._parse_shipping_fee(28)))
        self.assertEqual("28", str(mail_model._parse_shipping_fee([28])))
        self.assertEqual("28", str(mail_model._parse_shipping_fee("[28]")))
        self.assertEqual("1200", str(mail_model._parse_shipping_fee("NT$ 1,200")))
        with self.assertRaisesRegex(ValueError, "單一數字"):
            mail_model._parse_shipping_fee([28, 30])
        with self.assertRaisesRegex(ValueError, "不接受小數"):
            mail_model._parse_shipping_fee("28.5")

    def test_sequential_tracking_numbers_preserve_width_and_suffix(self):
        numbers = mail_model.generate_sequential_tracking_numbers("0008", "12345", 3)
        self.assertEqual(["000812345", "000912345", "001012345"], numbers)

    def test_sequential_tracking_numbers_reject_overflow(self):
        with self.assertRaisesRegex(ValueError, "超過 2 碼"):
            mail_model.generate_sequential_tracking_numbers("99", "12345", 2)

    def test_save_batch_tracking_numbers_updates_items_in_sequence(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"status": "CREATED"}
        cursor.fetchall.return_value = [{"id": 21}, {"id": 22}]
        with (
            patch.object(mail_model.database, "get_db_connection", return_value=connection),
            patch.object(mail_model, "_audit") as audit,
        ):
            success, message = mail_model.save_batch_tracking_numbers(
                7, 1, ["000812345", "000912345"]
            )

        self.assertTrue(success, message)
        update_calls = [
            call.args[1]
            for call in cursor.execute.call_args_list
            if "SET tracking_no = %s" in call.args[0]
        ]
        self.assertEqual([("000812345", 21), ("000912345", 22)], update_calls)
        connection.commit.assert_called_once_with()
        audit.assert_called_once()

    def test_mail_user_editor_saves_changes_and_new_rows(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [{"id": 1}]
        rows = [
            {"id": 1, "啟用": True, "姓名": "王小明", "排序": 2},
            {"id": None, "啟用": True, "姓名": "陳小華", "排序": 1},
        ]
        with (
            patch.object(mail_model.database, "get_db_connection", return_value=connection),
            patch.object(mail_model, "_audit") as audit,
        ):
            success, message = mail_model.save_mail_users(rows, actor_user_id=1)

        self.assertTrue(success, message)
        self.assertIn("新增 1 筆", message)
        self.assertIn("更新 1 筆", message)
        connection.commit.assert_called_once_with()
        audit.assert_called_once()

    def test_mail_user_editor_requires_one_active_user(self):
        success, message = mail_model.save_mail_users(
            [{"id": 1, "啟用": False, "姓名": "王小明", "排序": 0}],
            actor_user_id=1,
        )
        self.assertFalse(success)
        self.assertIn("至少需要保留一位", message)

    def test_government_agency_editor_only_updates_changed_rows(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            {
                "id": 1,
                "is_active": True,
                "agency_name": "勞工局",
                "department_name": "外勞科",
                "postal_code": "408221",
                "address": "台中市南屯區精科路26號",
            },
            {
                "id": 2,
                "is_active": True,
                "agency_name": "移民署",
                "department_name": None,
                "postal_code": "100",
                "address": "台北市中正區廣州街15號",
            },
        ]
        rows = [
            {
                "id": 1,
                "啟用": True,
                "機關名稱": "勞工局",
                "部門": "外勞科",
                "郵遞區號": "408221",
                "地址": "台中市南屯區精科路26號",
            },
            {
                "id": 2,
                "啟用": True,
                "機關名稱": "移民署",
                "部門": "服務站",
                "郵遞區號": "100",
                "地址": "台北市中正區廣州街15號",
            },
        ]
        with (
            patch.object(mail_model.database, "get_db_connection", return_value=connection),
            patch.object(mail_model, "_audit") as audit,
        ):
            success, message = mail_model.save_government_agencies(rows, actor_user_id=1)

        self.assertTrue(success, message)
        self.assertIn("新增 0 筆、更新 1 筆、停用 0 筆", message)
        update_calls = [
            call for call in cursor.execute.call_args_list
            if "UPDATE mail_government_agencies SET" in call.args[0]
        ]
        self.assertEqual(1, len(update_calls))
        self.assertEqual(2, update_calls[0].args[1][-1])
        self.assertEqual(1, audit.call_args.kwargs["after"]["updated"])

    def test_government_agency_editor_reports_no_change(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [
            {
                "id": 1,
                "is_active": True,
                "agency_name": "勞工局",
                "department_name": None,
                "postal_code": "408221",
                "address": "台中市南屯區精科路26號",
            }
        ]
        rows = [
            {
                "id": 1,
                "啟用": True,
                "機關名稱": "勞工局",
                "部門": None,
                "郵遞區號": "408221",
                "地址": "台中市南屯區精科路26號",
            }
        ]
        with (
            patch.object(mail_model.database, "get_db_connection", return_value=connection),
            patch.object(mail_model, "_audit"),
        ):
            success, message = mail_model.save_government_agencies(rows, actor_user_id=1)

        self.assertTrue(success, message)
        self.assertIn("新增 0 筆、更新 0 筆、停用 0 筆", message)
        self.assertFalse(
            any(
                "UPDATE mail_government_agencies SET" in call.args[0]
                for call in cursor.execute.call_args_list
            )
        )
        connection.commit.assert_called_once_with()

    def test_employer_recipient_includes_workplace_postal_code(self):
        employer_rows = [
            {
                "id": 7,
                "employer_id": "EMP007",
                "employer_name": "測試公司",
                "address": "彰化縣福興鄉福工路2之1號",
                "postal_code": "506",
            }
        ]
        with patch.object(mail_model, "_fetch_all", side_effect=[employer_rows, []]):
            options = mail_model.get_recipient_options()

        self.assertEqual("506", options[0]["postal_code"])
        self.assertEqual("E:7", options[0]["key"])

    def test_bulk_workbook_uses_template_cells_and_adds_pages(self):
        batch = {
            "batch_no": "POST-TEST-00001",
            "submission_mode": "BULK_FORM",
            "template_filename": "郵局大宗掛號單.xlsx",
        }
        with patch.object(mail_model, "get_batch", return_value=(batch, self._items(41))):
            data, filename = mail_model.generate_bulk_workbook(1)

        self.assertEqual("郵局大宗掛號單_POST-TEST-00001.xlsx", filename)
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "result.xlsx"
            output.write_bytes(data)
            workbook = load_workbook(output)
        self.assertEqual(["P1", "P2"], workbook.sheetnames)
        self.assertEqual("收件人1", workbook["P1"]["D5"].value)
        self.assertIn("地址1", workbook["P1"]["H5"].value)
        self.assertEqual("收件人41", workbook["P2"]["D5"].value)
        self.assertIsNone(workbook["P2"]["D6"].value)
        self.assertEqual("共", workbook["P1"]["F45"].value)
        self.assertEqual(40, workbook["P1"]["G45"].value)
        self.assertEqual("件", workbook["P1"]["I45"].value)
        self.assertEqual(1, workbook["P2"]["G45"].value)
        self.assertIn("$A$1:$J$45", str(workbook["P2"].print_area))
        self.assertIn("$1:$4", str(workbook["P2"].print_title_rows))

    def test_b4_envelope_fills_frontend_labels(self):
        record = {
            "mail_no": "MAIL-TEST-1",
            "recipient_postal_code_snapshot": "408221",
            "recipient_name_snapshot": "台中市政府勞工局",
            "recipient_department_snapshot": "入國通報",
            "recipient_contact_snapshot": "林小姐",
            "recipient_address_snapshot": "台中市南屯區精科路26號",
            "sender_name_snapshot": "王小明",
            "item_description": "D02-阮氏水",
            "mail_service": "限時掛號",
        }
        with patch.object(mail_model, "get_mail_record", return_value=record):
            data, filename = mail_model.generate_envelope(1, "B4.docx")

        document = Document(io.BytesIO(data))
        lines = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        self.assertEqual(
            [
                "限時掛號",
                "408221",
                "台中市南屯區精科路26號",
                "台中市政府勞工局   收",
                "入國通報：林小姐",
                "D02-阮氏水",
            ],
            lines,
        )
        self.assertEqual("MAIL-TEST-1_台中市政府勞工局_信封.docx", filename)

    def test_named_envelopes_fill_frontend_labels_and_drop_stale_text_box(self):
        record = {
            "mail_no": "MAIL-TEST-2",
            "recipient_postal_code_snapshot": "408221",
            "recipient_name_snapshot": "台中市政府勞工局",
            "recipient_department_snapshot": "入國通報",
            "recipient_contact_snapshot": "林小姐",
            "recipient_address_snapshot": "台中市南屯區精科路26號",
            "item_description": "D02-阮氏水",
            "mail_service": "限時掛號",
        }
        for template_name in ("信封(大).docx", "信封(小).docx"):
            with self.subTest(template_name=template_name):
                with patch.object(mail_model, "get_mail_record", return_value=record):
                    data, filename = mail_model.generate_envelope(1, template_name)

                document = Document(io.BytesIO(data))
                lines = [
                    paragraph.text.strip()
                    for paragraph in document.paragraphs
                    if paragraph.text.strip()
                ]
                self.assertEqual(
                    [
                        "408221 台中市南屯區精科路26號",
                        "(D02-阮氏水)",
                        "台中市政府勞工局 收",
                        "入國通報：林小姐",
                        "限時掛號",
                    ],
                    lines,
                )
                xml = document.element.xml
                self.assertNotIn("txbxContent", xml)
                self.assertNotIn("蔦松", xml)
                self.assertEqual("MAIL-TEST-2_台中市政府勞工局_信封.docx", filename)

    def test_recipient_department_contact_uses_colon_only_between_two_values(self):
        cases = (
            ({}, ""),
            ({"recipient_department_snapshot": "人事部"}, "人事部"),
            ({"recipient_contact_snapshot": "林小姐"}, "林小姐"),
            (
                {
                    "recipient_department_snapshot": "人事部",
                    "recipient_contact_snapshot": "林小姐",
                },
                "人事部：林小姐",
            ),
        )
        for record, expected in cases:
            with self.subTest(record=record):
                self.assertEqual(expected, mail_model._recipient_department_contact(record))

    def test_new_filename_automatically_uses_frontend_field_labels(self):
        record = {
            "mail_no": "MAIL-TEST-3",
            "recipient_postal_code_snapshot": "500",
            "recipient_name_snapshot": "測試公司",
            "recipient_department_snapshot": "人事部",
            "recipient_contact_snapshot": "陳先生",
            "recipient_address_snapshot": "彰化縣測試路1號",
            "item_description": "測試文件",
            "mail_service": "限時掛號",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            template = template_dir / "自訂橫式信封.docx"
            document = Document()
            document.add_paragraph("郵遞區號 收件地址")
            document.add_paragraph("(寄送內容)")
            document.add_paragraph("收件人／單位名稱 收")
            department_contact = document.add_paragraph()
            department_contact.add_run("收件")
            department_contact.add_run("部門：")
            department_contact.add_run("收件聯絡人")
            document.add_paragraph("郵件種類")
            document.save(template)
            with (
                patch.object(mail_model, "TEMPLATE_DIR", template_dir),
                patch.object(mail_model, "get_mail_record", return_value=record),
            ):
                data, _ = mail_model.generate_envelope(1, template.name)

        output = Document(io.BytesIO(data))
        self.assertEqual(
            [
                "500 彰化縣測試路1號",
                "(測試文件)",
                "測試公司 收",
                "人事部：陳先生",
                "限時掛號",
            ],
            [paragraph.text for paragraph in output.paragraphs],
        )

    def test_envelope_template_replaces_paragraph_and_table_placeholders(self):
        record = {
            "mail_no": "MAIL-TEST-1",
            "recipient_postal_code_snapshot": "500",
            "recipient_name_snapshot": "測試公司",
            "recipient_department_snapshot": "人事部",
            "recipient_address_snapshot": "彰化縣測試路1號",
            "sender_name_snapshot": "王小明",
            "item_description": "測試文件",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            template = template_dir / "信封.docx"
            document = Document()
            document.add_paragraph("{{recipient_name}} {{recipient_address}}")
            table = document.add_table(rows=1, cols=1)
            table.cell(0, 0).text = "{{item_description}}"
            document.save(template)
            with (
                patch.object(mail_model, "TEMPLATE_DIR", template_dir),
                patch.object(mail_model, "get_mail_record", return_value=record),
            ):
                data, filename = mail_model.generate_envelope(1, "信封.docx")

        output = Document(io.BytesIO(data))
        self.assertIn("測試公司", output.paragraphs[0].text)
        self.assertIn("彰化縣測試路1號", output.paragraphs[0].text)
        self.assertEqual("測試文件", output.tables[0].cell(0, 0).text)
        self.assertEqual("MAIL-TEST-1_測試公司_信封.docx", filename)

    def test_history_excel_accepts_postgresql_timezone_datetime(self):
        records = [
            {
                "id": 1,
                "mail_no": "MAIL-TEST-1",
                "created_at": datetime(2026, 10, 14, 1, 30, tzinfo=timezone.utc),
                "operator_name": "王小明",
                "sender_type": "CLIENT",
                "sender_name_snapshot": "客戶甲",
                "recipient_name_snapshot": "測試公司",
                "recipient_address_snapshot": "測試地址",
                "item_description": "測試文件",
                "mail_service": "掛號",
                "status": "READY",
                "batch_no": None,
                "tracking_no": None,
                "shipping_fee": None,
            }
        ]
        dataframe = mail_view._records_dataframe(records)
        self.assertEqual("王小明", dataframe.loc[0, "操作人員"])
        self.assertEqual("代寄：客戶甲", dataframe.loc[0, "寄件名義"])
        self.assertIsNone(dataframe.loc[0, "建立時間"].tzinfo)
        self.assertEqual(9, dataframe.loc[0, "建立時間"].hour)
        output = io.BytesIO()
        dataframe.to_excel(output, index=False)
        self.assertGreater(len(output.getvalue()), 0)


    def test_company_sender_stores_no_sender_fields(self):
        sender, error = mail_model._normalize_sender({"sender_name": "應被忽略"})
        self.assertIsNone(error)
        self.assertEqual("COMPANY", sender["sender_type"])
        self.assertIsNone(sender["sender_name"])
        self.assertIsNone(sender["sender_address"])

    def test_on_behalf_sender_requires_name_and_address(self):
        _, error = mail_model._normalize_sender({"sender_type": "CUSTOM", "sender_name": "客戶甲"})
        self.assertIn("必填", error)
        _, error = mail_model._normalize_sender({"sender_type": "BOGUS"})
        self.assertIn("不正確", error)

    def test_custom_sender_drops_workplace_link(self):
        sender, error = mail_model._normalize_sender(
            {
                "sender_type": "CUSTOM",
                "sender_employer_workplace_id": 9,
                "sender_name": " 客戶甲 ",
                "sender_address": "台中市測試路1號",
                "sender_phone": "04-1234567",
            }
        )
        self.assertIsNone(error)
        self.assertIsNone(sender["sender_employer_workplace_id"])
        self.assertEqual("客戶甲", sender["sender_name"])
        self.assertEqual("04-1234567", sender["sender_phone"])

    def test_create_record_saves_operator_and_client_sender_separately(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [None, {"id": 5}]
        data = {
            "recipient_type": "CUSTOM",
            "recipient_name": "勞工局",
            "recipient_address": "台中市南屯區精科路26號",
            "item_description": "聘僱許可函",
            "sender_type": "CLIENT",
            "sender_employer_workplace_id": 7,
            "sender_name": "測試公司",
            "sender_postal_code": "506",
            "sender_address": "彰化縣福興鄉福工路2之1號",
            "sender_contact": "林小姐",
            "sender_phone": "04-7777777",
            "planned_shipping_fee": 36,
        }
        with (
            patch.object(mail_model.database, "get_db_connection", return_value=connection),
            patch.object(mail_model, "_audit"),
        ):
            success, message, record_id = mail_model.create_mail_record(1, "王小明", data)

        self.assertTrue(success, message)
        self.assertEqual(5, record_id)
        insert_sql, params = cursor.execute.call_args_list[1].args
        self.assertEqual(insert_sql.count("%s"), len(params))
        self.assertEqual(
            (1, "王小明", "CLIENT", 7, "測試公司", "506", "彰化縣福興鄉福工路2之1號", "林小姐", "04-7777777"),
            params[:9],
        )
        self.assertEqual(36, params[-2])

    def test_create_record_rejects_decimal_postage_before_database_access(self):
        data = {
            "recipient_type": "CUSTOM",
            "recipient_name": "勞工局",
            "recipient_address": "台中市南屯區精科路26號",
            "item_description": "聘僱許可函",
            "planned_shipping_fee": "28.5",
        }
        with patch.object(mail_model.database, "get_db_connection") as get_connection:
            success, message, record_id = mail_model.create_mail_record(1, "王小明", data)

        self.assertFalse(success)
        self.assertIn("不接受小數", message)
        self.assertIsNone(record_id)
        get_connection.assert_not_called()

    def test_create_batch_preserves_dragged_order_and_removes_duplicates(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [{"id": 3}, {"id": 1}, {"id": 2}]
        cursor.fetchone.return_value = {"id": 99}
        with (
            patch.object(mail_model.database, "get_db_connection", return_value=connection),
            patch.object(mail_model, "_audit"),
        ):
            success, message, batch_id = mail_model.create_batch(
                [3, 1, 3, 2], "REGULAR", 1, posting_date=date(2026, 10, 14)
            )

        self.assertTrue(success, message)
        self.assertEqual(99, batch_id)
        item_insert_params = [
            call.args[1]
            for call in cursor.execute.call_args_list
            if "INSERT INTO mail_batch_items" in call.args[0]
        ]
        self.assertEqual(
            [(99, 3, 1, None), (99, 1, 2, None), (99, 2, 3, None)],
            item_insert_params,
        )

    def test_envelope_template_fills_sender_placeholders(self):
        record = {
            "mail_no": "MAIL-TEST-2",
            "recipient_name_snapshot": "勞工局",
            "recipient_address_snapshot": "台中市南屯區精科路26號",
            "sender_type": "CLIENT",
            "sender_name_snapshot": "測試公司",
            "sender_postal_code_snapshot": "506",
            "sender_address_snapshot": "彰化縣福興鄉福工路2之1號",
            "sender_contact_snapshot": "林小姐",
            "sender_phone_snapshot": "04-7777777",
            "item_description": "文件",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            document = Document()
            document.add_paragraph("{{sender_postal_code}} {{sender_address}}")
            document.add_paragraph("{{sender_name}} {{sender_contact}} {{sender_phone}}")
            document.save(template_dir / "代寄.docx")
            with (
                patch.object(mail_model, "TEMPLATE_DIR", template_dir),
                patch.object(mail_model, "get_mail_record", return_value=record),
            ):
                data, _ = mail_model.generate_envelope(1, "代寄.docx")

        output = Document(io.BytesIO(data))
        self.assertEqual("506 彰化縣福興鄉福工路2之1號", output.paragraphs[0].text)
        self.assertEqual("測試公司 林小姐 04-7777777", output.paragraphs[1].text)

    def test_company_sender_leaves_sender_placeholders_blank(self):
        record = {
            "mail_no": "MAIL-TEST-3",
            "recipient_name_snapshot": "勞工局",
            "recipient_address_snapshot": "地址",
            "sender_type": "COMPANY",
            "item_description": "文件",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            template_dir = Path(temp_dir)
            document = Document()
            document.add_paragraph("[{{sender_name}}{{sender_address}}]")
            document.save(template_dir / "代寄.docx")
            with (
                patch.object(mail_model, "TEMPLATE_DIR", template_dir),
                patch.object(mail_model, "get_mail_record", return_value=record),
            ):
                data, _ = mail_model.generate_envelope(1, "代寄.docx")

        self.assertEqual("[]", Document(io.BytesIO(data)).paragraphs[0].text)

    def test_bulk_workbook_prints_backfilled_posting_date(self):
        batch = {
            "batch_no": "POST-20261001-00001",
            "submission_mode": "BULK_FORM",
            "template_filename": "郵局大宗掛號單.xlsx",
            "posting_date": date(2026, 10, 1),
        }
        with patch.object(mail_model, "get_batch", return_value=(batch, self._items(1))):
            data, _ = mail_model.generate_bulk_workbook(1)
        sheet = load_workbook(io.BytesIO(data))["P1"]
        self.assertEqual((115, 10, 1), (sheet["C2"].value, sheet["E2"].value, sheet["G2"].value))

    def test_create_batch_rejects_future_posting_date(self):
        future = date.today() + timedelta(days=1)
        success, message, batch_id = mail_model.create_batch([1], "REGULAR", 1, posting_date=future)
        self.assertFalse(success)
        self.assertIn("不可晚於今天", message)
        self.assertIsNone(batch_id)

    def test_receipt_file_named_by_batch_no_without_overwriting(self):
        upload = MagicMock()
        upload.name = "收據.PDF"
        upload.getvalue.return_value = b"%PDF-1.4 test"
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(mail_model, "RECEIPT_DIR", Path(temp_dir)):
                first = mail_model.save_receipt(upload, "POST-20261001-00001")
                second = mail_model.save_receipt(upload, "POST-20261001-00001")
        self.assertEqual("POST-20261001-00001.pdf", Path(first["path"]).name)
        self.assertEqual("POST-20261001-00001-2.pdf", Path(second["path"]).name)
        self.assertEqual("收據.PDF", first["original_name"])

    def _edit_data(self):
        return {
            "recipient_name": "勞工局",
            "recipient_address": "台中市南屯區精科路26號",
            "item_description": "聘僱許可函（更正）",
            "planned_shipping_fee": 36,
        }

    def test_update_record_allowed_before_dispatch(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        before = {
            "id": 5, "mail_no": "MAIL-1", "created_by_user_id": 1, "status": "BATCHED",
            "item_description": "聘僱許可函",
        }
        cursor.fetchone.side_effect = [
            before,
            {**before, "item_description": "聘僱許可函（更正）", "planned_shipping_fee": 36},
        ]
        with (
            patch.object(mail_model.database, "get_db_connection", return_value=connection),
            patch.object(mail_model, "_audit") as audit,
        ):
            success, message = mail_model.update_mail_record(5, 1, self._edit_data())

        self.assertTrue(success, message)
        update_sql, params = cursor.execute.call_args_list[1].args
        self.assertEqual(update_sql.count("%s"), len(params))
        self.assertEqual(36, params[-4])
        connection.commit.assert_called_once_with()
        self.assertEqual(
            {"item_description": "聘僱許可函（更正）", "planned_shipping_fee": 36},
            audit.call_args.kwargs["after"],
        )

    def test_update_record_blocked_after_dispatch_or_by_other_user(self):
        for status, owner, expected in (("DISPATCHED", 1, "不可再修改"), ("READY", 2, "自己建立")):
            connection = MagicMock()
            cursor = connection.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = {
                "id": 5, "mail_no": "MAIL-1", "created_by_user_id": owner, "status": status,
            }
            with patch.object(mail_model.database, "get_db_connection", return_value=connection):
                success, message = mail_model.update_mail_record(5, 1, self._edit_data())
            self.assertFalse(success)
            self.assertIn(expected, message)
            self.assertEqual(1, cursor.execute.call_count)
            connection.commit.assert_not_called()

    def test_update_dispatched_batch_changes_history_without_requiring_new_receipt(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {
            "id": 7,
            "status": "DISPATCHED",
            "total_shipping_fee": 72,
            "posting_date": date(2026, 10, 1),
            "receipt_file_path": "mail_receipts/original.pdf",
        }
        updates = [
            {"batch_item_id": 21, "tracking_no": " 0012345 ", "shipping_fee": 38}
        ]
        with (
            patch.object(mail_model.database, "get_db_connection", return_value=connection),
            patch.object(mail_model, "_audit") as audit,
        ):
            success, message = mail_model.update_dispatched_batch(
                7, 1, 80, updates, date(2026, 10, 2)
            )

        self.assertTrue(success, message)
        item_sql, item_params = cursor.execute.call_args_list[1].args
        self.assertIn("UPDATE mail_batch_items", item_sql)
        self.assertEqual(("0012345", 38, 21, 7), item_params)
        batch_sql, batch_params = cursor.execute.call_args_list[2].args
        self.assertNotIn("receipt_file_path", batch_sql)
        self.assertEqual((80, date(2026, 10, 2), 7), batch_params)
        self.assertEqual(
            "mail_receipts/original.pdf",
            audit.call_args.kwargs["after"]["receipt_file_path"],
        )
        connection.commit.assert_called_once_with()

    def test_update_dispatched_batch_can_replace_receipt(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {
            "id": 7,
            "status": "DISPATCHED",
            "total_shipping_fee": 72,
            "posting_date": date(2026, 10, 1),
            "receipt_file_path": "mail_receipts/original.pdf",
        }
        receipt = {
            "path": "mail_receipts/replacement.pdf",
            "original_name": "更正收據.pdf",
            "content_type": "application/pdf",
        }
        with (
            patch.object(mail_model.database, "get_db_connection", return_value=connection),
            patch.object(mail_model, "_audit"),
        ):
            success, message = mail_model.update_dispatched_batch(
                7, 1, 80, [], date(2026, 10, 2), receipt
            )

        self.assertTrue(success, message)
        batch_sql, batch_params = cursor.execute.call_args_list[1].args
        self.assertIn("receipt_file_path", batch_sql)
        self.assertEqual(
            (
                80,
                date(2026, 10, 2),
                "mail_receipts/replacement.pdf",
                "更正收據.pdf",
                "application/pdf",
                1,
                7,
            ),
            batch_params,
        )

    def test_update_dispatched_batch_rejects_unfinished_batch(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = {"id": 7, "status": "CREATED"}
        with patch.object(mail_model.database, "get_db_connection", return_value=connection):
            success, message = mail_model.update_dispatched_batch(
                7, 1, 80, [], date(2026, 10, 2)
            )

        self.assertFalse(success)
        self.assertIn("只有已結案", message)
        connection.commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
