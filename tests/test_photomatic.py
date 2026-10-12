"""Country geometry, print rotations, exports, and existing-database migration."""
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="photomatic-tests-")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
from PIL import Image
from app import config, db, photomatic, processing as P
from synthetic import Fake, make_face


class CatalogTests(unittest.TestCase):
    def test_every_template_is_present_and_has_a_default_print(self):
        self.assertEqual(len(photomatic.COUNTRIES), 208)
        self.assertEqual(len(photomatic.PRINTS), 169)
        for c in photomatic.COUNTRIES.values():
            with self.subTest(country=c["name"]):
                self.assertTrue(c["width_mm"] > 0 and c["height_mm"] > 0)
                if c["use_overlay"]:
                    self.assertIsNotNone(c["overlay"])
                for printer in photomatic.PRINTERS:
                    layout = photomatic.default_print(c, printer)
                    self.assertEqual(layout["filename"].casefold(), c["default_print_name"].casefold())
                for asset in (c["flag"], c["overlay"]):
                    if asset:
                        self.assertTrue((config.BASE_DIR / asset.lstrip("/")).is_file())

    def test_codes_are_limited_to_uk_and_irish_passports(self):
        self.assertEqual({c["id"] for c in photomatic.COUNTRIES.values() if c["code_service"]}, {
            "united-kingdom-passport", "united-kingdom-online-renewal", "uk-online",
            "ireland-passport", "ireland-passport-online"})
        self.assertFalse(photomatic.country("ireland-public-services-card-online")["code_service"])

    def test_selected_uk_settings(self):
        c = photomatic.country()
        self.assertEqual(c["head"], [70, 64, 75])
        self.assertEqual(c["eyes"], [48, 42, 54])
        p = photomatic.default_print(c)
        self.assertEqual((p["width_px"], p["height_px"], p["dpi"]), (1844, 1240, 301))
        self.assertEqual(len(p["boxes"]), 6)
        self.assertTrue(all(b["landscape"] for b in p["boxes"]))


class ProcessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source, cls.analysis = make_face()

    def test_country_dimensions_and_eye_line(self):
        for country_id, expected in [("united-kingdom-passport", (1050, 1350)),
                                     ("usa-passport", (1500, 1500)),
                                     ("canada-passport", (1500, 2100)),
                                     ("nederland-passport", (1050, 1350)),
                                     ("ireland-passport-online", (900, 1200)),
                                     ("finland-passport", (1080, 1410))]:
            with self.subTest(country=country_id):
                result = P.process(self.source, analyzer=Fake(self.analysis), country_id=country_id,
                                   auto_adjust=False, fix_shadows=False, even_bg=False)
                self.assertIsNotNone(result.jpeg, result.checks)
                im = Image.open(io.BytesIO(result.jpeg))
                self.assertEqual(im.size, expected)
                self.assertFalse(any(c.key == "eyeposition" for c in result.checks))
                rgb = np.asarray(im)
                # Synthetic eye whites locate the actual eye line in the JPEG.
                eyes = (rgb.min(axis=2) > 242)
                ys = np.where(eyes)[0]
                self.assertGreater(len(ys), 0)
                self.assertAlmostEqual(float(np.median(ys)) / expected[1],
                                       photomatic.country(country_id)["eyes"][0] / 100, delta=0.012)

    def test_zoom_and_vertical_move_recheck_geometry(self):
        result = P.process(self.source, analyzer=Fake(self.analysis), country_id="united-kingdom-passport",
                           crop={"zoom": 1.1, "x": 0, "y": 12, "rotation": 0})
        self.assertIsNotNone(result.jpeg)
        self.assertTrue(any(c.key == "eyeposition" for c in result.checks))
        self.assertTrue(any(c.key == "headsize" for c in result.checks))

    def test_crown_uses_visible_hair_instead_of_fixed_extension(self):
        points = self.analysis.faces[0].points
        forehead = points[P.FOREHEAD][1]
        face_h = points[P.CHIN][1] - forehead
        mask = np.zeros_like(self.analysis.person_mask)
        cx = int((points[P.FACE_L][0] + points[P.FACE_R][0]) / 2)
        actual_crown = int(forehead - .6 * face_h)
        mask[actual_crown:int(forehead)+1, cx-200:cx+200] = 1
        self.assertAlmostEqual(P._crown_y(points, mask), actual_crown, delta=1)
        self.assertAlmostEqual(P._crown_y(points, None), forehead - .3 * face_h, delta=1)

    def test_freestyle_does_not_require_a_detected_face(self):
        blob = io.BytesIO()
        Image.new("RGB", (600, 900), "blue").save(blob, "JPEG")
        result = P.process(blob.getvalue(), country_id="free-style", analyzer=Fake(P.Analysis([], None)))
        self.assertTrue(result.ok)

    def test_background_evening_works_without_colour_adjustment(self):
        rgb = np.full((400, 300, 3), 220, np.uint8)
        rgb[:200] = 190
        mask = np.zeros((400, 300), np.float32)
        mask[:, 100:200] = 1
        rgb[:, 100:200] = (100, 140, 180)
        adjusted, notes = P.enhance(rgb, mask, (110, 100, 190, 300), even_bg=True, adjust=False)
        self.assertIn("background evened", notes)
        np.testing.assert_array_equal(adjusted[100:300, 130:170], rgb[100:300, 130:170])
        self.assertNotIn("colour cast removed", notes)


class PrintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        im = Image.new("RGB", (200, 300), "blue")
        im.paste("red", (0, 0, 200, 150))
        blob = io.BytesIO()
        im.save(blob, "JPEG", quality=100)
        cls.photo = blob.getvalue()

    def test_all_original_layouts_render_including_borderless_bleed(self):
        for layout in photomatic.PRINTS.values():
            with self.subTest(layout=layout["id"]):
                data = P.print_sheet(self.photo, template_id=layout["id"])
                im = Image.open(io.BytesIO(data))
                self.assertEqual(im.size, (layout["width_px"], layout["height_px"]))
                self.assertEqual(im.info["dpi"], (layout["dpi"], layout["dpi"]))

    def test_six_photos_are_rotated_without_stretching(self):
        im = Image.open(io.BytesIO(P.print_sheet(self.photo)))
        for box in photomatic.default_print(photomatic.country())["boxes"]:
            x, y, w, h = [P._mm(box[k]) for k in ("x_mm", "y_mm", "width_mm", "height_mm")]
            left = im.getpixel((x + w // 4, y + h // 2))
            right = im.getpixel((x + 3*w // 4, y + h // 2))
            self.assertGreater(left[2], 200)
            self.assertGreater(right[0], 200)

    def test_digital_save_templates(self):
        for country_id, size in [("united-kingdom-passport", (600, 771)),
                                 ("usa-passport", (600, 600)),
                                 ("canada-passport", (600, 840)),
                                 ("ireland-passport-online", (715, 951))]:
            with self.subTest(country=country_id):
                photo = P.save_photo(self.photo, country_id)
                self.assertEqual(Image.open(io.BytesIO(photo)).size, size)


class MigrationTests(unittest.TestCase):
    def test_migration_preserves_existing_issued_codes(self):
        with sqlite3.connect(config.DB_PATH) as c:
            c.executescript(db.SCHEMA)
            c.execute("INSERT INTO photos(id,code,status,source,created,expires) VALUES ('legacy123456','ABC12345','issued','shop',1,9999999999)")
        db.init()
        db.init()
        row = db.get("legacy123456")
        self.assertEqual(row["code"], "ABC12345")
        self.assertEqual(row["country_id"], "united-kingdom-passport")


if __name__ == "__main__":
    unittest.main(verbosity=2)
