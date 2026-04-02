from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from omniagents import function_tool


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


def _round_psu_wattage(watts: int) -> int:
    if watts <= 0:
        return 0
    step = 50
    return ((watts + step - 1) // step) * step


@function_tool
def suggest_retailers(country: str, region: Optional[str] = None) -> Dict[str, Any]:
    """Suggest reputable PC-parts retailers by country.

    Args:
        country: User country (e.g., "US", "United States", "Canada", "UK", "Germany").
        region: Optional region/state/province/city (used mainly for Micro Center availability in the US).

    Returns:
        Dict with keys:
          - normalized_country: str
          - retailers: List[Dict[str, str]] (name, url, notes)
          - guidance: str
    """

    c = _norm(country)
    r = _norm(region)

    def ret(items: List[Tuple[str, str, str]], guidance: str, normalized_country: str) -> Dict[str, Any]:
        return {
            "normalized_country": normalized_country,
            "retailers": [{"name": n, "url": u, "notes": notes} for n, u, notes in items],
            "guidance": guidance,
        }

    if c in {"us", "usa", "united states", "united states of america", "america"}:
        items = [
            ("Micro Center", "https://www.microcenter.com/", "Best bundle deals; in-store focused."),
            ("Newegg", "https://www.newegg.com/", "Good selection; watch third-party sellers."),
            ("Amazon", "https://www.amazon.com/", "Fast shipping; prefer shipped/sold by Amazon or the brand."),
            ("Best Buy", "https://www.bestbuy.com/", "Good for GPUs/CPUs sometimes; check sales."),
            ("B&H", "https://www.bhphotovideo.com/", "Often strong CPU/SSD pricing; reputable."),
        ]
        guidance = "Default to Micro Center bundles if you can buy in-store; otherwise compare Newegg/Amazon/B&H and use Best Buy for sale checks."
        if r:
            guidance = guidance + " If you share your ZIP/city, I can tell you if a Micro Center is realistic."
        return ret(items, guidance, "US")

    if c in {"canada", "ca"}:
        items = [
            ("Memory Express", "https://www.memoryexpress.com/", "Strong builder reputation; in-store and online."),
            ("Canada Computers", "https://www.canadacomputers.com/", "Wide selection; frequent sales."),
            ("Amazon.ca", "https://www.amazon.ca/", "Fast shipping; verify seller."),
            ("Newegg.ca", "https://www.newegg.ca/", "Good selection; watch marketplace sellers."),
        ]
        guidance = "Compare Memory Express and Canada Computers first, then use Amazon.ca/Newegg.ca to fill gaps."
        return ret(items, guidance, "Canada")

    if c in {"uk", "united kingdom", "great britain", "england", "scotland", "wales", "northern ireland"}:
        items = [
            ("Scan", "https://www.scan.co.uk/", "Excellent parts selection; strong reputation."),
            ("Overclockers UK", "https://www.overclockers.co.uk/", "Good for cases/cooling; sometimes higher prices."),
            ("Amazon.co.uk", "https://www.amazon.co.uk/", "Fast shipping; verify seller."),
            ("Ebuyer", "https://www.ebuyer.com/", "Often competitive pricing."),
            ("CCL", "https://www.cclonline.com/", "Solid UK retailer; decent availability."),
        ]
        guidance = "Start with Scan for core parts, then price-check Amazon/Ebuyer/CCL; use OCUK for specific cooling/case stock."
        return ret(items, guidance, "UK")

    if c in {"germany", "de", "deutschland"}:
        items = [
            ("Mindfactory", "https://www.mindfactory.de/", "Often very competitive CPU/GPU pricing."),
            ("Alternate", "https://www.alternate.de/", "Large selection; reliable."),
            ("Caseking", "https://www.caseking.de/", "Great for cases/cooling and specialty parts."),
            ("Amazon.de", "https://www.amazon.de/", "Convenient; verify seller."),
        ]
        guidance = "Price-check Mindfactory first for CPU/GPU, then use Alternate/Caseking for the rest; Amazon.de for availability." 
        return ret(items, guidance, "Germany")

    if c in {"australia", "au"}:
        items = [
            ("PCCG", "https://www.pccasegear.com/", "Popular AU PC builder retailer."),
            ("Scorptec", "https://www.scorptec.com.au/", "Strong selection; reputable."),
            ("Mwave", "https://www.mwave.com.au/", "Competitive pricing; good inventory."),
            ("Centre Com", "https://www.centrecom.com.au/", "Good pricing, especially on bundles."),
        ]
        guidance = "Compare PCCG/Scorptec/Mwave for core parts and use Centre Com for bundle/value checks."
        return ret(items, guidance, "Australia")

    items = [
        ("Amazon", "https://www.amazon.com/", "Convenient fallback; verify seller and region."),
        ("Newegg", "https://www.newegg.com/", "Broad selection; watch third-party sellers."),
    ]
    guidance = "Share your country and preferred stores (or a couple local retailers) and I’ll tailor pricing/availability."
    return ret(items, guidance, country.strip() or "Unknown")


@function_tool
def estimate_psu(
    cpu_tdp_w: int,
    gpu_tdp_w: int,
    other_components_w: int = 100,
    headroom_percent: int = 35,
) -> Dict[str, Any]:
    """Estimate system power draw and recommend a PSU wattage.

    Args:
        cpu_tdp_w: CPU power estimate in watts.
        gpu_tdp_w: GPU power estimate in watts.
        other_components_w: Allowance for motherboard, fans, storage, USB (default 100W).
        headroom_percent: Extra headroom percentage for transient spikes and efficiency (default 35).

    Returns:
        Dict with keys:
          - estimated_system_w: int
          - recommended_psu_w: int
          - notes: List[str]
    """

    base = max(0, cpu_tdp_w) + max(0, gpu_tdp_w) + max(0, other_components_w)
    recommended = int(base * (1 + max(0, headroom_percent) / 100))
    recommended = _round_psu_wattage(recommended)

    notes: List[str] = []
    if gpu_tdp_w >= 300:
        notes.append("High-end GPU: prefer a quality 80+ Gold PSU from a reputable OEM.")
    if recommended and recommended < 550:
        notes.append("If pricing is close, bumping to 650W can improve upgrade flexibility.")
    notes.append("Confirm the PSU has the right GPU power connectors for the chosen graphics card.")

    return {
        "estimated_system_w": base,
        "recommended_psu_w": recommended,
        "notes": notes,
    }


@function_tool
def validate_compatibility(build: Dict[str, Any]) -> Dict[str, Any]:
    """Validate basic PC part compatibility from a structured build summary.

    Provide a minimal structured summary of the build (you can include extra keys). This tool checks what it can and reports unknowns.

    Expected keys (recommended):
      - cpu_socket: str (e.g., "AM5", "LGA1700")
      - motherboard_socket: str
      - ram_type: str (e.g., "DDR4", "DDR5")
      - motherboard_ram_type: str
      - motherboard_form_factor: str (e.g., "ATX", "mATX", "Mini-ITX")
      - case_supported_form_factors: List[str]
      - gpu_length_mm: int (optional)
      - case_gpu_max_length_mm: int (optional)
      - cpu_cooler_height_mm: int (optional, air)
      - case_cooler_max_height_mm: int (optional)
      - psu_wattage: int (optional)
      - recommended_psu_w: int (optional)

    Args:
        build: Structured build summary.

    Returns:
        Dict with keys:
          - ok: bool
          - issues: List[str]
          - warnings: List[str]
          - unknowns: List[str]
    """

    issues: List[str] = []
    warnings: List[str] = []
    unknowns: List[str] = []

    cpu_socket = _norm(str(build.get("cpu_socket")) if build.get("cpu_socket") is not None else None)
    motherboard_socket = _norm(
        str(build.get("motherboard_socket")) if build.get("motherboard_socket") is not None else None
    )

    if cpu_socket and motherboard_socket:
        if cpu_socket != motherboard_socket:
            issues.append(f"CPU socket ({build.get('cpu_socket')}) does not match motherboard socket ({build.get('motherboard_socket')}).")
    else:
        unknowns.append("cpu_socket/motherboard_socket")

    ram_type = _norm(str(build.get("ram_type")) if build.get("ram_type") is not None else None)
    motherboard_ram_type = _norm(
        str(build.get("motherboard_ram_type")) if build.get("motherboard_ram_type") is not None else None
    )

    if ram_type and motherboard_ram_type:
        if ram_type != motherboard_ram_type:
            issues.append(f"RAM type ({build.get('ram_type')}) does not match motherboard RAM type ({build.get('motherboard_ram_type')}).")
    else:
        unknowns.append("ram_type/motherboard_ram_type")

    motherboard_ff = _norm(
        str(build.get("motherboard_form_factor")) if build.get("motherboard_form_factor") is not None else None
    )
    case_ffs_raw = build.get("case_supported_form_factors")
    case_ffs: List[str] = []
    if isinstance(case_ffs_raw, list):
        case_ffs = [_norm(str(x)) for x in case_ffs_raw]

    if motherboard_ff and case_ffs:
        if motherboard_ff not in case_ffs:
            issues.append(
                f"Motherboard form factor ({build.get('motherboard_form_factor')}) not listed as supported by case ({build.get('case_supported_form_factors')})."
            )
    else:
        unknowns.append("motherboard_form_factor/case_supported_form_factors")

    gpu_len = build.get("gpu_length_mm")
    case_gpu_max = build.get("case_gpu_max_length_mm")
    if isinstance(gpu_len, int) and isinstance(case_gpu_max, int):
        if gpu_len > case_gpu_max:
            issues.append(f"GPU length ({gpu_len}mm) exceeds case clearance ({case_gpu_max}mm).")
    else:
        unknowns.append("gpu_length_mm/case_gpu_max_length_mm")

    cooler_h = build.get("cpu_cooler_height_mm")
    case_cooler_max = build.get("case_cooler_max_height_mm")
    if isinstance(cooler_h, int) and isinstance(case_cooler_max, int):
        if cooler_h > case_cooler_max:
            issues.append(f"CPU cooler height ({cooler_h}mm) exceeds case clearance ({case_cooler_max}mm).")
    else:
        unknowns.append("cpu_cooler_height_mm/case_cooler_max_height_mm")

    psu_w = build.get("psu_wattage")
    rec_psu_w = build.get("recommended_psu_w")
    if isinstance(psu_w, int) and isinstance(rec_psu_w, int) and rec_psu_w > 0:
        if psu_w < rec_psu_w:
            warnings.append(f"PSU wattage ({psu_w}W) is below the recommendation ({rec_psu_w}W).")
    else:
        unknowns.append("psu_wattage/recommended_psu_w")

    ok = len(issues) == 0
    return {"ok": ok, "issues": issues, "warnings": warnings, "unknowns": unknowns}
