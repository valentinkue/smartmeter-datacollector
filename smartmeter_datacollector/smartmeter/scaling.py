#
# Copyright (C) 2026 Supercomputing Systems AG
# This file is part of smartmeter-datacollector.
#
# SPDX-License-Identifier: GPL-2.0-only
# See LICENSES/README.md for more information.
#
"""User-configurable scaling of meter readings.

A ``ScalingConfig`` describes additional scaling factors that are applied
*on top* of the built-in register scaling of a meter. It supports:

* a single global factor applied to every reading of a meter, and
* per-OBIS factors that override the global factor for a specific register.

Both are multiplicative: the value emitted for a register is

    raw_value * builtin_scaling * scaling_factor(obis)

so leaving the configuration empty keeps the previous behaviour unchanged.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional

from smartmeter_datacollector.smartmeter.obis import OBISCode

LOGGER = logging.getLogger("smartmeter")

# Config key for the global per-meter factor.
GLOBAL_KEY = "scale"
# Prefix for per-OBIS factors, e.g. ``scale.1.0.3.7.0`` or ``scale.3.7.0``.
PER_OBIS_PREFIX = "scale."


def parse_obis(obis_string: str) -> OBISCode:
    """Parse an OBIS code from a config string.

    Accepts the short form ``c.d.e`` (3 groups), the two-octet form ``c.d``
    (as used by some meters, ``e`` defaults to 0), the five-octet form
    ``a.b.c.d.e`` and the full ``a.b.c.d.e.f``. Any non-word character may be
    used as a separator. ``OBISCode`` equality only considers ``c``, ``d`` and
    ``e``, so the surrounding octets are only relevant for readability.
    """
    groups = [int(g) for g in re.split(r"\W+", obis_string.strip()) if g != ""]
    if len(groups) == 2:
        return OBISCode(a=1, b=0, c=groups[0], d=groups[1], e=0)
    if len(groups) == 3:
        return OBISCode(a=1, b=0, c=groups[0], d=groups[1], e=groups[2])
    if len(groups) == 5:
        return OBISCode(*groups)
    if len(groups) == 6:
        return OBISCode(*groups)
    raise ValueError(f"Invalid OBIS string '{obis_string}'.")


@dataclass
class ScalingConfig:
    """Additional, user-defined scaling for a single meter."""
    factor: float = 1.0
    per_obis: Dict[OBISCode, float] = field(default_factory=dict)

    def get_factor(self, obis: OBISCode) -> float:
        """Return the extra factor for ``obis``.

        A per-OBIS factor takes precedence over the global factor for that
        register; otherwise the global factor is returned.
        """
        return self.per_obis.get(obis, self.factor)

    def is_noop(self) -> bool:
        """True if this config would not change any reading."""
        return self.factor == 1.0 and not self.per_obis

    @classmethod
    def from_config(cls, section: Mapping[str, str]) -> "ScalingConfig":
        """Build a ``ScalingConfig`` from a reader config section.

        Recognised keys:

        * ``scale``          -- global factor for every register of the meter.
        * ``scale.<obis>``   -- factor for a single OBIS code, overriding the
                                global factor for that register.

        Invalid values are logged and skipped so a typo never crashes the
        collector.
        """
        config = cls()
        for key, raw_value in section.items():
            key = key.strip().lower()
            if key == GLOBAL_KEY:
                factor = _parse_factor(key, raw_value)
                if factor is not None:
                    config.factor = factor
            elif key.startswith(PER_OBIS_PREFIX):
                obis_part = key[len(PER_OBIS_PREFIX):]
                factor = _parse_factor(key, raw_value)
                if factor is None:
                    continue
                try:
                    obis = parse_obis(obis_part)
                except ValueError:
                    LOGGER.warning("Ignoring scaling for invalid OBIS '%s'.", obis_part)
                    continue
                config.per_obis[obis] = factor
        return config


def _parse_factor(key: str, raw_value: str) -> Optional[float]:
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        LOGGER.warning("Ignoring invalid scaling factor '%s' for '%s'.", raw_value, key)
        return None
