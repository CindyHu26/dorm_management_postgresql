import unittest

from postal_code_lookup import infer_postal_code


class PostalCodeLookupTests(unittest.TestCase):
    def test_infers_code_from_full_address(self):
        self.assertEqual("505", infer_postal_code("彰化縣鹿港鎮民權路163號3樓"))

    def test_accepts_common_tai_character_variant(self):
        self.assertEqual("100", infer_postal_code("台北市中正區重慶南路一段"))

    def test_infers_unique_district_when_county_is_omitted(self):
        self.assertEqual("505", infer_postal_code("鹿港鎮中山路100號"))

    def test_does_not_guess_an_ambiguous_district(self):
        self.assertIsNone(infer_postal_code("中正區測試路1號"))

    def test_blank_address_has_no_default(self):
        self.assertIsNone(infer_postal_code(""))


if __name__ == "__main__":
    unittest.main()
