import os
import unittest

os.environ["LUMEN_REVENUE_CAPTURE_V3_AUTORUN"] = "false"

import revenue_capture_v3_runtime as capture


class RevenueCaptureV3Tests(unittest.TestCase):
    def test_transform_routes_primary_cta_to_existing_service_form(self):
        source = (
            '<a class="cta" href="#contacto">Hablar con LUMEN</a>'
            '<p>Para oportunidades B2B, sourcing de proveedores o coordinación comercial:</p>\n'
            '          <p><a href="mailto:__CONTACT__">__CONTACT__</a></p>'
        )
        result = capture.transform_landing(source)
        self.assertIn('/services#consulta', result)
        self.assertIn('/intelligence', result)
        self.assertIn('mailto:__CONTACT__', result)
        self.assertNotIn('>Hablar con LUMEN<', result)

    def test_transform_is_idempotent(self):
        source = '<a class="cta" href="#contacto">Hablar con LUMEN</a>'
        once = capture.transform_landing(source)
        twice = capture.transform_landing(once)
        self.assertEqual(once, twice)

    def test_transform_does_not_create_payment_or_contract_language(self):
        source = '<a class="cta" href="#contacto">Hablar con LUMEN</a>'
        result = capture.transform_landing(source).lower()
        self.assertNotIn('pagar ahora', result)
        self.assertNotIn('contratar ahora', result)


if __name__ == "__main__":
    unittest.main()
