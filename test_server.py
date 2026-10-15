"""Basic regression tests for StudSift's core helpers."""
import unittest
import server

class StudSiftTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(server.classification("Brick 2 x 4"), "Bricks")
        self.assertEqual(server.classification("Plate 2 x 2"), "Plates")
        self.assertEqual(server.classification("Tile 1 x 2"), "Tiles")
        self.assertEqual(server.classification("Technic Axle 3"), "Technic")

    def test_part_identity_includes_colour(self):
        self.assertEqual(server.part_key("3001", "Red"), server.part_key("3001", "red"))
        self.assertNotEqual(server.part_key("3001", "Red"), server.part_key("3001", "Blue"))

    def test_confusable_colours_are_suggestions_only(self):
        self.assertTrue(server.likely_colour_confusion("Light Gray", "Light Bluish Gray"))
        self.assertTrue(server.likely_colour_confusion("Black", "Dark Bluish Gray"))
        self.assertFalse(server.likely_colour_confusion("Red", "Blue"))
        self.assertFalse(server.likely_colour_confusion("Black", "Black"))

    def test_data_files_defined(self):
        for key in ("inventory", "bags", "sets", "set_requirements", "set_pieces", "set_pick_staging"):
            self.assertIn(key, server.FILES)
        self.assertEqual(server.DEFAULT_CAPACITY, 100)

if __name__ == "__main__":
    unittest.main()
