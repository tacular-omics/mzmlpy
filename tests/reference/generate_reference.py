"""Generate the frozen reference values used by tests/test_reference_pyteomics.py.

Independent references (not dependencies of mzmlpy):

* pyteomics.mzml reads every bundled file it can decode (it has no zstd, byte-shuffled or
  dictionary codec) and its values are frozen into ``pyteomics_reference.json``.
* psims.mzml.MzMLWriter writes ``psims_written.mzML`` from the arrays and metadata frozen in
  ``psims_reference.json``, so mzmlpy is checked on a file produced by another writer.

Produced with pyteomics 5.0.1, psims 1.4.0, pynumpress 0.1.5 and numpy 2.5.3 on Python 3.13::

    uv run --with pyteomics --with psims --with lxml python tests/reference/generate_reference.py

Array values are stored as a length plus the SHA-256 of the float64 little-endian bytes, so
equality is exact and the fixture stays small. Rerunning should produce no diff.
"""

import gzip
import hashlib
import json
import warnings
from pathlib import Path

import numpy as np
from psims.mzml.writer import MzMLWriter
from pyteomics import mzml

HERE = Path(__file__).parent
DATA = HERE.parent / "data"

PYTEOMICS_FILES = [
    "example.mzML",
    "example.mzML.gz",
    "bruker_ms2_im.mzML",
    "bruker_ms2_im_combined_im.mzML",
    "zlib_20250806_ArgC_DDA_HCD-FT_01.mzML",
    "numpresslinear_20250806_ArgC_DDA_HCD-FT_01.mzML",
    "numpresspic_20250806_ArgC_DDA_HCD-FT_01.mzML",
    "numpressslof_20250806_ArgC_DDA_HCD-FT_01.mzML",
]


def array_ref(values) -> dict:
    arr = np.asarray(values)
    as64 = arr.astype("<f8")
    return {
        "dtype": arr.dtype.str,
        "length": int(arr.size),
        "sha256": hashlib.sha256(as64.tobytes()).hexdigest(),
    }


def seconds(value) -> float:
    unit = getattr(value, "unit_info", None)
    return float(value) * (60.0 if unit == "minute" else 1.0)


def spectrum_ref(spec: dict) -> dict:
    out: dict = {"id": spec["id"], "index": spec["index"], "ms_level": spec.get("ms level")}
    for key in ("m/z array", "intensity array"):
        if key in spec:
            out[key] = array_ref(spec[key])
    scan = spec["scanList"]["scan"][0]
    if "scan start time" in scan:
        out["scan_start_time_s"] = seconds(scan["scan start time"])
    precursors = []
    for p in spec.get("precursorList", {}).get("precursor", []):
        iw = p.get("isolationWindow", {})
        act = p.get("activation", {})
        precursors.append(
            {
                "spectrum_ref": p.get("spectrumRef"),
                "isolation_window": [
                    iw.get("isolation window target m/z"),
                    iw.get("isolation window lower offset"),
                    iw.get("isolation window upper offset"),
                ],
                "collision_energy": act.get("collision energy"),
                "selected_ions": [
                    {
                        "mz": si.get("selected ion m/z"),
                        "charge": si.get("charge state"),
                        "intensity": si.get("peak intensity"),
                    }
                    for si in p.get("selectedIonList", {}).get("selectedIon", [])
                ],
            }
        )
    out["precursors"] = precursors
    # Spectrum-level cvParams as pyteomics flattens them: name -> value (None for valueless terms).
    cv = {}
    for key in (
        "base peak m/z",
        "base peak intensity",
        "total ion current",
        "lowest observed m/z",
        "highest observed m/z",
        "ms level",
    ):
        if key in spec:
            cv[key] = float(spec[key])
    out["cv"] = cv
    out["centroid"] = "centroid spectrum" in spec
    out["profile"] = "profile spectrum" in spec
    return out


def pyteomics_reference() -> dict:
    result = {}
    for name in PYTEOMICS_FILES:
        path = DATA / name
        source = gzip.open(path, "rb") if name.endswith(".gz") else str(path)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            reader = mzml.MzML(source, decode_binary=True)
            spectra = [spectrum_ref(s) for s in reader]
            reader.reset()
            chroms = [
                {
                    "id": c["id"],
                    "time array": array_ref(c["time array"]),
                    "intensity array": array_ref(c["intensity array"]),
                }
                for c in reader.iterfind("chromatogram")
            ]
        result[name] = {"spectra": spectra, "chromatograms": chroms}
    return result


# Arrays chosen to exercise float32/float64, zlib/none and numpress; values are exact in float32.
PSIMS_SPECTRA = [
    {
        "id": "scan=1",
        "compression": "zlib",
        "mz_dtype": "float64",
        "int_dtype": "float32",
        "ms_level": 1,
        "rt_min": 0.5,
        "mz": [100.0, 200.25, 300.5, 1500.125],
        "intensity": [10.0, 2000.5, 3.25, 0.0],
    },
    {
        "id": "scan=2",
        "compression": "none",
        "mz_dtype": "float32",
        "int_dtype": "float64",
        "ms_level": 2,
        "rt_min": 0.75,
        "mz": [150.5, 250.75],
        "intensity": [1.5, 99999.0],
        "precursor": {
            "mz": 445.12,
            "charge": 2,
            "intensity": 12345.0,
            "scan_id": "scan=1",
            "activation": ["beam-type collision-induced dissociation", {"collision energy": 30.0}],
            "isolation_window": [1.0, 445.12, 1.5],
        },
    },
    {
        "id": "scan=3",
        "compression": "zlib",
        "mz_dtype": "float64",
        "int_dtype": "float64",
        "ms_level": 1,
        "rt_min": 1.0,
        "mz": [],
        "intensity": [],
    },
    {
        "id": "scan=4",
        "compression": "MS-Numpress linear prediction compression",
        "mz_dtype": "float64",
        "int_dtype": "float64",
        "ms_level": 1,
        "rt_min": 1.25,
        "mz": [400.0, 400.5, 401.0, 402.25, 900.125],
        "intensity": [5.0, 6.0, 7.0, 8.0, 9.0],
    },
]


def write_psims_file(path: Path) -> None:
    with MzMLWriter(open(path, "wb"), close=True) as w:
        w.controlled_vocabularies()
        w.file_description(["MSn spectrum"])
        w.software_list([{"id": "psims-writer", "version": "1.4.0", "params": ["python-psims"]}])
        w.instrument_configuration_list([w.InstrumentConfiguration(id="IC1", component_list=[])])
        w.data_processing_list(
            [
                w.DataProcessing(
                    [w.ProcessingMethod(order=1, software_reference="psims-writer", params=["Conversion to mzML"])],
                    id="DP1",
                )
            ]
        )
        with w.run(id="psims_run", instrument_configuration="IC1"):
            with w.spectrum_list(count=len(PSIMS_SPECTRA)):
                for s in PSIMS_SPECTRA:
                    w.write_spectrum(
                        np.array(s["mz"], dtype=s["mz_dtype"]),
                        np.array(s["intensity"], dtype=s["int_dtype"]),
                        id=s["id"],
                        centroided=True,
                        scan_start_time=s["rt_min"],
                        compression=s["compression"],
                        encoding={
                            "m/z array": np.dtype(s["mz_dtype"]).type,
                            "intensity array": np.dtype(s["int_dtype"]).type,
                        },
                        params=[{"ms level": s["ms_level"]}],
                        precursor_information=s.get("precursor"),
                    )


def main() -> None:
    (HERE / "pyteomics_reference.json").write_text(json.dumps(pyteomics_reference(), indent=1) + "\n")
    write_psims_file(HERE / "psims_written.mzML")
    (HERE / "psims_reference.json").write_text(json.dumps(PSIMS_SPECTRA, indent=1) + "\n")


if __name__ == "__main__":
    main()
