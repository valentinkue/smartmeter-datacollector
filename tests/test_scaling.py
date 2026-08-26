#
# Copyright (C) 2026 Supercomputing Systems AG
# This file is part of smartmeter-datacollector.
#
# SPDX-License-Identifier: GPL-2.0-only
# See LICENSES/README.md for more information.
#
from configparser import ConfigParser

from smartmeter_datacollector.smartmeter.cosem import Cosem
from smartmeter_datacollector.smartmeter.obis import OBISCode
from smartmeter_datacollector.smartmeter.scaling import ScalingConfig, parse_obis
from smartmeter_datacollector.smartmeter.siemens_td3511 import SiemensParser


def _section(**values):
    parser = ConfigParser()
    parser.read_dict({"reader0": {"type": "lge450", **values}})
    return parser["reader0"]


def test_parse_obis_short_form():
    assert parse_obis("3.7.0") == OBISCode(1, 0, 3, 7, 0)


def test_parse_obis_two_octet_form():
    assert parse_obis("14.7") == OBISCode(1, 0, 14, 7, 0)


def test_parse_obis_full_forms():
    assert parse_obis("1.0.3.7.0") == OBISCode(1, 0, 3, 7, 0)
    assert parse_obis("1.0.3.7.0.255") == OBISCode(1, 0, 3, 7, 0)


def test_parse_obis_invalid():
    for bad in ("", "1", "not.an.obis"):
        try:
            parse_obis(bad)
        except ValueError:
            continue
        assert False, f"expected ValueError for '{bad}'"


def test_empty_config_is_noop():
    scaling = ScalingConfig.from_config(_section())
    assert scaling.is_noop()
    assert scaling.get_factor(OBISCode(1, 0, 1, 7, 0)) == 1.0


def test_global_factor():
    scaling = ScalingConfig.from_config(_section(scale="0.5"))
    assert not scaling.is_noop()
    assert scaling.get_factor(OBISCode(1, 0, 1, 7, 0)) == 0.5
    assert scaling.get_factor(OBISCode(1, 0, 3, 7, 0)) == 0.5


def test_per_obis_overrides_global():
    section = _section(**{"scale": "0.5", "scale.1.0.3.7.0": "2.0"})
    scaling = ScalingConfig.from_config(section)
    # per-OBIS wins for its register ...
    assert scaling.get_factor(OBISCode(1, 0, 3, 7, 0)) == 2.0
    # ... global applies to the rest
    assert scaling.get_factor(OBISCode(1, 0, 1, 7, 0)) == 0.5


def test_per_obis_short_form_key():
    scaling = ScalingConfig.from_config(_section(**{"scale.3.7.0": "3.0"}))
    assert scaling.get_factor(OBISCode(1, 0, 3, 7, 0)) == 3.0


def test_invalid_factor_is_skipped():
    scaling = ScalingConfig.from_config(_section(scale="not-a-number"))
    assert scaling.is_noop()


def test_invalid_obis_key_is_skipped():
    scaling = ScalingConfig.from_config(_section(**{"scale.bogus": "2.0"}))
    assert scaling.per_obis == {}


def test_cosem_applies_global_factor_on_top_of_builtin():
    # Active power has a built-in scaling of 1.0, current L1 of 0.01.
    scaling = ScalingConfig.from_config(_section(scale="2.0"))
    cosem = Cosem(fallback_id="id", scaling=scaling)

    active_power = cosem.get_register(OBISCode(1, 0, 1, 7, 0))
    assert active_power.scaling == 2.0

    current_l1 = cosem.get_register(OBISCode(1, 0, 31, 7, 0))
    assert current_l1.scaling == 0.01 * 2.0


def test_cosem_per_obis_multiplies_builtin():
    scaling = ScalingConfig.from_config(_section(**{"scale.1.0.31.7.0": "10"}))
    cosem = Cosem(fallback_id="id", scaling=scaling)

    current_l1 = cosem.get_register(OBISCode(1, 0, 31, 7, 0))
    assert current_l1.scaling == 0.01 * 10
    # untouched register keeps its built-in scaling
    active_power = cosem.get_register(OBISCode(1, 0, 1, 7, 0))
    assert active_power.scaling == 1.0


def test_cosem_without_scaling_keeps_builtin():
    cosem = Cosem(fallback_id="id")
    assert cosem.get_register(OBISCode(1, 0, 31, 7, 0)).scaling == 0.01


def test_cosem_does_not_mutate_shared_default_map():
    scaling = ScalingConfig.from_config(_section(scale="5"))
    Cosem(fallback_id="id", scaling=scaling)
    # A fresh, unscaled Cosem must still see the original built-in scaling.
    fresh = Cosem(fallback_id="id2")
    assert fresh.get_register(OBISCode(1, 0, 31, 7, 0)).scaling == 0.01


def test_siemens_parser_applies_scaling():
    scaling = ScalingConfig.from_config(_section(scale="2.0"))
    parser = SiemensParser(scaling=scaling)
    # Active power "1.7.0" has a built-in scaling of 1000.
    assert parser._register_obis["1.7.0"].scaling == 1000 * 2.0
