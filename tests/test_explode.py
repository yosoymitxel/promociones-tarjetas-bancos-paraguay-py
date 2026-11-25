import unittest

from scraper_modules.explode import explode, parse_affiliated_stores


STORE_LIST = """ALDO BERTONI BIRKENSTOCK EL MERCADILLO GAP MOSS UNDER ARMOUR VERONICA WILLIGS ALEMANIA CELL BRAUN CALVIN KLEIN CASA AMERICANA CUNA BELLA HERING HIGH LOW ISDIN JOYERIA ARMELE MAC MANGO ORAL B PALUPIA PARFOIS PILAR TL SPORT & OUTDOORS TOMMY HILFIGER VENDOME RELOJERIA AEROPOSTALE APHRODITE CASA MARIA CAT CHAMPS ELYSEÉS COLE HAAN COLUMBIA CROCS DENOIR ENEACHE FUSCHIA INDIAN EMPORIUM JOSEFINA KERASTASE LUPO MARIE MARIE MATCH MAYBELLINE MUAR NEW BALANCE NINE WEST ODETTE OPTICA VISION PIERRE LANNIER PLANET TOY PULSAK PUMA RND ROCHESTER RONDINA SCALA SKECHERS SPORT HOUSE TIMBERLAND TOTTO VERDAD CONSECUENCIA WRANGLER - LEE GNC VERNIER BIBI"""


def sample_promo(bank_id="itau", description=None):
    return {
        "id": "itau-ab12cd34",
        "title": "Primer Martes",
        "desc": description or f"Beneficio: hasta 25% de ahorro. Bases y condiciones. Locales adheridos: {STORE_LIST}",
        "img": "https://example.test/logo-varios.png",
        "href": "https://www.itau.com.py/beneficios2/Detalle?b=123&c=456",
        "bankId": bank_id,
        "bankShort": "Itaú",
        "bankColor": "#FF6B00",
        "category": "Otros",
        "discount_percent": 25,
        "days": ["Martes"],
        "installments": 10,
        "validity": "Del 6 de enero al 1 de diciembre de 2026",
        "expired": False,
    }


class ItaúAffiliatedStoreTests(unittest.TestCase):
    def test_catalog_segments_full_list_without_splitting_compound_names(self):
        stores = parse_affiliated_stores(STORE_LIST)
        self.assertEqual(len(stores), 66)
        self.assertEqual(stores[:4], ["ALDO", "BERTONI", "BIRKENSTOCK", "EL MERCADILLO"])
        self.assertIn("UNDER ARMOUR", stores)
        self.assertIn("VERONICA WILLIGS", stores)
        self.assertIn("TL SPORT & OUTDOORS", stores)
        self.assertIn("VERDAD CONSECUENCIA", stores)
        self.assertIn("WRANGLER - LEE", stores)

    def test_explode_keeps_parent_and_adds_one_promo_per_store(self):
        original = sample_promo()
        result = explode([original])
        self.assertEqual(len(result), 67)

        parent = result[0]
        self.assertEqual(parent["title"], "Primer Martes")
        self.assertEqual(parent["affiliated_stores"], parse_affiliated_stores(STORE_LIST))
        self.assertNotIn("Locales adheridos:", parent["desc"])

        aldo = next(p for p in result if p["title"] == "ALDO")
        bertoni = next(p for p in result if p["title"] == "BERTONI")
        verdad = next(p for p in result if p["title"] == "VERDAD CONSECUENCIA")
        self.assertNotEqual(aldo["id"], bertoni["id"])
        for child in (aldo, bertoni, verdad):
            self.assertEqual(child["parent_id"], parent["id"])
            self.assertEqual(child["group"], parent["title"])
            self.assertEqual(child["bankId"], "itau")
            self.assertEqual(child["discount_percent"], 25)
            self.assertEqual(child["days"], ["Martes"])
            self.assertEqual(child["installments"], 10)
            self.assertEqual(child["href"], parent["href"])
            self.assertIsNone(child["img"] or None)
            self.assertNotIn("affiliated_stores", child)

    def test_unknown_name_blocks_partial_expansion(self):
        original = sample_promo(description="Bases. Locales adheridos: ALDO BERTONI LOCAL NUEVO")
        result = explode([original])
        self.assertEqual(result, [original])
        self.assertNotIn("affiliated_stores", result[0])

    def test_non_itau_promotion_is_unchanged(self):
        original = sample_promo(bank_id="gnb")
        result = explode([original])
        self.assertEqual(result, [original])
        self.assertNotIn("affiliated_stores", result[0])


if __name__ == "__main__":
    unittest.main()
