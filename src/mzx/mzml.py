"""Bridge from mzmlpy.spectra.Spectrum to InlineSpectrum.

Tree-walk rules:
  NAMED REGISTRY KEYS — default_array_length (key 1), id (key 2).
  CV — everything from cv_params on spectrum, scans, scan windows, precursors, products.
  PEAK ARRAYS — mz, intensity, charge, ion_mobility as separate segments.
  EXPAND — ref_params dereferenced via optional ref_group lookup; their cvParams emitted.
  DROP — index, source_file_ref, data_processing_ref, ns, spot_id.
"""

from __future__ import annotations

from mzmlpy.constants import ION_MOBILITIES
from mzmlpy.elems.params import CvParam

from .model import (
    InlineSpectrum,
    MzxActivation,
    MzxCvParam,
    MzxIsolationWindow,
    MzxPrecursor,
    MzxProduct,
    MzxScan,
    MzxScanWindow,
    MzxSelectedIon,
)


def _convert_cvparam(cv: CvParam) -> MzxCvParam:
    """Convert a mzmlpy CvParam to MzxCvParam.

    Numeric string values are coerced to float/int where possible.
    """
    value: float | int | str | None = None
    if cv.value is not None:
        try:
            f = float(cv.value)
            value = int(f) if f == int(f) else f
        except (ValueError, OverflowError):
            value = cv.value
    return MzxCvParam(
        accession=cv.accession,
        value=value,
        unit_accession=cv.unit_accession if cv.unit_accession else None,
    )


def _expand_ref_params(obj, ref_groups: dict | None) -> list[MzxCvParam]:
    """Resolve ref_params on an mzmlpy _ParamGroup object and return converted cvParams."""
    extra: list[MzxCvParam] = []
    if ref_groups is None:
        return extra
    for rp in obj.ref_params:
        group = ref_groups.get(rp.ref)
        if group is not None:
            for cv in group.cv_params:
                extra.append(_convert_cvparam(cv))
    return extra


def _collect_cvparams(obj, ref_groups: dict | None) -> list[MzxCvParam]:
    """Return all cvParams from obj (including expanded ref_params)."""
    direct = [_convert_cvparam(cv) for cv in obj.cv_params]
    expanded = _expand_ref_params(obj, ref_groups)
    return direct + expanded


def from_mzmlpy(spec, ref_groups: dict | None = None) -> InlineSpectrum:
    """Convert a mzmlpy Spectrum to InlineSpectrum.

    Args:
        spec: A mzmlpy.spectra.Spectrum instance.
        ref_groups: Optional dict mapping group id → mzmlpy _ParamGroup for
            dereferencing referenceableParamGroupRef elements. Pass
            ``{g.id: g for g in mzml.referenceable_param_groups}`` if available.

    Returns:
        InlineSpectrum ready for encoding.
    """

    # ─── Spectrum-level CV params (EXPAND ref_params) ───────────────────────
    spectrum_params = _collect_cvparams(spec, ref_groups)

    # ─── Scan list ───────────────────────────────────────────────────────────
    scans_out: list[MzxScan] = []
    scan_combination_out = None

    if spec._has_scan_list and spec._scan_list is not None:
        sl = spec._scan_list
        combo = sl.spectra_combination
        if combo is not None:
            scan_combination_out = MzxCvParam(accession=str(combo))

        for scan in sl.scans:
            scan_params = _collect_cvparams(scan, ref_groups)
            windows_out: list[MzxScanWindow] = []
            if scan._has_scan_windows_list and scan._scan_window_list is not None:
                for w in scan._scan_window_list.scan_windows:
                    w_params = _collect_cvparams(w, ref_groups)
                    windows_out.append(MzxScanWindow(params=w_params))
            scans_out.append(MzxScan(params=scan_params, windows=windows_out))

    # ─── Precursor list ──────────────────────────────────────────────────────
    precursors_out: list[MzxPrecursor] = []
    if spec.has_precursors:
        for pre in spec.precursors:
            iw_out = None
            if pre.isolation_window is not None:
                iw_out = MzxIsolationWindow(params=_collect_cvparams(pre.isolation_window, ref_groups))

            selected_ions_out: list[MzxSelectedIon] = []
            for si_elem in pre.element.findall(f"./{pre.ns}selectedIonList/{pre.ns}selectedIon"):
                from mzmlpy.spectra import SelectedIon
                si = SelectedIon(si_elem)
                selected_ions_out.append(MzxSelectedIon(params=_collect_cvparams(si, ref_groups)))

            act_out = None
            if pre.activation is not None:
                act_out = MzxActivation(params=_collect_cvparams(pre.activation, ref_groups))

            # @spectrumRef → USI back-link
            spectrum_ref = pre.spectrum_ref

            precursors_out.append(MzxPrecursor(
                isolation_window=iw_out,
                selected_ions=selected_ions_out,
                activation=act_out,
                spectrum_ref=spectrum_ref,
            ))

    # ─── Product list ────────────────────────────────────────────────────────
    products_out: list[MzxProduct] = []
    if spec.has_products:
        for prod in spec.products:
            iw_out = None
            if prod.isolation_window is not None:
                iw_out = MzxIsolationWindow(params=_collect_cvparams(prod.isolation_window, ref_groups))
            products_out.append(MzxProduct(isolation_window=iw_out))

    # ─── Peak arrays ─────────────────────────────────────────────────────────
    mz = spec.mz
    intensity = spec.intensity
    charge = spec.charge

    im = None
    im_type = None
    if spec.has_im:
        for im_acc in ION_MOBILITIES:
            arr = spec.get_binary_array(str(im_acc))
            if arr is not None:
                data = arr.data
                if len(data) > 0:
                    im = data
                    im_type = str(im_acc)
                    break

    return InlineSpectrum(
        default_array_length=spec.default_array_length or (len(mz) if mz is not None else 0),
        mz=mz,
        intensity=intensity,
        charge=charge,
        ion_mobility=im,
        ion_mobility_type=im_type,
        id=spec.id,
        params=spectrum_params,
        scans=scans_out,
        scan_combination=scan_combination_out,
        precursors=precursors_out,
        products=products_out,
    )
