import unittest
from unittest.mock import MagicMock, patch

import pandas as pd

from data_models import employer_workplace_model
import updater


class EmployerWorkplacePostalTests(unittest.TestCase):
    def test_excel_numeric_postal_code_is_normalized(self):
        self.assertEqual("506", employer_workplace_model._clean_postal_code(506.0))
        self.assertEqual("506001", employer_workplace_model._clean_postal_code("506001"))
        self.assertIsNone(employer_workplace_model._clean_postal_code(float("nan")))

    def test_report_sync_assigns_postal_code_only_to_work_address(self):
        cursor = MagicMock()
        fresh_df = pd.DataFrame(
            [
                {
                    "employer_id": "EMP001",
                    "employer_name": "測試公司",
                    "work_address": "彰化縣福興鄉福工路2之1號",
                    "company_address": "台中市西屯區台灣大道1號",
                    "approval_address": "",
                    "postal_code": "506",
                }
            ]
        )

        count = updater._sync_employer_workplaces(cursor, fresh_df, MagicMock())

        self.assertEqual(2, count)
        params = [call.args[1] for call in cursor.execute.call_args_list]
        by_address = {values[2]: values for values in params}
        self.assertEqual("506", by_address["彰化縣福興鄉福工路2之1號"][3])
        self.assertIsNone(by_address["台中市西屯區台灣大道1號"][3])

    def test_batch_import_writes_postal_code(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        dataframe = pd.DataFrame(
            [
                {
                    "雇主編號": "EMP001",
                    "雇主簡稱": "測試公司",
                    "工作地址": "彰化縣福興鄉福工路2之1號",
                    "郵遞區號": 506.0,
                    "座標": "",
                }
            ]
        )
        with patch.object(
            employer_workplace_model.database,
            "get_db_connection",
            return_value=connection,
        ):
            success_count, failed = employer_workplace_model.batch_import_workplaces(dataframe)

        self.assertEqual(1, success_count)
        self.assertTrue(failed.empty)
        self.assertEqual("506", cursor.execute.call_args.args[1][-1])
        connection.commit.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
