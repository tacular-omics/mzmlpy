"""Quick size comparison: mzML XML vs mzx (lossy) vs mzx (lossless) vs single-msgpack+b64."""
import xml.etree.ElementTree as ET
import zlib

import msgpack
import numpy as np

from mzmlpy.run import Mzml
from spectrl import encode_spectrum, from_mzmlpy
from spectrl.token import b64url_encode

results = []

with Mzml("tests/data/example.mzML") as m:
    for spec in m.spectra:
        mz = spec.mz
        intensity = spec.intensity
        if mz is None or len(mz) == 0:
            continue

        n = len(mz)

        # 1. Raw mzML XML for this spectrum element
        xml_bytes = ET.tostring(spec.element, encoding="unicode").encode("utf-8")

        # 2. mzx token — lossy (numpress+zlib) and lossless (raw+zlib)
        inline = from_mzmlpy(spec)
        token_lossy = encode_spectrum(inline)
        token_lossless = encode_spectrum(inline, lossless=True)

        # 3. Minimal single-msgpack variant: arrays as raw zlib-compressed bin fields,
        #    wrapped in a single base64url string (no separate segments, no metadata header).
        #    This is the absolute minimum — just peaks + id, no CV metadata.
        mp = msgpack.packb(
            {
                "mz": zlib.compress(mz.astype("<f8").tobytes()),
                "i": zlib.compress(intensity.astype("<f8").tobytes()),
                "n": n,
                "id": spec.id,
            },
            use_bin_type=True,
        )
        mp_b64 = b64url_encode(mp)

        results.append(
            {
                "id": spec.id,
                "ms_level": spec.ms_level,
                "n_peaks": n,
                "xml": len(xml_bytes),
                "mzx_lossy": len(token_lossy),
                "mzx_lossless": len(token_lossless),
                "mp_b64": len(mp_b64),
            }
        )

hdr = f"{'ID':<22} {'Lvl':>3} {'Peaks':>6} {'XML (B)':>9} {'mzx lossy':>11} {'mzx lossless':>13} {'mp+b64':>8}"
print(hdr)
print("-" * len(hdr))
for r in results:
    print(
        f"{r['id']:<22} {r['ms_level']:>3} {r['n_peaks']:>6} "
        f"{r['xml']:>9} {r['mzx_lossy']:>11} {r['mzx_lossless']:>13} {r['mp_b64']:>8}"
    )

print("-" * len(hdr))
avg = {k: sum(r[k] for r in results) / len(results) for k in ("xml", "mzx_lossy", "mzx_lossless", "mp_b64")}
print(
    f"{'AVERAGE':<22} {'':>3} {'':>6} "
    f"{avg['xml']:>9.0f} {avg['mzx_lossy']:>11.0f} {avg['mzx_lossless']:>13.0f} {avg['mp_b64']:>8.0f}"
)
print()
print("Reduction vs raw XML:")
for label, key in [("mzx lossy    (numpress+zlib+b64)", "mzx_lossy"), ("mzx lossless (raw f64+zlib+b64)", "mzx_lossless"), ("msgpack+b64  (peaks only, no meta)", "mp_b64")]:
    pct = (1 - avg[key] / avg["xml"]) * 100
    print(f"  {label}: {pct:+.1f}%")
