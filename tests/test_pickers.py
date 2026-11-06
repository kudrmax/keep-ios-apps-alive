import json
import plistlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from installer.devices import Device, DevicePicker, Devices
from installer.errors import InstallError
from installer.profiles import ProfileMatcher, ProfileRefresh
from installer.xcode import DestinationCheck, PlatformCheck, SchemePicker, TeamPicker, XcodeInstall


def device(name, wired=False, connected=False):
    return Device(identifier=name, udid=name, name=name, wired=wired, connected=connected)


class DevicePickerTest(unittest.TestCase):
    def test_prefers_connected_then_wired(self):
        devices = [device("offline", wired=True), device("wifi", connected=True),
                   device("cable", wired=True, connected=True)]
        self.assertEqual(DevicePicker.pick(devices, None).name, "cable")

    def test_connected_wifi_beats_offline_cable(self):
        devices = [device("offline", wired=True), device("wifi", connected=True)]
        self.assertEqual(DevicePicker.pick(devices, None).name, "wifi")

    def test_preferred_name(self):
        devices = [device("a", wired=True, connected=True), device("b")]
        self.assertEqual(DevicePicker.pick(devices, "b").name, "b")

    def test_unknown_preferred_name(self):
        with self.assertRaises(InstallError):
            DevicePicker.pick([device("a")], "b")

    def test_no_devices(self):
        with self.assertRaises(InstallError):
            DevicePicker.pick([], None)


class ListingShell:
    """Answers `devicectl list devices` with one paired iPhone, its tunnel up or down."""

    def __init__(self, tunnel):
        self.tunnel = tunnel

    def run(self, args, cwd=None):
        listing = {"result": {"devices": [{
            "identifier": "PHONE",
            "hardwareProperties": {"deviceType": "iPhone", "udid": "UDID"},
            "deviceProperties": {"name": "iPhone"},
            "connectionProperties": {"pairingState": "paired", "transportType": "localNetwork", "tunnelState": self.tunnel},
        }]}}
        Path(args[args.index("--json-output") + 1]).write_text(json.dumps(listing))
        return subprocess.CompletedProcess(args, 0, "", "")


class ReachableTest(unittest.TestCase):
    def test_reachable_only_while_the_tunnel_is_up(self):
        phone = device("PHONE")
        self.assertTrue(Devices(ListingShell("connected")).reachable(phone))
        self.assertFalse(Devices(ListingShell("unavailable")).reachable(phone))


class SchemePickerTest(unittest.TestCase):
    def test_single_scheme(self):
        self.assertEqual(SchemePicker.pick(["App"], "Project", None), "App")

    def test_scheme_named_after_project(self):
        self.assertEqual(SchemePicker.pick(["Shop", "ShopWidgets"], "Shop", None), "Shop")

    def test_ambiguous(self):
        with self.assertRaises(InstallError):
            SchemePicker.pick(["A", "B"], "Project", None)

    def test_preferred_must_exist(self):
        with self.assertRaises(InstallError):
            SchemePicker.pick(["A"], "Project", "B")


class TeamPickerTest(unittest.TestCase):
    def test_single_team(self):
        self.assertEqual(TeamPicker.pick({"ABC": "Personal"}, None), "ABC")

    def test_several_teams_need_a_choice(self):
        with self.assertRaises(InstallError):
            TeamPicker.pick({"ABC": "a", "DEF": "b"}, None)

    def test_no_teams(self):
        with self.assertRaises(InstallError):
            TeamPicker.pick({}, None)


class XcodeChoiceTest(unittest.TestCase):
    DESTINATIONS = """
        { platform:iOS, arch:arm64, id:PHONE, name:Max }
        { platform:iOS, arch:arm64e, id:OTHER, name:Old, error:iOS 26.5 is not installed. }
    """

    def test_device_without_error_is_supported(self):
        self.assertTrue(DestinationCheck.supports(self.DESTINATIONS, "PHONE"))

    def test_device_with_error_is_not_supported(self):
        self.assertFalse(DestinationCheck.supports(self.DESTINATIONS, "OTHER"))

    def test_absent_device_is_not_supported(self):
        self.assertFalse(DestinationCheck.supports(self.DESTINATIONS, "NONE"))

    def test_listed_with_or_without_error(self):
        self.assertTrue(DestinationCheck.listed(self.DESTINATIONS, "PHONE"))
        self.assertTrue(DestinationCheck.listed(self.DESTINATIONS, "OTHER"))
        self.assertFalse(DestinationCheck.listed(self.DESTINATIONS, "NONE"))

    def test_versions_compare_numerically(self):
        versions = [XcodeInstall(Path(v), v) for v in ["26.3", "16.4", "26.10"]]
        self.assertEqual([x.version for x in sorted(versions, key=lambda x: x.version_key, reverse=True)],
                         ["26.10", "26.3", "16.4"])


class PlatformCheckTest(unittest.TestCase):
    def test_missing_platform(self):
        output = "{ platform:iOS, name:Any iOS Device, error:iOS 26.5 is not installed. Please download ... }"
        self.assertIn("iOS 26.5", str(PlatformCheck.error(output)))

    def test_other_errors(self):
        self.assertIsNone(PlatformCheck.error("error: Signing requires a development team"))


class ProfileMatcherTest(unittest.TestCase):
    def test_exact_bundle_and_team(self):
        self.assertTrue(ProfileMatcher.matches("TEAM.com.app", "TEAM", ["com.app"]))

    def test_extension_of_the_app(self):
        self.assertTrue(ProfileMatcher.matches("TEAM.com.app.widget", "TEAM", ["com.app"]))

    def test_app_with_a_longer_name_is_not_a_match(self):
        self.assertFalse(ProfileMatcher.matches("TEAM.com.apple", "TEAM", ["com.app"]))

    def test_other_team(self):
        self.assertFalse(ProfileMatcher.matches("OTHER.com.app", "TEAM", ["com.app"]))

    def test_wildcard_profile(self):
        self.assertFalse(ProfileMatcher.matches("TEAM.*", "TEAM", ["com.app"]))


class FakeShell:
    """Decodes a profile file as the plist it contains instead of calling `security`; `trash` deletes for real."""

    def run(self, args, cwd=None):
        if args[0] == "security":
            return subprocess.CompletedProcess(args, 0, Path(args[-1]).read_text(), "")
        return subprocess.run(args, capture_output=True, text=True)


class ProfileRefreshTest(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.mine = self._profile("mine", "TEAM.com.app")
        self.widget = self._profile("widget", "TEAM.com.app.widget")
        self.other = self._profile("other", "TEAM.com.other")

    def tearDown(self):
        subprocess.run(["trash", str(self.folder)])

    def _profile(self, name, application_identifier):
        path = self.folder / f"{name}.mobileprovision"
        path.write_bytes(plistlib.dumps({"Entitlements": {"application-identifier": application_identifier}}))
        return path

    def _refresh(self):
        return ProfileRefresh(FakeShell(), "TEAM", ["com.app"], [self.folder])

    def test_sets_aside_only_this_app(self):
        refresh = self._refresh()
        self.assertEqual(sorted(refresh.set_aside()), ["com.app", "com.app.widget"])
        self.assertFalse(self.mine.exists())
        self.assertFalse(self.widget.exists())
        self.assertTrue(self.other.exists())
        refresh.commit()

    def test_restore_puts_profiles_back(self):
        refresh = self._refresh()
        refresh.set_aside()
        refresh.restore()
        self.assertTrue(self.mine.exists())
        self.assertTrue(self.widget.exists())


if __name__ == "__main__":
    unittest.main()
