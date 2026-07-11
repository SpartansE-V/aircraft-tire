from __future__ import annotations

import unittest


class AppBootTests(unittest.TestCase):
    def test_app_imports(self) -> None:
        from app.main import app

        self.assertEqual(app.title, "COLMAP Reconstruction API")


if __name__ == "__main__":
    unittest.main()
