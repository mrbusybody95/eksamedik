"""
cp_variance.py — Clinical Pathway Variance Analysis
=====================================================
Compares actual extracted data vs standard CP definitions.
Produces per-patient and aggregate variance reports.

Architecture:
  1. Load CP standard JSON (cp_profiles/*.json)
  2. Compare each patient's extraction results vs standard
  3. Classify each field as: COMPLIANT | VARIANCE_DEVIATION | VARIANCE_MISSING | NOT_ASSESSABLE
  4. Produce per-patient + aggregate reports

All logic is disease-agnostic — standards live in JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field as dc_field
from enum import Enum
from pathlib import Path
from typing import Any


# ================================================================
# PATHS
# ================================================================

CP_PROFILES_DIR = Path(__file__).resolve().parent.parent / "cp_profiles"


# ================================================================
# ENUMS & DATA CLASSES
# ================================================================

class VarianceType(str, Enum):
    """Classification of variance between actual and standard."""
    COMPLIANT = "compliant"              # actual matches expected
    VARIANCE_DEVIATION = "deviation"     # actual differs from expected
    VARIANCE_MISSING = "missing"         # expected but not documented (None)
    NOT_ASSESSABLE = "not_assessable"    # data absent, can't compare


class Severity(str, Enum):
    """Standard severity level."""
    WAJIB = "wajib"
    REKOMENDASI = "rekomendasi"


@dataclass
class FieldVariance:
    """Variance result for one field in one patient."""
    field: str
    label: str
    expected: Any
    actual: Any
    variance_type: VarianceType
    severity: Severity
    section: str        # which CP section (e.g. "Diagnostik Wajib")
    category: str       # grouping category (e.g. "Laboratorium")
    note: str = ""      # human-readable explanation

    def to_dict(self) -> dict:
        return {
            "field": self.field,
            "label": self.label,
            "expected": str(self.expected),
            "actual": str(self.actual) if self.actual is not None else "—",
            "variance_type": self.variance_type.value,
            "severity": self.severity.value,
            "section": self.section,
            "category": self.category,
            "note": self.note,
        }


@dataclass
class PatientVarianceReport:
    """Complete variance report for one patient."""
    patient_id: str
    cp_name: str
    variances: list[FieldVariance] = dc_field(default_factory=list)
    los_actual: float | None = None
    los_target_min: float | None = None
    los_target_max: float | None = None

    @property
    def compliant_count(self) -> int:
        return sum(1 for v in self.variances if v.variance_type == VarianceType.COMPLIANT)

    @property
    def deviation_count(self) -> int:
        return sum(1 for v in self.variances if v.variance_type == VarianceType.VARIANCE_DEVIATION)

    @property
    def missing_count(self) -> int:
        return sum(1 for v in self.variances if v.variance_type == VarianceType.VARIANCE_MISSING)

    @property
    def not_assessable_count(self) -> int:
        return sum(1 for v in self.variances if v.variance_type == VarianceType.NOT_ASSESSABLE)

    @property
    def total_standards(self) -> int:
        return len(self.variances)

    @property
    def compliance_rate(self) -> float:
        """Percentage of assessable standards that are compliant."""
        assessable = self.compliant_count + self.deviation_count + self.missing_count
        if assessable == 0:
            return 0.0
        return (self.compliant_count / assessable) * 100

    @property
    def wajib_missing(self) -> list[FieldVariance]:
        """List of mandatory fields that are missing."""
        return [v for v in self.variances
                if v.severity == Severity.WAJIB
                and v.variance_type in (VarianceType.VARIANCE_MISSING, VarianceType.VARIANCE_DEVIATION)]

    @property
    def los_variance(self) -> str | None:
        """LOS variance description, or None if not assessable."""
        if self.los_actual is None:
            return None
        if self.los_target_min is not None and self.los_actual < self.los_target_min:
            return f"Di bawah target ({self.los_actual:.0f} < {self.los_target_min:.0f} hari)"
        if self.los_target_max is not None and self.los_actual > self.los_target_max:
            return f"Di atas target ({self.los_actual:.0f} > {self.los_target_max:.0f} hari)"
        return f"Sesuai target ({self.los_target_min:.0f}-{self.los_target_max:.0f} hari)"

    def to_summary_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "cp_name": self.cp_name,
            "total_standards": self.total_standards,
            "compliant": self.compliant_count,
            "deviation": self.deviation_count,
            "missing": self.missing_count,
            "not_assessable": self.not_assessable_count,
            "compliance_rate_pct": round(self.compliance_rate, 1),
            "wajib_missing_count": len(self.wajib_missing),
            "los_actual": self.los_actual,
            "los_target": f"{self.los_target_min}-{self.los_target_max}" if self.los_target_min else None,
            "los_variance": self.los_variance,
        }


@dataclass
class AggregateReport:
    """Aggregate variance report across all patients."""
    cp_name: str
    patient_reports: list[PatientVarianceReport] = dc_field(default_factory=list)

    @property
    def patient_count(self) -> int:
        return len(self.patient_reports)

    @property
    def avg_compliance_rate(self) -> float:
        if not self.patient_reports:
            return 0.0
        return sum(r.compliance_rate for r in self.patient_reports) / len(self.patient_reports)

    @property
    def total_deviations(self) -> int:
        return sum(r.deviation_count for r in self.patient_reports)

    @property
    def total_missing(self) -> int:
        return sum(r.missing_count for r in self.patient_reports)

    def field_compliance_summary(self) -> dict[str, dict]:
        """Per-field compliance across all patients.
        
        Returns: {field: {label, compliant, missing, deviation, total, compliance_pct}}
        """
        field_stats: dict[str, dict] = {}
        for pr in self.patient_reports:
            for v in pr.variances:
                if v.field not in field_stats:
                    field_stats[v.field] = {
                        "label": v.label,
                        "severity": v.severity.value,
                        "section": v.section,
                        "category": v.category,
                        "compliant": 0, "deviation": 0, "missing": 0, "not_assessable": 0, "total": 0,
                    }
                fs = field_stats[v.field]
                fs["total"] += 1
                if v.variance_type == VarianceType.COMPLIANT:
                    fs["compliant"] += 1
                elif v.variance_type == VarianceType.VARIANCE_DEVIATION:
                    fs["deviation"] += 1
                elif v.variance_type == VarianceType.VARIANCE_MISSING:
                    fs["missing"] += 1
                else:
                    fs["not_assessable"] += 1

        # Compute compliance %
        for f, fs in field_stats.items():
            assessable = fs["compliant"] + fs["deviation"] + fs["missing"]
            fs["compliance_pct"] = round((fs["compliant"] / assessable) * 100, 1) if assessable > 0 else 0.0

        return field_stats

    def los_summary(self) -> dict:
        """Aggregate LOS statistics."""
        los_values = [r.los_actual for r in self.patient_reports if r.los_actual is not None]
        if not los_values:
            return {"count": 0, "mean": None, "median": None, "min": None, "max": None,
                    "above_target": 0, "below_target": 0, "within_target": 0}
        
        los_values.sort()
        n = len(los_values)
        median = los_values[n // 2] if n % 2 == 1 else (los_values[n // 2 - 1] + los_values[n // 2]) / 2

        above = sum(1 for r in self.patient_reports
                    if r.los_actual is not None and r.los_target_max is not None and r.los_actual > r.los_target_max)
        below = sum(1 for r in self.patient_reports
                    if r.los_actual is not None and r.los_target_min is not None and r.los_actual < r.los_target_min)
        within = len(los_values) - above - below

        return {
            "count": n,
            "mean": round(sum(los_values) / n, 1),
            "median": round(median, 1),
            "min": los_values[0],
            "max": los_values[-1],
            "above_target": above,
            "below_target": below,
            "within_target": within,
        }

    def wajib_compliance_summary(self) -> dict[str, dict]:
        """Per-field compliance for WAJIB fields only.
        
        Returns: {field: {label, compliant, missing, total, compliance_pct}}
        """
        all_fields = self.field_compliance_summary()
        return {f: fs for f, fs in all_fields.items() if fs["severity"] == "wajib"}


# ================================================================
# CP PROFILE LOADER
# ================================================================

def list_cp_profiles() -> list[dict[str, str]]:
    """List all available CP standard profiles.
    
    Returns: list of {name, file, disease_profile_ref, standard_count}
    """
    profiles = []
    if not CP_PROFILES_DIR.exists():
        return profiles
    for fp in sorted(CP_PROFILES_DIR.glob("*.json")):
        if fp.name.startswith("_"):
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            n_items = sum(len(items) for items in data.get("standards", {}).values())
            profiles.append({
                "name": data.get("name", fp.stem),
                "file": fp.name,
                "disease_profile_ref": data.get("disease_profile_ref", ""),
                "version": data.get("version", "1.0"),
                "standard_count": n_items,
                "los_target": data.get("los_target", {}),
            })
        except Exception:
            pass
    return profiles


def load_cp_profile(cp_name: str) -> dict:
    """Load a CP standard profile by name or filename.
    
    Args:
        cp_name: e.g. "Stroke Infark", "stroke_infark.json", or "stroke_infark"
    
    Returns:
        CP profile dict with "standards" and "los_target"
    
    Raises:
        FileNotFoundError: if profile not found
    """
    # Try direct filename
    fp = CP_PROFILES_DIR / cp_name
    if not fp.exists():
        fp = CP_PROFILES_DIR / f"{cp_name}.json"
    if not fp.exists():
        # Search by name field
        for f in CP_PROFILES_DIR.glob("*.json"):
            if f.name.startswith("_"):
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("name", "").lower() == cp_name.lower():
                    fp = f
                    break
                if data.get("disease_profile_ref", "").lower() == cp_name.lower():
                    fp = f
                    break
            except Exception:
                continue

    if not fp.exists():
        raise FileNotFoundError(f"CP profile not found: {cp_name}")

    data = json.loads(fp.read_text(encoding="utf-8"))
    if "standards" not in data:
        raise ValueError(f"CP profile missing 'standards': {fp.name}")

    return data


def find_cp_for_disease(disease_profile_name: str) -> dict | None:
    """Find matching CP standard for a disease profile.
    
    Args:
        disease_profile_name: e.g. "Stroke Infark" or "stroke_infark"
    
    Returns:
        CP profile dict, or None if no matching CP found.
    """
    try:
        return load_cp_profile(disease_profile_name)
    except (FileNotFoundError, ValueError):
        pass

    # Try matching by disease_profile_ref
    for fp in CP_PROFILES_DIR.glob("*.json"):
        if fp.name.startswith("_"):
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            ref = data.get("disease_profile_ref", "").lower()
            if ref == disease_profile_name.lower().replace(" ", "_"):
                return data
        except Exception:
            continue
    return None


# ================================================================
# VARIANCE ENGINE
# ================================================================

def compare_patient(
    extraction_result: dict[str, Any],
    cp_profile: dict,
) -> PatientVarianceReport:
    """Compare one patient's extraction results vs CP standard.
    
    Args:
        extraction_result: dict from extract_one_patient() (field → value)
        cp_profile: loaded CP profile dict (with "standards" and "los_target")
    
    Returns:
        PatientVarianceReport with all field variances.
    """
    patient_id = extraction_result.get("patient_id", "unknown")
    cp_name = cp_profile.get("name", "Unknown CP")
    los_target = cp_profile.get("los_target", {})
    los_min = los_target.get("min")
    los_max = los_target.get("max")

    report = PatientVarianceReport(
        patient_id=patient_id,
        cp_name=cp_name,
        los_target_min=los_min,
        los_target_max=los_max,
    )

    # Extract actual LOS
    los_actual = extraction_result.get("lama_rawat_hari")
    if los_actual is not None:
        try:
            report.los_actual = float(los_actual)
        except (ValueError, TypeError):
            pass

    # Compare each standard item
    standards = cp_profile.get("standards", {})
    for section_name, items in standards.items():
        for item in items:
            fv = _compare_one_field(extraction_result, item, section_name)
            report.variances.append(fv)

    # Add explicit LOS target variance if LOS is documented
    if report.los_actual is not None and (los_min is not None or los_max is not None):
        los_field = "lama_rawat_hari"
        los_label = "Lama Rawat (Target CP)"
        if los_max is not None and report.los_actual > los_max:
            report.variances.append(FieldVariance(
                field=los_field, label=los_label, expected=f"{los_min}-{los_max} hari",
                actual=report.los_actual,
                variance_type=VarianceType.VARIANCE_DEVIATION,
                severity=Severity.WAJIB, section="LOS Target", category="Outcome",
                note=f"Melebihi target ({report.los_actual:.0f} > {los_max:.0f} hari)",
            ))
        elif los_min is not None and report.los_actual < los_min:
            report.variances.append(FieldVariance(
                field=los_field, label=los_label, expected=f"{los_min}-{los_max} hari",
                actual=report.los_actual,
                variance_type=VarianceType.VARIANCE_DEVIATION,
                severity=Severity.REKOMENDASI, section="LOS Target", category="Outcome",
                note=f"Di bawah target ({report.los_actual:.0f} < {los_min:.0f} hari)",
            ))
        else:
            report.variances.append(FieldVariance(
                field=los_field, label=los_label, expected=f"{los_min}-{los_max} hari",
                actual=report.los_actual,
                variance_type=VarianceType.COMPLIANT,
                severity=Severity.WAJIB, section="LOS Target", category="Outcome",
                note=f"Sesuai target ({los_min}-{los_max} hari)",
            ))

    return report


def _compare_one_field(
    extraction: dict[str, Any],
    standard: dict,
    section_name: str,
) -> FieldVariance:
    """Compare one field against its standard.
    
    Standard item format:
      {"field": "...", "expected": "ada"/numeric, "label": "...", "severity": "wajib"/"rekomendasi", "category": "..."}
    
    Logic:
      - expected="ada" (boolean check): actual in ("ada", "ada (+)", ...) → COMPLIANT
                                        actual == "tidak" → VARIANCE_DEVIATION
                                        actual is None → VARIANCE_MISSING
      - expected=numeric: actual matches → COMPLIANT
                          actual differs → VARIANCE_DEVIATION
                          actual is None → NOT_ASSESSABLE
    """
    field = standard["field"]
    expected = standard["expected"]
    label = standard.get("label", field)
    severity = Severity(standard.get("severity", "wajib"))
    category = standard.get("category", "")

    actual = extraction.get(field)

    # Case 1: Boolean-style expected ("ada")
    if expected == "ada":
        if actual is None:
            return FieldVariance(
                field=field, label=label, expected="ada", actual=None,
                variance_type=VarianceType.VARIANCE_MISSING,
                severity=severity, section=section_name, category=category,
                note=f"{label} tidak terdokumentasi",
            )
        actual_str = str(actual).lower().strip()
        negative_markers = ("tidak", "negatif", "minus", "-", "belum", "bukan", "tidak ada")
        if actual_str in negative_markers:
            return FieldVariance(
                field=field, label=label, expected="ada", actual=actual,
                variance_type=VarianceType.VARIANCE_DEVIATION,
                severity=severity, section=section_name, category=category,
                note=f"Tidak dilakukan/tidak ada (dokumentasi: '{actual}')",
            )
        # Any other non-None value = documented/exists (including numeric values like "12.5")
        return FieldVariance(
            field=field, label=label, expected="ada", actual=actual,
            variance_type=VarianceType.COMPLIANT,
            severity=severity, section=section_name, category=category,
            note="Sesuai standar",
        )

    # Case 2: Numeric expected
    if isinstance(expected, (int, float)):
        if actual is None:
            return FieldVariance(
                field=field, label=label, expected=expected, actual=None,
                variance_type=VarianceType.NOT_ASSESSABLE,
                severity=severity, section=section_name, category=category,
                note=f"{label} tidak tercatat, tidak bisa dinilai",
            )
        try:
            actual_num = float(actual)
            if actual_num == expected:
                return FieldVariance(
                    field=field, label=label, expected=expected, actual=actual,
                    variance_type=VarianceType.COMPLIANT,
                    severity=severity, section=section_name, category=category,
                    note="Sesuai standar",
                )
            else:
                return FieldVariance(
                    field=field, label=label, expected=expected, actual=actual,
                    variance_type=VarianceType.VARIANCE_DEVIATION,
                    severity=severity, section=section_name, category=category,
                    note=f"Nilai: {actual} (expected: {expected})",
                )
        except (ValueError, TypeError):
            return FieldVariance(
                field=field, label=label, expected=expected, actual=actual,
                variance_type=VarianceType.NOT_ASSESSABLE,
                severity=severity, section=section_name, category=category,
                note=f"Nilai '{actual}' bukan angka",
            )

    # Case 3: String expected (exact match)
    if isinstance(expected, str):
        if actual is None:
            return FieldVariance(
                field=field, label=label, expected=expected, actual=None,
                variance_type=VarianceType.VARIANCE_MISSING,
                severity=severity, section=section_name, category=category,
                note=f"{label} tidak terdokumentasi",
            )
        if str(actual).lower().strip() == expected.lower().strip():
            return FieldVariance(
                field=field, label=label, expected=expected, actual=actual,
                variance_type=VarianceType.COMPLIANT,
                severity=severity, section=section_name, category=category,
                note="Sesuai standar",
            )
        return FieldVariance(
            field=field, label=label, expected=expected, actual=actual,
            variance_type=VarianceType.VARIANCE_DEVIATION,
            severity=severity, section=section_name, category=category,
            note=f"Dokumentasi: '{actual}' (expected: '{expected}')",
        )

    # Fallback — unknown expected type
    return FieldVariance(
        field=field, label=label, expected=expected, actual=actual,
        variance_type=VarianceType.NOT_ASSESSABLE,
        severity=severity, section=section_name, category=category,
        note=f"Tipe standar tidak dikenali: {type(expected)}",
    )


# ================================================================
# AGGREGATE
# ================================================================

def analyze_all_patients(
    extraction_results: list[dict[str, Any]],
    cp_profile: dict,
) -> AggregateReport:
    """Run variance analysis for all patients against a CP standard.
    
    Args:
        extraction_results: list of dicts from extract_all_patients()
        cp_profile: loaded CP profile dict
    
    Returns:
        AggregateReport with per-patient + aggregate stats
    """
    cp_name = cp_profile.get("name", "Unknown")
    agg = AggregateReport(cp_name=cp_name)

    for result in extraction_results:
        pr = compare_patient(result, cp_profile)
        agg.patient_reports.append(pr)

    return agg


# ================================================================
# CLI TEST
# ================================================================

if __name__ == "__main__":
    print("=== Clinical Pathway Variance Analysis ===\n")

    profiles = list_cp_profiles()
    print(f"Available CP profiles ({len(profiles)}):")
    for p in profiles:
        los = p.get("los_target", {})
        los_str = f"LOS {los.get('min', '?')}-{los.get('max', '?')} hari" if los else "LOS: -"
        print(f"  • {p['name']} ({p['file']}) — {p['standard_count']} standar, {los_str}")

    # Demo: load and show one
    if profiles:
        print(f"\n--- Detail: {profiles[0]['name']} ---")
        cp = load_cp_profile(profiles[0]["name"])
        for section, items in cp["standards"].items():
            print(f"\n  [{section}]")
            for item in items:
                sev = "🔴" if item.get("severity") == "wajib" else "🟡"
                print(f"    {sev} {item['label']} — field: {item['field']}, expected: {item['expected']}")
