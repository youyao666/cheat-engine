from __future__ import annotations

import pytest

from cli_anything.cheat_engine.utils.driver_build import DriverBuildError, _last_json_object


def test_last_json_object_ignores_compiler_output():
    payload = _last_json_object(
        '[cl] DBKDrvr.c\nwarning C4996: deprecated\n{"Path":"x.sys","Signed":false}'
    )

    assert payload == {"Path": "x.sys", "Signed": False}


def test_last_json_object_rejects_missing_result():
    with pytest.raises(DriverBuildError, match="did not return a JSON result"):
        _last_json_object("compiler output only")
