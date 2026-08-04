"""
Unit tests for GraphProfile and GraphProfileManager in SimPad.
"""

import unittest
from src.profiles.manager import GraphProfile, GraphProfileManager


class TestGraphProfileManager(unittest.TestCase):

    def setUp(self):
        self.pm = GraphProfileManager()

    def test_profile_id_and_name(self):
        prof = GraphProfile(name="TestProfile", graph_data={"nodes": {}, "links": []}, is_preset=False)
        self.assertEqual(prof.name, "TestProfile")
        self.assertEqual(prof.id, "TestProfile")

        data_dict = prof.to_dict()
        self.assertIn("id", data_dict)
        self.assertIn("name", data_dict)
        self.assertEqual(data_dict["name"], "TestProfile")

        restored_prof = GraphProfile.from_dict(data_dict)
        self.assertEqual(restored_prof.name, "TestProfile")
        self.assertEqual(restored_prof.id, "TestProfile")

    def test_preset_star_indicator(self):
        displays = self.pm.list_display_names()
        self.assertTrue(len(displays) > 0)
        # Check that Default (preset) has star
        def_display = self.pm.get_display_name("Default")
        self.assertTrue(def_display.startswith("★ "))

    def test_rename_user_profile(self):
        # Create a temp clone to test renaming
        cloned, msg = self.pm.clone_profile("Default", new_name="TempForRenameTest")
        self.assertIsNotNone(cloned)
        self.assertEqual(msg, "OK")

        # Rename user profile
        renamed, rmsg = self.pm.rename_profile("TempForRenameTest", "RenamedUserProfileTest")
        self.assertIsNotNone(renamed)
        self.assertEqual(renamed.name, "RenamedUserProfileTest")

        # Clean up
        deleted, dmsg = self.pm.delete_profile("RenamedUserProfileTest")
        self.assertTrue(deleted)

    def test_preset_protection_against_rename_and_delete(self):
        # Renaming preset must fail
        renamed, rmsg = self.pm.rename_profile("Default", "NewDefaultName")
        self.assertIsNone(renamed)
        self.assertIn("read-only preset", rmsg)

        # Deleting preset must fail
        deleted, dmsg = self.pm.delete_profile("Default")
        self.assertFalse(deleted)
        self.assertIn("built-in preset", dmsg)




if __name__ == "__main__":
    unittest.main()
