import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import save_path_finder_linux as linux_finder
from common import shortcut_utils, steam_utils


@pytest.fixture
def isolated_linux_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    xdg_data = tmp_path / "xdg-data"
    xdg_config = tmp_path / "xdg-config"
    home.mkdir()
    xdg_data.mkdir()
    xdg_config.mkdir()

    real_expanduser = os.path.expanduser

    def fake_expanduser(path):
        if path == "~":
            return str(home)
        if isinstance(path, str) and path.startswith("~/"):
            return str(home / Path(path[2:]))
        return real_expanduser(path)

    monkeypatch.setattr(linux_finder.os.path, "expanduser", fake_expanduser)
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg_config))
    monkeypatch.setattr(
        linux_finder.config,
        "LINUX_KNOWN_SAVE_LOCATIONS",
        [
            "~/.local/share",
            "~/.config",
            "~/.var/app",
            "~/Games",
            "~",
        ],
    )
    monkeypatch.setattr(linux_finder.config, "LINUX_ENABLE_SNAP_SEARCH", False)
    monkeypatch.setattr(
        linux_finder.config, "LINUX_ENABLE_PROTON_SCAN_NONSTEAM", False
    )
    monkeypatch.setattr(linux_finder.config, "LINUX_SKIP_HOME_FALLBACK", True)
    monkeypatch.setattr(linux_finder.config, "LINUX_MAX_RESULTS", 20, raising=False)

    return {
        "home": home,
        "xdg_data": xdg_data,
        "xdg_config": xdg_config,
    }


def test_never_returns_synthesised_nonexistent_aliases(isolated_linux_home):
    home = isolated_linux_home["home"]
    for relative in (".local/share", ".config", ".var/app", "Games"):
        (home / Path(relative)).mkdir(parents=True, exist_ok=True)

    results = linux_finder.guess_save_path(
        "Dark Souls II: Scholar of the First Sin",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results == []
    aliases = {
        alias.casefold()
        for alias in linux_finder.generate_abbreviations(
            "Dark Souls II: Scholar of the First Sin"
        )
    }
    assert "dark" not in aliases


def test_steam_libraries_reads_current_steamapps_vdf(tmp_path, monkeypatch):
    steam_root = tmp_path / "Steam"
    external_library = tmp_path / "sd-card" / "SteamLibrary"
    (steam_root / "steamapps").mkdir(parents=True)
    (external_library / "steamapps").mkdir(parents=True)
    modern_vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    modern_vdf.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        steam_utils,
        "get_steam_install_path",
        lambda: str(steam_root),
    )

    def fake_parse_vdf(path):
        if os.path.normpath(path) == os.path.normpath(str(modern_vdf)):
            return {
                "libraryfolders": {
                    "0": {"path": str(steam_root)},
                    "1": {"path": str(external_library)},
                }
            }
        return None

    monkeypatch.setattr(steam_utils, "_parse_vdf", fake_parse_vdf)
    monkeypatch.setattr(steam_utils, "_steam_libraries", None)

    assert steam_utils.find_steam_libraries() == [
        os.path.normpath(str(steam_root)),
        os.path.normpath(str(external_library)),
    ]


@pytest.mark.parametrize(
    "relative_root",
    [
        ".var/app/com.valvesoftware.Steam/.local/share/Steam",
        "snap/steam/common/.local/share/Steam",
    ],
)
def test_linux_steam_detection_supports_packaged_layouts(
    tmp_path, monkeypatch, relative_root
):
    home = tmp_path / "home"
    steam_root = home / Path(relative_root)
    (steam_root / "steamapps").mkdir(parents=True)
    (steam_root / "userdata").mkdir()

    real_expanduser = os.path.expanduser

    def fake_expanduser(path):
        if path == "~":
            return str(home)
        if isinstance(path, str) and path.startswith("~/"):
            return str(home / Path(path[2:]))
        return real_expanduser(path)

    monkeypatch.setattr(steam_utils.os.path, "expanduser", fake_expanduser)
    monkeypatch.setenv("XDG_DATA_HOME", str(home / ".local" / "share"))

    assert steam_utils._find_steam_linux() == os.path.normpath(
        str(steam_root)
    )


def test_dark_souls_proton_leaf_is_top_on_external_library(
    isolated_linux_home, tmp_path
):
    library = tmp_path / "sd-card" / "SteamLibrary"
    install_dir = (
        library
        / "steamapps"
        / "common"
        / "Dark Souls II Scholar of the First Sin"
    )
    save_leaf = (
        library
        / "steamapps"
        / "compatdata"
        / "335300"
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Roaming"
        / "DarkSoulsII"
        / "123456789"
    )
    install_dir.mkdir(parents=True)
    save_leaf.mkdir(parents=True)
    (save_leaf / "DS2SOFS0000.sl2").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Dark Souls II: Scholar of the First Sin",
        game_install_dir=str(install_dir),
        appid=335300,
        is_steam_game=True,
    )

    assert results
    assert results[0][0] == os.path.normpath(str(save_leaf))
    assert results[0][2] is True
    assert all(os.path.isdir(path) for path, _, _ in results)
    assert len({_canonical(path) for path, _, _ in results}) == len(results)
    assert not any(
        os.path.basename(path).casefold()
        in {"pfx", "appdata", "local", "locallow", "roaming", "documents"}
        for path, _, _ in results
    )


def test_native_unity_path_respects_custom_xdg_config(isolated_linux_home):
    product_dir = (
        isolated_linux_home["xdg_config"]
        / "unity3d"
        / "Unknown Indie Studio"
        / "Hollow Knight"
    )
    product_dir.mkdir(parents=True)
    (product_dir / "user1.dat").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Hollow Knight",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(product_dir))
    assert results[0][2] is True
    assert all(
        os.path.basename(path).casefold()
        not in {"unity3d", "unknown indie studio"}
        for path, _, _ in results
    )


def test_unity_publisher_with_matching_game_is_prioritised_beyond_scan_cap(
    isolated_linux_home
):
    unity_root = isolated_linux_home["xdg_config"] / "unity3d"
    unity_root.mkdir()
    for index in range(80):
        (unity_root / f"AA Decoy Studio {index:03d}").mkdir()

    product_dir = (
        unity_root
        / "ZZ Target Studio"
        / "Hollow Knight"
    )
    product_dir.mkdir(parents=True)
    (product_dir / "user1.dat").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Hollow Knight",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(product_dir))


def test_unreal_internal_project_name_uses_appid_scope(
    isolated_linux_home, tmp_path
):
    library = tmp_path / "SteamLibrary"
    install_dir = (
        library / "steamapps" / "common" / "Deep Rock Galactic"
    )
    save_leaf = (
        library
        / "steamapps"
        / "compatdata"
        / "548430"
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Local"
        / "FSD"
        / "Saved"
        / "SaveGames"
    )
    install_dir.mkdir(parents=True)
    save_leaf.mkdir(parents=True)
    (save_leaf / "Player.sav").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Deep Rock Galactic",
        game_install_dir=str(install_dir),
        appid=548430,
        is_steam_game=True,
    )

    assert results[0][0] == os.path.normpath(str(save_leaf))
    assert results[0][2] is True


def test_install_tree_without_save_evidence_does_not_flood_results(
    isolated_linux_home, tmp_path
):
    install_dir = tmp_path / "Dark Souls II Scholar of the First Sin"
    (install_dir / "Game" / "Param").mkdir(parents=True)
    (install_dir / "Game" / "font" / "Korean").mkdir(parents=True)
    (install_dir / "Game" / "NGWord" / "Korean").mkdir(parents=True)
    (install_dir / "Game" / "Param" / "database.db").write_bytes(
        b"install asset"
    )

    results = linux_finder.guess_save_path(
        "Dark Souls II: Scholar of the First Sin",
        game_install_dir=str(install_dir),
        is_steam_game=False,
    )

    assert results == []


def test_system_bin_launcher_is_never_a_save_candidate(
    isolated_linux_home, tmp_path
):
    system_bin = tmp_path / "bin"
    system_bin.mkdir()
    (system_bin / "savegame.sav").write_bytes(b"false positive")

    results = linux_finder.guess_save_path(
        "No Man's Sky",
        game_install_dir=str(system_bin),
        is_steam_game=False,
    )

    assert results == []


def test_no_mans_sky_unowned_compatdata_without_steam_or_wine(
    isolated_linux_home, tmp_path, monkeypatch
):
    install_stub = tmp_path / "bin"
    install_stub.mkdir()
    compatdata = (
        isolated_linux_home["home"]
        / ".local"
        / "share"
        / "Steam"
        / "steamapps"
        / "compatdata"
    )
    save_dir = (
        compatdata
        / "275850"
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Roaming"
        / "HelloGames"
        / "NMS"
    )
    save_dir.mkdir(parents=True)
    (save_dir / "save.hg").write_bytes(b"save")
    (save_dir / "accountdata.hg").write_bytes(b"account")

    unrelated = (
        compatdata
        / "111111"
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Roaming"
        / "UnrelatedGame"
        / "Saves"
    )
    unrelated.mkdir(parents=True)
    (unrelated / "slot1.sav").write_bytes(b"other game")
    monkeypatch.setattr(
        linux_finder.config,
        "LINUX_ENABLE_PROTON_SCAN_NONSTEAM",
        True,
    )

    results = linux_finder.guess_save_path(
        "No Man's Sky",
        game_install_dir=str(install_stub),
        is_steam_game=False,
    )

    assert results
    assert results[0][0] == os.path.normpath(
        str(save_dir)
    )
    assert not any(
        os.path.normpath(str(unrelated)) == path
        for path, _, _ in results
    )
    assert all(
        os.path.basename(path).casefold() != "bin"
        for path, _, _ in results
    )


def test_desktop_name_preserves_full_game_identity(tmp_path):
    desktop_file = tmp_path / "BindingOfIsaac.desktop"
    desktop_file.write_text(
        "\n".join(
            [
                "[Desktop Entry]",
                "Version=1.0",
                "Type=Application",
                "Name=The Binding of Isaac: Rebirth",
                (
                    'Exec="/home/test/FakeGameInstalls/'
                    'BindingOfIsaac/isaac.sh"'
                ),
                "Terminal=false",
            ]
        ),
        encoding="utf-8",
    )

    parsed = shortcut_utils.parse_linux_desktop_entry(
        str(desktop_file)
    )

    assert parsed["Name"] == "The Binding of Isaac: Rebirth"
    assert parsed["Exec"].endswith(
        'FakeGameInstalls/BindingOfIsaac/isaac.sh"'
    )


def test_binding_of_isaac_rebirth_unowned_compatdata(
    isolated_linux_home, tmp_path, monkeypatch
):
    install_dir = tmp_path / "FakeGameInstalls" / "BindingOfIsaac"
    install_dir.mkdir(parents=True)
    (install_dir / "isaac.sh").write_text(
        "#!/bin/sh\n", encoding="utf-8"
    )
    save_dir = (
        isolated_linux_home["home"]
        / ".local"
        / "share"
        / "Steam"
        / "steamapps"
        / "compatdata"
        / "250900"
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "Documents"
        / "My Games"
        / "Binding of Isaac Rebirth"
    )
    save_dir.mkdir(parents=True)
    (save_dir / "persistentgamedata1.dat").write_bytes(b"save")
    (save_dir / "options.ini").write_text(
        "[Options]\n", encoding="utf-8"
    )
    monkeypatch.setattr(
        linux_finder.config,
        "LINUX_ENABLE_PROTON_SCAN_NONSTEAM",
        True,
    )

    results = linux_finder.guess_save_path(
        "The Binding of Isaac Rebirth",
        game_install_dir=str(install_dir),
        is_steam_game=False,
    )

    assert results
    assert results[0][0] == os.path.normpath(str(save_dir))


def test_binding_of_isaac_rebirth_native_xdg_layout(
    isolated_linux_home, tmp_path
):
    install_dir = tmp_path / "FakeGameInstalls" / "BindingOfIsaac"
    install_dir.mkdir(parents=True)
    (install_dir / "isaac.sh").write_text(
        "#!/bin/sh\n", encoding="utf-8"
    )
    save_dir = (
        isolated_linux_home["xdg_data"]
        / "binding of isaac rebirth"
    )
    save_dir.mkdir()
    (save_dir / "persistentgamedata1.dat").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "The Binding of Isaac Rebirth",
        game_install_dir=str(install_dir),
        is_steam_game=False,
    )

    assert results
    assert results[0][0] == os.path.normpath(str(save_dir))


def test_unrelated_install_directory_needs_game_context(
    isolated_linux_home, tmp_path
):
    launcher_target = tmp_path / "GenericLauncherTarget"
    launcher_target.mkdir()
    (launcher_target / "save01.sav").write_bytes(b"false positive")

    results = linux_finder.guess_save_path(
        "Celeste",
        game_install_dir=str(launcher_target),
        is_steam_game=False,
    )

    assert results == []


def test_short_title_does_not_adopt_install_container_as_alias(
    isolated_linux_home
):
    install_dir = (
        isolated_linux_home["home"] / "FakeGameInstalls" / "FTL"
    )
    install_dir.mkdir(parents=True)
    (install_dir / "ftl.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    aliases = {
        linux_finder.clean_for_comparison(alias)
        for alias in linux_finder.generate_abbreviations(
            "FTL", str(install_dir)
        )
    }

    assert "fakegameinstalls" not in aliases


def test_linux_shell_executable_supplies_shortened_title_hint(
    isolated_linux_home, tmp_path, monkeypatch
):
    install_dir = tmp_path / "ProjectZomboid"
    install_dir.mkdir()
    (install_dir / "zomboid.sh").write_text(
        "#!/bin/sh\n", encoding="utf-8"
    )
    save_dir = isolated_linux_home["home"] / "Zomboid" / "Saves"
    save_dir.mkdir(parents=True)
    (save_dir / "slot1.bin").write_bytes(b"save")
    monkeypatch.setattr(
        linux_finder.config, "LINUX_SKIP_HOME_FALLBACK", False
    )

    results = linux_finder.guess_save_path(
        "ProjectZomboid",
        game_install_dir=str(install_dir),
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(save_dir))


def test_hidden_home_publisher_is_searched_without_crawling_home(
    isolated_linux_home, monkeypatch
):
    save_dir = (
        isolated_linux_home["home"]
        / ".klei"
        / "DoNotStarveTogether"
        / "SaveGames"
    )
    save_dir.mkdir(parents=True)
    (save_dir / "save01.sav").write_bytes(b"save")
    monkeypatch.setattr(
        linux_finder.config, "LINUX_SKIP_HOME_FALLBACK", False
    )

    results = linux_finder.guess_save_path(
        "Don't Starve Together",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(save_dir))


def test_unknown_xdg_publisher_with_matching_child_beats_scan_cap(
    isolated_linux_home
):
    xdg_data = isolated_linux_home["xdg_data"]
    for index in range(80):
        (xdg_data / f"AA Decoy Publisher {index:03d}").mkdir()
    save_dir = (
        xdg_data
        / "ZZ Grinding Gear Games"
        / "Path of Exile"
        / "SaveGames"
    )
    save_dir.mkdir(parents=True)
    (save_dir / "save01.sav").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "PathOfExile",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(save_dir))


@pytest.mark.parametrize(
    ("game_name", "disk_name"),
    [
        ("Witcher3", "The Witcher 3"),
        ("BindingOfIsaac", "Binding of Isaac Afterbirth"),
    ],
)
def test_common_on_disk_title_variants_are_matched(
    isolated_linux_home, game_name, disk_name
):
    save_dir = isolated_linux_home["xdg_data"] / disk_name / "SaveGames"
    save_dir.mkdir(parents=True)
    (save_dir / "save01.sav").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        game_name,
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(save_dir))


def test_matching_folder_is_prioritised_beyond_directory_scan_cap(
    isolated_linux_home
):
    xdg_data = isolated_linux_home["xdg_data"]
    for index in range(80):
        (xdg_data / f"decoy-{index:03d}").mkdir()
    target = xdg_data / "NineSols"
    target.mkdir()
    (target / "save01.sav").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Nine Sols",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(target))


@pytest.mark.parametrize(
    ("requested_game", "other_game_folder"),
    [
        ("DOOM", "DOOMEternal"),
        ("The Forest", "SonsOfTheForest"),
    ],
)
def test_real_other_game_folder_is_not_returned(
    isolated_linux_home, requested_game, other_game_folder
):
    other_path = isolated_linux_home["xdg_data"] / other_game_folder
    other_path.mkdir()
    (other_path / "save01.sav").write_bytes(b"other game")

    results = linux_finder.guess_save_path(
        requested_game,
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results == []


def test_username_matching_game_does_not_contaminate_xdg_context(
    isolated_linux_home, tmp_path, monkeypatch
):
    game_named_home = tmp_path / "Celeste"
    unrelated_save = (
        game_named_home
        / ".config"
        / "TotallyUnrelatedApp"
        / "Saves"
    )
    unrelated_save.mkdir(parents=True)
    (unrelated_save / "slot1.sav").write_bytes(b"not celeste")

    def expand_game_named_home(path):
        if path == "~":
            return str(game_named_home)
        if isinstance(path, str) and path.startswith("~/"):
            return str(game_named_home / Path(path[2:]))
        return path

    monkeypatch.setattr(
        linux_finder.os.path, "expanduser", expand_game_named_home
    )
    monkeypatch.setenv(
        "XDG_CONFIG_HOME", str(game_named_home / ".config")
    )
    monkeypatch.setattr(
        linux_finder.config,
        "LINUX_KNOWN_SAVE_LOCATIONS",
        ["~/.config", "~"],
    )

    results = linux_finder.guess_save_path(
        "Celeste",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results == []


def test_flatpak_returns_confirmed_save_leaf_not_containers(
    isolated_linux_home
):
    save_leaf = (
        isolated_linux_home["home"]
        / ".var"
        / "app"
        / "com.example.Celeste"
        / "data"
        / "Celeste"
        / "Saves"
    )
    save_leaf.mkdir(parents=True)
    (save_leaf / "slot1.sav").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Celeste",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(save_leaf))
    assert results[0][2] is True
    assert all(
        os.path.basename(path).casefold() not in {"app", "data"}
        for path, _, _ in results
    )


def test_flatpak_matching_package_is_prioritised_beyond_scan_cap(
    isolated_linux_home
):
    flatpak_root = (
        isolated_linux_home["home"] / ".var" / "app"
    )
    flatpak_root.mkdir(parents=True)
    for index in range(80):
        (flatpak_root / f"aa.example.Decoy{index:03d}").mkdir()

    save_leaf = (
        flatpak_root
        / "zz.publisher.Celeste"
        / "data"
        / "Celeste"
        / "Saves"
    )
    save_leaf.mkdir(parents=True)
    (save_leaf / "slot1.sav").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Celeste",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(save_leaf))
    assert not any(
        path == os.path.normpath(str(flatpak_root / "zz.publisher.Celeste"))
        for path, _, _ in results
    )


def test_native_snap_common_directory_is_supported(
    isolated_linux_home, monkeypatch
):
    snap_common = (
        isolated_linux_home["home"] / "snap" / "celeste" / "common"
    )
    snap_common.mkdir(parents=True)
    (snap_common / "save01.sav").write_bytes(b"save")
    monkeypatch.setattr(linux_finder.config, "LINUX_ENABLE_SNAP_SEARCH", True)

    results = linux_finder.guess_save_path(
        "Celeste",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(snap_common))
    assert results[0][2] is True


def test_steam_userdata_prefers_nonempty_remote_over_base(
    isolated_linux_home
):
    userdata = (
        isolated_linux_home["home"]
        / ".local"
        / "share"
        / "Steam"
        / "userdata"
    )
    app_base = userdata / "42" / "570"
    remote = app_base / "remote"
    remote.mkdir(parents=True)
    (app_base / "remotecache.vdf").write_text("metadata", encoding="utf-8")
    (remote / "save.dat").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Dota 2",
        game_install_dir=None,
        appid=570,
        steam_userdata_path=str(userdata),
        steam_id3_to_use=42,
        is_steam_game=True,
    )

    assert results
    assert results[0][0] == os.path.normpath(str(remote))
    assert not any(path == os.path.normpath(str(app_base)) for path, _, _ in results)


def test_steam_userdata_is_discovered_from_appid_alone(
    isolated_linux_home
):
    remote = (
        isolated_linux_home["home"]
        / ".local"
        / "share"
        / "Steam"
        / "userdata"
        / "42"
        / "570"
        / "remote"
    )
    remote.mkdir(parents=True)
    (remote / "save.dat").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Dota 2",
        game_install_dir=None,
        appid=570,
        is_steam_game=True,
    )

    assert results[0][0] == os.path.normpath(str(remote))


def test_steam_userdata_is_discovered_under_custom_xdg_data_home(
    isolated_linux_home
):
    remote = (
        isolated_linux_home["xdg_data"]
        / "Steam"
        / "userdata"
        / "42"
        / "570"
        / "remote"
    )
    remote.mkdir(parents=True)
    (remote / "save.dat").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Dota 2",
        game_install_dir=None,
        appid=570,
        is_steam_game=True,
    )

    assert results[0][0] == os.path.normpath(str(remote))


@pytest.mark.parametrize(
    ("game_name", "folder_name", "expected"),
    [
        ("DOOM", "DOOM 2", False),
        ("Dark Souls II", "Dark Souls III", False),
        (
            "Dark Souls II: Scholar of the First Sin",
            "DarkSoulsII",
            True,
        ),
        ("Nine Sols", "NineSols", True),
        ("Call of Duty Black Ops", "Call of Duty Modern Warfare", False),
        ("Football Manager 2024", "Football Manager 2023", False),
        ("DOOM", "DOOM Eternal", False),
        ("Resident Evil", "Resident Evil Village", False),
        ("Portal", "Portal Stories Mel", False),
        ("The Forest", "Sons of the Forest", False),
        ("Subnautica", "Subnautica Below Zero", False),
        ("Half-Life", "Half-Life Alyx", False),
        ("Final Fantasy XIV", "FFXIV", True),
        ("Final Fantasy XIV", "FF14", True),
        ("Final Fantasy 14", "FFXIV", True),
        ("Dark Souls II", "DSII", True),
        ("Dark Souls II", "DS2", True),
        (
            "The Binding of Isaac Rebirth",
            "Binding of Isaac Repentance",
            False,
        ),
        ("Resident Evil Biohazard", "Resident Evil Village", False),
        ("Batman Arkham Asylum", "Batman Arkham City", False),
        (
            "Middle Earth Shadow of Mordor",
            "Middle Earth Shadow of War",
            False,
        ),
        ("Control Ultimate Edition", "Control", True),
        ("Control", "Control Ultimate Edition", False),
        (
            "Death Stranding Director’s Cut",
            "Death Stranding",
            True,
        ),
        (
            "Ghost of Tsushima Director's Cut",
            "Ghost of Tsushima",
            True,
        ),
    ],
)
def test_title_matching_guards_versions(game_name, folder_name, expected):
    assert (
        linux_finder.are_names_similar(
            game_name,
            folder_name,
            fuzz_engine=linux_finder._fuzz_module,
            thefuzz_available=linux_finder._THEFUZZ_AVAILABLE,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("game_name", "folder_name"),
    [
        ("Pokémon Uranium", "PokémonUranium"),
        ("大逆転裁判", "大逆転裁判"),
    ],
)
def test_unicode_title_components_are_preserved(game_name, folder_name):
    state = linux_finder._build_search_state(game_name, None)
    assert linux_finder._component_matches_game(folder_name, state)


def test_immediate_cancellation_returns_empty(isolated_linux_home):
    class Cancelled:
        @staticmethod
        def check_cancelled():
            return True

    assert (
        linux_finder.guess_save_path(
            "Hollow Knight",
            game_install_dir=None,
            cancellation_manager=Cancelled(),
        )
        == []
    )


def test_parallel_searches_do_not_share_candidate_state(isolated_linux_home):
    xdg_data = isolated_linux_home["xdg_data"]
    expected = {}
    for game_name in ("Alpha Game", "Beta Game", "Gamma Game"):
        game_dir = xdg_data / game_name.replace(" ", "")
        game_dir.mkdir()
        (game_dir / "save01.sav").write_bytes(b"save")
        expected[game_name] = os.path.normpath(str(game_dir))

    names = list(expected) * 4
    with ThreadPoolExecutor(max_workers=6) as executor:
        result_lists = list(
            executor.map(
                lambda name: linux_finder.guess_save_path(
                    name,
                    game_install_dir=None,
                    is_steam_game=False,
                ),
                names,
            )
        )

    for game_name, results in zip(names, result_lists):
        assert results[0][0] == expected[game_name]


def test_search_budget_does_not_poison_an_unvisited_root(
    tmp_path, monkeypatch
):
    target = tmp_path / "Celeste"
    target.mkdir()
    (target / "slot1.sav").write_bytes(b"save")
    state = linux_finder._build_search_state(
        "Celeste", None, is_steam_game=False
    )
    monkeypatch.setattr(
        linux_finder.config,
        "LINUX_MAX_DIRECTORIES_TO_EXPLORE",
        1,
    )

    state.directories_explored = 1
    linux_finder._search_recursive(str(target), 0, state)
    assert linux_finder._path_key(str(target)) not in state.explored_paths

    state.directories_explored = 0
    linux_finder._search_recursive(str(target), 0, state)
    assert os.path.normpath(str(target)) in state.guesses_data


@pytest.mark.parametrize("save_filename", ["zzz_slot.sav", "state.db"])
def test_proton_evidence_is_not_hidden_by_early_log_files(
    isolated_linux_home, tmp_path, save_filename
):
    library = tmp_path / "SteamLibrary"
    install_dir = library / "steamapps" / "common" / "Requested Game"
    opaque_project = (
        library
        / "steamapps"
        / "compatdata"
        / "12345"
        / "pfx"
        / "drive_c"
        / "users"
        / "steamuser"
        / "AppData"
        / "Local"
        / "OpaqueProject"
    )
    install_dir.mkdir(parents=True)
    opaque_project.mkdir(parents=True)
    for index in range(30):
        (opaque_project / f"aaa-{index:02d}.log").write_text(
            "log", encoding="utf-8"
        )
    (opaque_project / save_filename).write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Requested Game",
        game_install_dir=str(install_dir),
        appid=12345,
        is_steam_game=True,
    )

    assert results[0][0] == os.path.normpath(str(opaque_project))
    assert results[0][2] is True


def test_native_rimworld_unity_layout(isolated_linux_home):
    save_dir = (
        isolated_linux_home["xdg_config"]
        / "unity3d"
        / "Ludeon Studios"
        / "RimWorld by Ludeon Studios"
        / "Saves"
    )
    save_dir.mkdir(parents=True)
    (save_dir / "Colony.rws").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "RimWorld",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(save_dir))
    assert results[0][2] is True


def test_proton_programdata_layout(isolated_linux_home, tmp_path):
    library = tmp_path / "SteamLibrary"
    install_dir = library / "steamapps" / "common" / "Example Game"
    save_dir = (
        library
        / "steamapps"
        / "compatdata"
        / "12345"
        / "pfx"
        / "drive_c"
        / "ProgramData"
        / "Example Game"
        / "Saves"
    )
    install_dir.mkdir(parents=True)
    save_dir.mkdir(parents=True)
    (save_dir / "slot1.sav").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Example Game",
        game_install_dir=str(install_dir),
        appid=12345,
        is_steam_game=True,
    )

    assert results[0][0] == os.path.normpath(str(save_dir))


def test_dedicated_nonsteam_wine_prefix_supports_internal_project(
    isolated_linux_home, tmp_path, monkeypatch
):
    monkeypatch.setattr(
        linux_finder.config,
        "LINUX_ENABLE_PROTON_SCAN_NONSTEAM",
        True,
    )
    prefix = tmp_path / "Requested Game"
    install_dir = (
        prefix / "drive_c" / "Program Files" / "Requested Game"
    )
    save_dir = (
        prefix
        / "drive_c"
        / "users"
        / "player"
        / "AppData"
        / "Local"
        / "InternalProject"
        / "Saved"
        / "SaveGames"
    )
    install_dir.mkdir(parents=True)
    save_dir.mkdir(parents=True)
    (save_dir / "Player.sav").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Requested Game",
        game_install_dir=str(install_dir),
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(save_dir))


def test_shared_default_wine_prefix_does_not_claim_another_game(
    isolated_linux_home, monkeypatch
):
    monkeypatch.setattr(
        linux_finder.config,
        "LINUX_ENABLE_PROTON_SCAN_NONSTEAM",
        True,
    )
    prefix = isolated_linux_home["home"] / ".wine"
    install_dir = (
        prefix / "drive_c" / "Program Files" / "Requested Game"
    )
    other_save = (
        prefix
        / "drive_c"
        / "users"
        / "player"
        / "AppData"
        / "Local"
        / "OtherGame"
        / "Saved"
        / "SaveGames"
    )
    install_dir.mkdir(parents=True)
    other_save.mkdir(parents=True)
    (other_save / "other.sav").write_bytes(b"other")

    results = linux_finder.guess_save_path(
        "Requested Game",
        game_install_dir=str(install_dir),
        is_steam_game=False,
    )

    assert not any(
        _canonical(path) == _canonical(str(other_save))
        for path, _, _ in results
    )


def test_heroic_title_matched_sibling_prefix(
    isolated_linux_home, monkeypatch
):
    monkeypatch.setattr(
        linux_finder.config,
        "LINUX_ENABLE_PROTON_SCAN_NONSTEAM",
        True,
    )
    heroic_root = isolated_linux_home["home"] / "Games" / "Heroic"
    install_dir = heroic_root / "TheWitness"
    save_dir = (
        heroic_root
        / "Prefixes"
        / "default"
        / "The Witness"
        / "pfx"
        / "drive_c"
        / "users"
        / "player"
        / "AppData"
        / "Local"
        / "InternalProject"
        / "Saved"
        / "SaveGames"
    )
    install_dir.mkdir(parents=True)
    save_dir.mkdir(parents=True)
    (save_dir / "Player.sav").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "The Witness",
        game_install_dir=str(install_dir),
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(save_dir))


def test_renpy_numeric_save_directory(
    isolated_linux_home, monkeypatch
):
    save_dir = (
        isolated_linux_home["home"]
        / ".renpy"
        / "DDLC-1454445547"
    )
    save_dir.mkdir(parents=True)
    (save_dir / "1-1-LT1.save").write_bytes(b"save")
    monkeypatch.setattr(
        linux_finder.config,
        "LINUX_KNOWN_SAVE_LOCATIONS",
        ["~/.renpy"],
    )

    results = linux_finder.guess_save_path(
        "Doki Doki Literature Club!",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(save_dir))


def test_flatpak_package_context_does_not_require_inner_title(
    isolated_linux_home
):
    save_dir = (
        isolated_linux_home["home"]
        / ".var"
        / "app"
        / "com.publisher.Celeste"
        / "data"
        / "Saves"
    )
    save_dir.mkdir(parents=True)
    (save_dir / "slot1.sav").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Celeste",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(save_dir))


def test_user_snap_and_var_home_are_not_install_trees(
    isolated_linux_home, tmp_path, monkeypatch
):
    snap_save = (
        isolated_linux_home["home"] / "snap" / "celeste" / "common"
    )
    assert not linux_finder._identify_path_type(
        str(snap_save), "Snap"
    )["is_install_dir_walk"]

    fedora_home = tmp_path / "var" / "home" / "deck"
    fedora_config = fedora_home / ".config"

    def expand_fedora_home(path):
        if path == "~":
            return str(fedora_home)
        return path

    monkeypatch.setattr(
        linux_finder.os.path, "expanduser", expand_fedora_home
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fedora_config))
    assert not linux_finder._identify_path_type(
        str(fedora_config / "Celeste"),
        "XDG Config",
    )["is_install_dir_walk"]


def test_userdata_auto_and_explicit_scores_are_identical(
    isolated_linux_home
):
    userdata = (
        isolated_linux_home["home"]
        / ".local"
        / "share"
        / "Steam"
        / "userdata"
    )
    remote = userdata / "42" / "570" / "remote"
    remote.mkdir(parents=True)
    (remote / "save.dat").write_bytes(b"save")

    auto_results = linux_finder.guess_save_path(
        "Dota 2",
        appid=570,
        is_steam_game=True,
    )
    explicit_results = linux_finder.guess_save_path(
        "Dota 2",
        appid=570,
        steam_userdata_path=str(userdata),
        steam_id3_to_use=42,
        is_steam_game=True,
    )

    assert auto_results == explicit_results
    assert auto_results[0][1] <= 1100


def test_nested_userdata_remote_returns_one_capped_leaf(
    isolated_linux_home
):
    userdata = (
        isolated_linux_home["home"]
        / ".local"
        / "share"
        / "Steam"
        / "userdata"
    )
    save_dir = userdata / "42" / "570" / "remote" / "Dota2" / "Saves"
    save_dir.mkdir(parents=True)
    (save_dir / "slot1.sav").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Dota 2",
        appid=570,
        steam_userdata_path=str(userdata),
        steam_id3_to_use=42,
        is_steam_game=True,
    )

    assert results == [
        (os.path.normpath(str(save_dir)), results[0][1], True)
    ]
    assert results[0][1] <= 1100


def test_explicit_userdata_account_does_not_include_other_accounts(
    isolated_linux_home
):
    userdata = (
        isolated_linux_home["home"]
        / ".local"
        / "share"
        / "Steam"
        / "userdata"
    )
    for user_id in ("42", "99"):
        remote = userdata / user_id / "570" / "remote"
        remote.mkdir(parents=True)
        (remote / "save.dat").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Dota 2",
        appid=570,
        steam_userdata_path=str(userdata),
        steam_id3_to_use=42,
        is_steam_game=True,
    )

    assert results
    assert all(
        os.path.normpath(str(userdata / "42")) in path
        for path, _, _ in results
    )


def test_multiple_save_leaves_collapse_to_common_game_parent(
    isolated_linux_home
):
    game_dir = isolated_linux_home["xdg_data"] / "ExampleGame"
    saves = game_dir / "Saves"
    profiles = game_dir / "Profiles"
    saves.mkdir(parents=True)
    profiles.mkdir()
    (saves / "slot1.sav").write_bytes(b"save")
    (profiles / "profile1.sav").write_bytes(b"profile")

    results = linux_finder.guess_save_path(
        "Example Game",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results == [
        (os.path.normpath(str(game_dir)), results[0][1], True)
    ]


def test_specific_save_folder_ranks_above_generic_config(
    isolated_linux_home
):
    data_root = (
        isolated_linux_home["home"]
        / ".var"
        / "app"
        / "com.publisher.Celeste"
        / "data"
    )
    config_dir = data_root / "Config"
    saves_dir = data_root / "Saves"
    config_dir.mkdir(parents=True)
    saves_dir.mkdir()
    (config_dir / "slot1.sav").write_bytes(b"config")
    (saves_dir / "slot1.sav").write_bytes(b"save")

    results = linux_finder.guess_save_path(
        "Celeste",
        game_install_dir=None,
        is_steam_game=False,
    )

    assert results[0][0] == os.path.normpath(str(saves_dir))


def test_cross_platform_compatibility_wrappers_keep_the_windows_contract(
    tmp_path
):
    path = tmp_path / "Celeste"
    path.mkdir()
    assert linux_finder.are_names_similar(
        "Celeste",
        "Celeste",
        game_title_words_for_seq=["Celeste"],
    )
    sort_key = linux_finder.final_sort_key(
        (str(path), "Compatibility", True),
        {"game_name": "Celeste"},
    )
    assert len(sort_key) == 2


def test_steam_libraries_reads_legacy_vdf_shape(tmp_path, monkeypatch):
    steam_root = tmp_path / "Steam"
    external_library = tmp_path / "legacy-library"
    (steam_root / "steamapps").mkdir(parents=True)
    (external_library / "steamapps").mkdir(parents=True)
    legacy_vdf = steam_root / "config" / "libraryfolders.vdf"
    legacy_vdf.parent.mkdir()
    legacy_vdf.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        steam_utils,
        "get_steam_install_path",
        lambda: str(steam_root),
    )

    def fake_parse_vdf(path):
        if os.path.normpath(path) == os.path.normpath(str(legacy_vdf)):
            return {
                "LibraryFolders": {
                    "1": str(external_library),
                }
            }
        return None

    monkeypatch.setattr(steam_utils, "_parse_vdf", fake_parse_vdf)
    monkeypatch.setattr(steam_utils, "_steam_libraries", None)

    assert steam_utils.find_steam_libraries() == [
        os.path.normpath(str(steam_root)),
        os.path.normpath(str(external_library)),
    ]


def _canonical(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))
