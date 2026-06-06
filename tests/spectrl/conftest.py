"""Shared fixtures for mzx tests."""

import numpy as np
import pytest

from spectrl.model import (
    InlineSpectrum,
    SpectrlActivation,
    SpectrlCvParam,
    SpectrlIsolationWindow,
    SpectrlPrecursor,
    SpectrlScan,
    SpectrlScanWindow,
    SpectrlSelectedIon,
)


@pytest.fixture
def simple_spectrum() -> InlineSpectrum:
    """A minimal 5-peak spectrum for fast round-trip tests."""
    rng = np.random.default_rng(42)
    mz = np.sort(rng.uniform(100.0, 1000.0, 5))
    intensity = rng.uniform(1000.0, 1e6, 5)
    return InlineSpectrum(
        default_array_length=5,
        mz=mz,
        intensity=intensity,
        id="scan=1",
    )


@pytest.fixture
def ms2_spectrum() -> InlineSpectrum:
    """A realistic MS2 spectrum with scan metadata and a precursor."""
    rng = np.random.default_rng(0)
    n = 84
    mz = np.sort(rng.uniform(100.0, 1700.0, n))
    intensity = rng.uniform(1000.0, 1e7, n)

    return InlineSpectrum(
        default_array_length=n,
        mz=mz,
        intensity=intensity,
        id="scan=12298",
        params=[
            SpectrlCvParam(accession="MS:1000511", value=2),          # ms level
            SpectrlCvParam(accession="MS:1000130"),                    # positive scan (flag)
            SpectrlCvParam(accession="MS:1000127"),                    # centroid (flag)
            SpectrlCvParam(accession="MS:1000285", value=1234567.0),  # TIC
        ],
        scans=[
            SpectrlScan(
                params=[
                    SpectrlCvParam(accession="MS:1000016", value=23.41, unit_accession="UO:0000031"),
                    SpectrlCvParam(accession="MS:1000927", value=50.0),
                ],
                windows=[
                    SpectrlScanWindow(params=[
                        SpectrlCvParam(accession="MS:1000501", value=110.0),
                        SpectrlCvParam(accession="MS:1000500", value=1700.0),
                    ])
                ],
            )
        ],
        precursors=[
            SpectrlPrecursor(
                isolation_window=SpectrlIsolationWindow(params=[
                    SpectrlCvParam(accession="MS:1000827", value=800.41),
                    SpectrlCvParam(accession="MS:1000828", value=1.0),
                    SpectrlCvParam(accession="MS:1000829", value=1.0),
                ]),
                selected_ions=[SpectrlSelectedIon(params=[
                    SpectrlCvParam(accession="MS:1000744", value=800.4123),
                    SpectrlCvParam(accession="MS:1000041", value=2),
                    SpectrlCvParam(accession="MS:1000042", value=4.5e6),
                ])],
                activation=SpectrlActivation(params=[
                    SpectrlCvParam(accession="MS:1000422"),           # HCD flag
                    SpectrlCvParam(accession="MS:1000045", value=27.0),  # CE
                ]),
            )
        ],
        interp="PEPTIDES[MOD:00046]K/2",
    )
