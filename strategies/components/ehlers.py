"""Vectorized port of the Pine ``simwai/ehlers/2`` library.

Every function mirrors the Pine source bar-for-bar. Recursive ``var`` state
(Pine ``var float x = 0`` retains its previous value from bar 0) is carried
through a numpy loop; plain series history lookups (``src[7]`` etc.) propagate
NaN exactly like Pine's series indexing.

The dominant-cycle helpers (``get_median_dc``, ``get_iq_dc``,
``get_hilbert_dc``, ``get_bandpass_dc``, ``get_hd_dc``) return a Series of
integer period lengths. ``get_cyber_cycle`` is a documented approximation of
the template's ``cc.getCyberCycle(src, alpha, cyclePart)`` call, which is not
an exported symbol of this library — it follows the classic Ehlers Cyber Cycle
homodyne discriminator using the provided smoothing ``alpha``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas import Series

_PI = 3.141592653589793
_TWO_PI = 2.0 * _PI


def _nz(value: float, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, float) and np.isnan(value):
        return default
    return value


# ---------------------------------------------------------------------------
# Plain vectorized helpers
# ---------------------------------------------------------------------------
def normalize(src: Series, _min: float = -1.0, _max: float = 1.0) -> Series:
    """Normalize a series to ``[min, max]`` using a running historic min/max.

    The running extrema start from ``src`` (Pine seeds ``1.0`` / ``-1.0`` and
    ``nz(src, historic)``, so the first non-NaN sample defines the initial
    window and never shifts the boundaries out).
    """
    values = src.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    hist_min = 1.0
    hist_max = -1.0
    for i, v in enumerate(values):
        v = _nz(v, hist_min)
        hist_min = min(v, hist_min)
        hist_max = max(v, hist_max)
        span = max(hist_max - hist_min, 1.0)
        out[i] = _min + (_max - _min) * (v - hist_min) / span
    return Series(out, index=src.index)


def fisherize(value: Series) -> Series:
    """Inverse Fisher Transformation: ``(exp(2v)-1)/(exp(2v)+1)``."""
    v = 2.0 * value
    return (np.exp(v) - 1.0) / (np.exp(v) + 1.0)


def get_alpha(length: float) -> Series:
    """Convert a length to an EMA-style smoothing alpha: ``2/(length+1)``."""
    return 2.0 / (length + 1.0)


# ---------------------------------------------------------------------------
# Dominant cycle: median method
# ---------------------------------------------------------------------------
def _rolling_median_tail(values: list[float], length: int) -> float:
    window = [v for v in values[-length:] if np.isfinite(v)]
    if not window:
        return 0.0
    window.sort()
    mid = len(window) // 2
    if len(window) % 2 == 1:
        return window[mid]
    return (window[mid - 1] + window[mid]) / 2.0


def get_median_dc(
    price: Series,
    min_period: int = 1,
    max_period: int = 34,
    alpha: float = 0.07,
    cyc_part: float = 0.5,
) -> Series:
    """Ehlers Median Dominant Cyber Cycle (credits @blackcat1402).

    Returns the rounded, clamped period scaled by ``cyc_part``.
    """
    values = price.to_numpy(dtype=float)
    n = len(values)
    smooth = np.zeros(n)
    cycle = np.zeros(n)
    q1 = np.zeros(n)
    i1 = np.zeros(n)
    delta_phase = np.zeros(n)
    inst_period = np.zeros(n)
    period = np.zeros(n)
    out = np.zeros(n, dtype=int)

    for i in range(n):
        p0 = _nz(values[i])
        p1 = _nz(values[i - 1]) if i >= 1 else 0.0
        p2 = _nz(values[i - 2]) if i >= 2 else 0.0
        p3 = _nz(values[i - 3]) if i >= 3 else 0.0

        smooth[i] = (p0 + 2 * p1 + 2 * p2 + p3) / 6.0

        s1 = smooth[i - 1] if i >= 1 else 0.0
        s2 = smooth[i - 2] if i >= 2 else 0.0
        c1 = cycle[i - 1] if i >= 1 else 0.0
        c2 = cycle[i - 2] if i >= 2 else 0.0
        cycle[i] = (
            (1 - 0.5 * alpha) ** 2 * (smooth[i] - 2 * s1 + s2)
            + 2 * (1 - alpha) * c1
            - (1 - alpha) ** 2 * c2
        )
        if i < 7:
            cycle[i] = (p0 - 2 * p1 + p2) / 4.0

        cycle2 = cycle[i - 2] if i >= 2 else 0.0
        cycle4 = cycle[i - 4] if i >= 4 else 0.0
        cycle6 = cycle[i - 6] if i >= 6 else 0.0
        ip1 = inst_period[i - 1] if i >= 1 else 0.0
        q1[i] = (
            0.0962 * cycle[i]
            + 0.5769 * cycle2
            - 0.5769 * cycle4
            - 0.0962 * cycle6
        ) * (0.5 + 0.08 * ip1)
        i1[i] = cycle[i - 3] if i >= 3 else 0.0

        q1_1 = q1[i - 1] if i >= 1 else 0.0
        i1_1 = i1[i - 1] if i >= 1 else 0.0
        if q1[i] != 0 and q1_1 != 0:
            denom = 1 + i1[i] * i1_1 / (q1[i] * q1_1)
            if denom != 0:
                delta_phase[i] = (i1[i] / q1[i] - i1_1 / q1_1) / denom
            else:
                delta_phase[i] = delta_phase[i - 1] if i >= 1 else 0.0
        else:
            delta_phase[i] = delta_phase[i - 1] if i >= 1 else 0.0
        delta_phase[i] = min(max(delta_phase[i], 0.1), 1.1)

        median_delta = _rolling_median_tail(delta_phase[: i + 1], 5)
        dc = 15.0 if median_delta == 0 else 6.28318 / median_delta + 0.5
        inst_period[i] = 0.33 * dc + 0.67 * ip1
        period[i] = 0.15 * inst_period[i] + 0.85 * (period[i - 1] if i >= 1 else 0.0)

        raw = int(round(period[i] * cyc_part))
        raw = 34 if raw > 34 else raw
        raw = 1 if raw < 1 else raw
        raw = min_period if raw < min_period else raw
        raw = max_period if raw > max_period else raw
        out[i] = raw

    return Series(out, index=price.index)


# ---------------------------------------------------------------------------
# Dominant cycle: inphase-quadrature method
# ---------------------------------------------------------------------------
def get_iq_dc(src: Series, min_period: int = 1, max_period: int = 34) -> Series:
    """Ehlers Inphase-Quadrature dominant cycle (credits @DasanC)."""
    values = src.to_numpy(dtype=float)
    n = len(values)
    p = np.full(n, np.nan)
    inphase = np.zeros(n)
    quadrature = np.zeros(n)
    re = np.zeros(n)
    im = np.zeros(n)
    delta_iq = np.full(n, np.nan)
    inst_iq = np.zeros(n)
    len_iq = np.zeros(n)
    out = np.zeros(n, dtype=int)

    imult = 0.635
    qmult = 0.338

    for i in range(n):
        if i >= 7 and np.isfinite(values[i]) and np.isfinite(values[i - 7]):
            p[i] = values[i] - values[i - 7]

        p4 = p[i - 4] if i >= 4 else np.nan
        p2 = p[i - 2] if i >= 2 else np.nan
        p0 = p[i]
        inphase[i] = (
            1.25 * (_nz(p4) - imult * _nz(p2))
            + imult * (inphase[i - 3] if i >= 3 else 0.0)
        )
        quadrature[i] = (
            _nz(p2) - qmult * _nz(p0) + qmult * (quadrature[i - 2] if i >= 2 else 0.0)
        )

        ip1 = inphase[i - 1] if i >= 1 else 0.0
        qp1 = quadrature[i - 1] if i >= 1 else 0.0
        re[i] = 0.2 * (inphase[i] * ip1 + quadrature[i] * qp1) + 0.8 * (re[i - 1] if i >= 1 else 0.0)
        im[i] = 0.2 * (inphase[i] * qp1 - ip1 * quadrature[i]) + 0.8 * (im[i - 1] if i >= 1 else 0.0)

        if re[i] != 0:
            delta_iq[i] = np.arctan(im[i] / re[i])

        v = 0.0
        inst_iq[i] = inst_iq[i - 1] if i >= 1 else 0.0
        for j in range(max_period + 1):
            if i - j < 0 or np.isnan(delta_iq[i - j]):
                continue
            v += delta_iq[i - j]
            if v > _TWO_PI and inst_iq[i] == 0.0:
                inst_iq[i] = float(j)
                break
        if inst_iq[i] == 0.0:
            inst_iq[i] = inst_iq[i - 1] if i >= 1 else 0.0

        len_iq[i] = 0.25 * inst_iq[i] + 0.75 * (len_iq[i - 1] if i >= 1 else 1.0)
        length = len_iq[i] if len_iq[i] >= min_period else min_period
        out[i] = int(round(length))

    return Series(out, index=src.index)


# ---------------------------------------------------------------------------
# Dominant cycle: Hilbert transform method
# ---------------------------------------------------------------------------
def get_hilbert_dc(src: Series, min_period: int = 1, max_period: int = 34) -> Series:
    """Ehlers Hilbert-transform dominant cycle (credits @DasanC)."""
    values = src.to_numpy(dtype=float)
    n = len(values)
    in_phase = np.zeros(n)
    quadrature = np.zeros(n)
    phase = np.zeros(n)
    delta_phase = np.zeros(n)
    inst_period = np.zeros(n)
    period = np.zeros(n)
    out = np.zeros(n, dtype=int)

    imult = 0.635
    qmult = 0.338

    for i in range(n):
        if i > 5:
            v0 = _nz(values[i])
            v7 = _nz(values[i - 7]) if i >= 7 else 0.0
            value3 = v0 - v7
            v3_4 = (
                values[i - 7 - 4] if i >= 11 else np.nan
            )
            v3_2 = (
                values[i - 7 - 2] if i >= 9 else np.nan
            )
            in_phase[i] = (
                1.25 * (_nz(v3_4) - imult * _nz(v3_2))
                + imult * (in_phase[i - 3] if i >= 3 else 0.0)
            )
            quadrature[i] = (
                _nz(v3_2) - qmult * value3 + qmult * (quadrature[i - 2] if i >= 2 else 0.0)
            )

            ip0 = in_phase[i]
            ip1 = in_phase[i - 1] if i >= 1 else 0.0
            q0 = quadrature[i]
            q1 = quadrature[i - 1] if i >= 1 else 0.0
            if abs(ip0 + ip1) > 0:
                phase[i] = 180.0 / _PI * np.arctan(abs((q0 + q1) / (ip0 + ip1)))
                if ip0 < 0 and q0 > 0:
                    phase[i] = 180.0 - phase[i]
                elif ip0 < 0 and q0 < 0:
                    phase[i] = 180.0 + phase[i]
                elif ip0 > 0 and q0 < 0:
                    phase[i] = 360.0 - phase[i]

            phase1 = phase[i - 1] if i >= 1 else 0.0
            delta_phase[i] = phase1 - phase[i]
            if phase1 < 90 and phase[i] > 270:
                delta_phase[i] = 360.0 + phase1 - phase[i]
            delta_phase[i] = min(max(delta_phase[i], 1.0), 60.0)

            value4 = 0.0
            inst_period[i] = inst_period[i - 1] if i >= 1 else 0.0
            for j in range(51):
                if i - j < 0:
                    continue
                value4 += delta_phase[i - j]
                if value4 > 360 and inst_period[i] == 0:
                    inst_period[i] = float(j)
                    break

            period[i] = 0.25 * inst_period[i] + 0.75 * (period[i - 1] if i >= 1 else 0.0)
            period[i] = min_period if period[i] < min_period else period[i]
            period[i] = max_period if period[i] > max_period else period[i]
            out[i] = int(round(period[i]))
        else:
            out[i] = min_period

    return Series(out, index=src.index)


# ---------------------------------------------------------------------------
# Dominant cycle: multiple bandpass method
# ---------------------------------------------------------------------------
def get_bandpass_dc(
    price: Series, min_period: int = 1, max_period: int = 34, cyc_part: float = 0.5
) -> Series:
    """Ehlers bandpass dominant cycle (credits @blackcat1402)."""
    values = price.to_numpy(dtype=float)
    n = len(values)
    hp = np.zeros(n)
    smooth_hp = np.zeros(n)
    out = np.zeros(n, dtype=int)

    ehlers_i = np.zeros((n, 52))
    q = np.zeros((n, 52))
    real = np.zeros((n, 52))
    imag = np.zeros((n, 52))
    ampl = np.zeros((n, 52))
    db = np.zeros((n, 52))
    old_i = np.zeros(52)
    older_i = np.zeros(52)
    old_q = np.zeros(52)
    older_q = np.zeros(52)
    old_real = np.zeros(52)
    older_real = np.zeros(52)
    old_imag = np.zeros(52)
    older_imag = np.zeros(52)
    old_ampl = np.zeros(52)

    log10 = np.log(10.0)
    alpha1 = (1 - np.sin(9 / 180 * _PI)) / np.cos(9 / 180 * _PI)
    alpha1_plus1 = alpha1 + 1.0

    for i in range(n):
        p0 = _nz(values[i])
        p1 = _nz(values[i - 1]) if i >= 1 else 0.0

        hp[i] = 0.5 * alpha1_plus1 * (p0 - p1) + alpha1 * (hp[i - 1] if i >= 1 else 0.0)
        smooth_hp[i] = (
            hp[i]
            + 2 * (hp[i - 1] if i >= 1 else 0.0)
            + 3 * (hp[i - 2] if i >= 2 else 0.0)
            + 3 * (hp[i - 3] if i >= 3 else 0.0)
            + 2 * (hp[i - 4] if i >= 4 else 0.0)
            + (hp[i - 5] if i >= 5 else 0.0)
        ) / 12.0
        if i == 1:
            smooth_hp[i] = 0.0
        elif i < 7:
            smooth_hp[i] = p0 - p1

        ehlers_delta = max(-0.015 * i + 0.5, 0.15)

        if i > 6:
            shp0 = smooth_hp[i]
            shp1 = smooth_hp[i - 1] if i >= 1 else 0.0
            for n_idx in range(8, 51):
                beta = np.cos(_TWO_PI / n_idx)
                cos720 = np.cos(4 * _PI * ehlers_delta / n_idx)
                if cos720 != 0:
                    gamma = 1.0 / cos720
                else:
                    gamma = 1.0
                alpha = gamma - np.sqrt(max(gamma**2 - 1.0, 0.0))
                one_minus = 1 - alpha
                one_plus = 1 + alpha
                q[i, n_idx] = n_idx / _TWO_PI * (shp0 - shp1)
                ehlers_i[i, n_idx] = shp0
                real[i, n_idx] = (
                    0.5 * one_minus * (ehlers_i[i, n_idx] - older_i[n_idx])
                    + beta * one_plus * old_real[n_idx]
                    - alpha * older_real[n_idx]
                )
                imag[i, n_idx] = (
                    0.5 * one_minus * (q[i, n_idx] - older_q[n_idx])
                    + beta * one_plus * old_imag[n_idx]
                    - alpha * older_imag[n_idx]
                )
                ampl[i, n_idx] = real[i, n_idx] ** 2 + imag[i, n_idx] ** 2

        for n_idx in range(8, 51):
            older_i[n_idx] = old_i[n_idx]
            old_i[n_idx] = ehlers_i[i, n_idx]
            older_q[n_idx] = old_q[n_idx]
            old_q[n_idx] = q[i, n_idx]
            older_real[n_idx] = old_real[n_idx]
            old_real[n_idx] = real[i, n_idx]
            older_imag[n_idx] = old_imag[n_idx]
            old_imag[n_idx] = imag[i, n_idx]
            old_ampl[n_idx] = ampl[i, n_idx]

        max_ampl = ampl[i, 10] if i > 6 else 0.0
        for n_idx in range(8, 51):
            if ampl[i, n_idx] > max_ampl:
                max_ampl = ampl[i, n_idx]
        for n_idx in range(8, 51):
            if max_ampl != 0 and ampl[i, n_idx] / max_ampl > 0:
                db[i, n_idx] = (
                    -10 * np.log(0.01 / (1 - 0.99 * ampl[i, n_idx] / max_ampl)) / log10
                )
            if db[i, n_idx] > 20:
                db[i, n_idx] = 20

        num = 0.0
        denom = 0.0
        for n_idx in range(10, 51):
            if db[i, n_idx] <= 3:
                num += n_idx * (20 - db[i, n_idx])
                denom += 20 - db[i, n_idx]
            if denom != 0:
                dc = num / denom

        if i > 6:
            dom_cyc = np.median(db[i, 8:51]) if np.any(np.isfinite(db[i, 8:51])) else 0.0
        else:
            dom_cyc = 0.0
        dom_cycle = int(np.ceil(cyc_part * dom_cyc))
        dom_cycle = min_period if dom_cycle < min_period else dom_cycle
        dom_cycle = max_period if dom_cycle > max_period else dom_cycle
        out[i] = dom_cycle if i > 6 else min_period

    return Series(out, index=price.index)


# ---------------------------------------------------------------------------
# Dominant cycle: homodyne discriminator method
# ---------------------------------------------------------------------------
def get_hd_dc(price: Series, min_period: int = 1, max_period: int = 34, cyc_part: float = 0.5) -> Series:
    """Ehlers Homodyne discriminator dominant cycle (credits @blackcat1402)."""
    values = price.to_numpy(dtype=float)
    n = len(values)
    smooth = np.zeros(n)
    detrender = np.zeros(n)
    i1 = np.zeros(n)
    q1 = np.zeros(n)
    ji = np.zeros(n)
    jq = np.zeros(n)
    i2 = np.zeros(n)
    q2 = np.zeros(n)
    re = np.zeros(n)
    im = np.zeros(n)
    period = np.zeros(n)
    smooth_period = np.zeros(n)
    out = np.zeros(n, dtype=int)

    for i in range(n):
        p0 = _nz(values[i])
        p1 = _nz(values[i - 1]) if i >= 1 else 0.0
        p2 = _nz(values[i - 2]) if i >= 2 else 0.0
        p3 = _nz(values[i - 3]) if i >= 3 else 0.0
        if i > 7:
            smooth[i] = (4 * p0 + 3 * p1 + 2 * p2 + p3) / 10.0
        else:
            smooth[i] = smooth[i - 1] if i >= 1 else 0.0

        per1 = period[i - 1] if i >= 1 else 0.0
        s2 = smooth[i - 2] if i >= 2 else 0.0
        s4 = smooth[i - 4] if i >= 4 else 0.0
        s6 = smooth[i - 6] if i >= 6 else 0.0
        if i > 7:
            detrender[i] = (
                0.0962 * smooth[i]
                + 0.5769 * s2
                - 0.5769 * s4
                - 0.0962 * s6
            ) * (0.075 * per1 + 0.54)
        else:
            detrender[i] = detrender[i - 1] if i >= 1 else 0.0

        d2 = detrender[i - 2] if i >= 2 else 0.0
        d4 = detrender[i - 4] if i >= 4 else 0.0
        d6 = detrender[i - 6] if i >= 6 else 0.0
        if i > 7:
            q1[i] = (
                0.0962 * detrender[i]
                + 0.5769 * d2
                - 0.5769 * d4
                - 0.0962 * d6
            ) * (0.075 * per1 + 0.54)
            i1[i] = detrender[i - 3] if i >= 3 else 0.0
        else:
            q1[i] = q1[i - 1] if i >= 1 else 0.0
            i1[i] = i1[i - 1] if i >= 1 else 0.0

        i1_2 = i1[i - 2] if i >= 2 else 0.0
        i1_4 = i1[i - 4] if i >= 4 else 0.0
        i1_6 = i1[i - 6] if i >= 6 else 0.0
        q1_2 = q1[i - 2] if i >= 2 else 0.0
        q1_4 = q1[i - 4] if i >= 4 else 0.0
        q1_6 = q1[i - 6] if i >= 6 else 0.0
        ji[i] = (
            0.0962 * i1[i]
            + 0.5769 * i1_2
            - 0.5769 * i1_4
            - 0.0962 * i1_6
        ) * (0.075 * per1 + 0.54)
        jq[i] = (
            0.0962 * q1[i]
            + 0.5769 * q1_2
            - 0.5769 * q1_4
            - 0.0962 * q1_6
        ) * (0.075 * per1 + 0.54)

        i2[i] = i1[i] - jq[i]
        q2[i] = q1[i] + ji[i]
        i2[i] = 0.2 * i2[i] + 0.8 * (i2[i - 1] if i >= 1 else 0.0)
        q2[i] = 0.2 * q2[i] + 0.8 * (q2[i - 1] if i >= 1 else 0.0)

        i2_1 = i2[i - 1] if i >= 1 else 0.0
        q2_1 = q2[i - 1] if i >= 1 else 0.0
        re[i] = i2[i] * i2_1 + q2[i] * q2_1
        im[i] = i2[i] * q2_1 - q2[i] * i2_1
        re[i] = 0.2 * re[i] + 0.8 * (re[i - 1] if i >= 1 else 0.0)
        im[i] = 0.2 * im[i] + 0.8 * (im[i - 1] if i >= 1 else 0.0)

        if im[i] != 0 and re[i] != 0:
            period[i] = _TWO_PI / np.arctan(im[i] / re[i])
        else:
            period[i] = period[i - 1] if i >= 1 else 0.0
        if period[i] > 1.5 * per1:
            period[i] = 1.5 * per1
        elif period[i] < 0.67 * per1:
            period[i] = 0.67 * per1

        period[i] = min_period if period[i] < min_period else period[i]
        period[i] = max_period if period[i] > max_period else period[i]
        period[i] = 0.2 * period[i] + 0.8 * per1
        smooth_period[i] = 0.33 * period[i] + 0.67 * (smooth_period[i - 1] if i >= 1 else 0.0)

        raw = int(np.ceil(cyc_part * smooth_period[i]))
        raw = 34 if raw > 34 else raw
        raw = 1 if raw < 1 else raw
        raw = min_period if raw < min_period else raw
        raw = max_period if raw > max_period else raw
        out[i] = raw if i > 7 else min_period

    return Series(out, index=price.index)


# ---------------------------------------------------------------------------
# Template's cc.getCyberCycle(src, alpha, cyclePart) approximation
# ---------------------------------------------------------------------------
def get_cyber_cycle(src: Series, alpha: float = 0.07, cycle_part: float = 0.5) -> Series:
    """Dominant Cyber Cycle length used by the Strategy Template.

    ``cc.getCyberCycle`` is not exported by the provided ``simwai/ehlers/2``
    library, so this follows the classic Ehlers Cyber Cycle homodyne
    discriminator (the ``get_median_dc`` skeleton) with the caller-provided
    smoothing ``alpha``. Returns an integer period clamped to ``[1, 34]`` and
    scaled by ``cycle_part``. Only affects adaptive lengths (default off).
    """
    values = src.to_numpy(dtype=float)
    n = len(values)
    smooth = np.zeros(n)
    cycle = np.zeros(n)
    q1 = np.zeros(n)
    i1 = np.zeros(n)
    delta_phase = np.zeros(n)
    inst_period = np.zeros(n)
    period = np.zeros(n)
    out = np.zeros(n, dtype=int)

    for i in range(n):
        p0 = _nz(values[i])
        p1 = _nz(values[i - 1]) if i >= 1 else 0.0
        p2 = _nz(values[i - 2]) if i >= 2 else 0.0
        p3 = _nz(values[i - 3]) if i >= 3 else 0.0
        smooth[i] = (p0 + 2 * p1 + 2 * p2 + p3) / 6.0

        s1 = smooth[i - 1] if i >= 1 else 0.0
        s2 = smooth[i - 2] if i >= 2 else 0.0
        c1 = cycle[i - 1] if i >= 1 else 0.0
        c2 = cycle[i - 2] if i >= 2 else 0.0
        cycle[i] = (
            (1 - 0.5 * alpha) ** 2 * (smooth[i] - 2 * s1 + s2)
            + 2 * (1 - alpha) * c1
            - (1 - alpha) ** 2 * c2
        )
        if i < 7:
            cycle[i] = (p0 - 2 * p1 + p2) / 4.0

        ip1 = inst_period[i - 1] if i >= 1 else 0.0
        q1[i] = (
            0.0962 * cycle[i]
            + 0.5769 * (cycle[i - 2] if i >= 2 else 0.0)
            - 0.5769 * (cycle[i - 4] if i >= 4 else 0.0)
            - 0.0962 * (cycle[i - 6] if i >= 6 else 0.0)
        ) * (0.5 + 0.08 * ip1)
        i1[i] = cycle[i - 3] if i >= 3 else 0.0

        q1_1 = q1[i - 1] if i >= 1 else 0.0
        i1_1 = i1[i - 1] if i >= 1 else 0.0
        if q1[i] != 0 and q1_1 != 0:
            denom = 1 + i1[i] * i1_1 / (q1[i] * q1_1)
            delta_phase[i] = (
                (i1[i] / q1[i] - i1_1 / q1_1) / denom if denom != 0 else 0.0
            )
        else:
            delta_phase[i] = delta_phase[i - 1] if i >= 1 else 0.0
        delta_phase[i] = min(max(delta_phase[i], 0.1), 1.1)

        median_delta = _rolling_median_tail(delta_phase[: i + 1], 5)
        dc = 15.0 if median_delta == 0 else 6.28318 / median_delta + 0.5
        inst_period[i] = 0.33 * dc + 0.67 * ip1
        period[i] = 0.15 * inst_period[i] + 0.85 * (period[i - 1] if i >= 1 else 0.0)

        raw = int(round(period[i] * cycle_part))
        raw = 34 if raw > 34 else raw
        raw = 1 if raw < 1 else raw
        out[i] = raw

    return Series(out, index=src.index)


# ---------------------------------------------------------------------------
# Smoothing helpers
# ---------------------------------------------------------------------------
def do_net(series: Series, net_length: int, lower: int = -1, upper: int = 1) -> Series:
    """Noise Elimination Technology (credits @blackcat1402)."""
    net_length = max(2, int(net_length))
    values = series.to_numpy(dtype=float)
    n = len(values)
    out = np.zeros(n)

    for i in range(n):
        window = [_nz(values[i - k]) for k in range(net_length) if i - k >= 0]
        num = 0
        for c in range(1, len(window) + 1):
            for k in range(1, c):
                num -= np.sign(window[c - 1] - window[k - 1])
        denom = 0.5 * net_length * (net_length - 1)
        net = num / denom if denom else 0.0
        trigger = 0.05 + 0.9 * (out[i - 1] if i >= 1 else 0.0)
        out[i] = trigger
    norm = normalize(Series(out, index=series.index), float(lower), float(upper))
    return norm


def do_hann_window(series: Series, hann_length: float) -> Series:
    """Hann window smoothing (credits @cheatcountry)."""
    length = max(1, int(round(hann_length)))
    values = series.to_numpy(dtype=float)
    n = len(values)
    out = np.full(n, np.nan)
    for i in range(n):
        total = 0.0
        coef = 0.0
        for j in range(1, length + 1):
            if i - (j - 1) < 0:
                continue
            cosine = 1 - np.cos(_TWO_PI * j / (length + 1))
            total += cosine * values[i - (j - 1)]
            coef += cosine
        out[i] = total / coef if coef != 0 else 0.0
    return Series(out, index=series.index)


def do_kalman(src: Series) -> Series:
    """Ehlers-style Kalman filter (credits @M0rty)."""
    values = src.to_numpy(dtype=float)
    n = len(values)
    value1 = np.zeros(n)
    value2 = np.zeros(n)
    value3 = np.zeros(n)
    true_range = np.abs(values - np.roll(values, 1))
    true_range[0] = np.nan

    for i in range(n):
        v0 = _nz(values[i])
        v1 = _nz(values[i - 1]) if i >= 1 else 0.0
        value1[i] = 0.2 * (v0 - v1) + 0.8 * (value1[i - 1] if i >= 1 else 0.0)
        tr_prev = _nz(true_range[i - 1]) if i >= 1 else 0.0
        value2[i] = 0.1 * (tr_prev + 0.8 * (value2[i - 1] if i >= 1 else 0.0))
        lam = abs(value1[i] / value2[i]) if value2[i] != 0 else 0.0
        alpha = (
            (-lam**2 + np.sqrt(lam**4 + 16 * lam**2)) / 8
            if (lam**4 + 16 * lam**2) >= 0
            else 0.0
        )
        value3[i] = alpha * v0 + (1 - alpha) * (value3[i - 1] if i >= 1 else 0.0)

    return Series(value3, index=src.index)
