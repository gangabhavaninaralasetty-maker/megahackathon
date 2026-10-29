import re
import csv
from pathlib import Path
from difflib import SequenceMatcher

DISCLAIMER = ("This prototype is for educational demonstration only and is not validated for clinical use. "
              "A qualified clinician must verify every alert and decide the appropriate action. "
              "An incomplete medication list means that no detected issue is not proof of safety.")

def norm(s):
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def load_dataset_data(data_dir=None):
    """Load the user-supplied Kaggle CSVs as an unvalidated reference dataset.

    This does not imply clinical validation. Severity is intentionally REVIEW because
    the interaction CSV has no validated severity column.
    """
    root = Path(data_dir) if data_dir else Path(__file__).resolve().parent / "data"
    interactions_path = root / "drug_interaction.csv"
    medicines_path = root / "drug_information_1258.csv"
    if not interactions_path.exists() or not medicines_path.exists():
        raise FileNotFoundError(
            "Dataset CSVs not found. Put drug_interaction.csv and "
            "drug_information_1258.csv inside the project's data/ folder."
        )

    medicines = {}
    with medicines_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            medicines[name] = {
                "generic_name": name,
                "class": "CLASS_NOT_PROVIDED",
                "brands": [],
                "renal_adjustment_flag": "NO_VALIDATED_RULE_SUPPLIED",
                "database_id": (row.get("id") or "").strip(),
                "target": (row.get("target") or "").strip(),
                "enzyme": (row.get("enzyme") or "").strip(),
                "demo_only": False,
            }

    interactions = []
    seen = set()
    with interactions_path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            a = (row.get("drugA") or "").strip()
            b = (row.get("drugB") or "").strip()
            if not a or not b:
                continue
            key = (norm(a), norm(b), (row.get("mechanism") or "").strip(), (row.get("action") or "").strip())
            if key in seen:
                continue
            seen.add(key)
            mechanism = (row.get("mechanism") or "Interaction mechanism not specified").strip()
            action = (row.get("action") or "not specified").strip()
            interactions.append({
                "drug_a": a,
                "drug_b": b,
                "severity": "REVIEW",
                "rule_id": f"KAGGLE_DDI_{len(interactions)+1}",
                "mechanism": mechanism,
                "dataset_action": action,
                "action": "Treat this as an unvalidated reference signal. A qualified clinician must verify it against an authoritative interaction reference.",
                "limitation": "Kaggle dataset row; clinical validity, context, severity, and patient-specific significance have not been independently verified.",
                "demo_only": False,
                "source": "user-supplied Kaggle CSV (unvalidated)",
            })

    return {
        "medicines": medicines,
        "interactions": interactions,
        "duplicate_classes": set(),
        "dataset_mode": True,
        "source_summary": {
            "medicine_rows_loaded": len(medicines),
            "interaction_rows_loaded": len(interactions),
            "source": "user-supplied Kaggle CSV; unvalidated",
        },
    }

def load_demo_data():
    # EXPLICITLY SYNTHETIC PLACEHOLDERS. No clinical drug reference is being asserted.
    medicines = {
        "demo_medicine_a": {
            "generic_name":"demo_medicine_a", "class":"DEMO_CLASS_ALPHA",
            "brands":["demoa"], "renal_adjustment_flag":"REVIEW_REQUIRED",
            "pregnancy_category":"NOT_PROVIDED", "demo_only":True
        },
        "demo_medicine_b": {
            "generic_name":"demo_medicine_b", "class":"DEMO_CLASS_BETA",
            "brands":["demob"], "renal_adjustment_flag":"NO_RULE_SUPPLIED",
            "pregnancy_category":"NOT_PROVIDED", "demo_only":True
        },
        "demo_medicine_c": {
            "generic_name":"demo_medicine_c", "class":"DEMO_CLASS_ALPHA",
            "brands":["democ"], "renal_adjustment_flag":"NO_RULE_SUPPLIED",
            "pregnancy_category":"NOT_PROVIDED", "demo_only":True
        }
    }
    interactions = [
        {"drug_a":"demo_medicine_a","drug_b":"demo_medicine_b","severity":"HIGH",
         "rule_id":"DEMO_PAIR_A_B","action":"Demo only: review the official interaction reference and assess the patient before making a prescribing decision.",
         "demo_only":True}
    ]
    duplicate_classes = {"DEMO_CLASS_ALPHA"}
    return {"medicines":medicines, "interactions":interactions, "duplicate_classes":duplicate_classes}

class SafetyEngine:
    def __init__(self, medicines, interactions, duplicate_classes=None):
        self.medicines = medicines
        self.interactions = interactions
        self.duplicate_classes = duplicate_classes or set()
        self.aliases = {}
        for generic, info in medicines.items():
            self.aliases[norm(generic)] = generic
            for brand in info.get("brands", []):
                self.aliases[norm(brand)] = generic
        self.interaction_index = {}
        for interaction in interactions:
            key = frozenset((norm(interaction["drug_a"]), norm(interaction["drug_b"])))
            self.interaction_index.setdefault(key, []).append(interaction)

    def resolve_name(self, raw):
        cleaned = norm(raw)
        if not cleaned:
            return {"input":raw, "status":"unmatched", "generic_name":None, "confidence":0.0}
        if cleaned in self.aliases:
            return {"input":raw, "status":"exact", "generic_name":self.aliases[cleaned], "confidence":1.0}
        candidates = [(SequenceMatcher(None, cleaned, alias).ratio(), generic)
                      for alias, generic in self.aliases.items()]
        candidates.sort(reverse=True)
        score, generic = candidates[0] if candidates else (0.0, None)
        if score >= 0.84:
            return {"input":raw, "status":"fuzzy_candidate_requires_verification",
                    "generic_name":generic, "confidence":round(score, 3)}
        return {"input":raw, "status":"unmatched", "generic_name":None, "confidence":round(score, 3)}

    def _alert(self, issue_type, severity, drugs, reason, action, confidence, limitation, rule_id=None, demo_only=True, source=None):
        return {
            "issue_type":issue_type, "severity":severity, "drugs":drugs,
            "reason":reason, "suggested_action":action,
            "confidence":confidence, "limitations":limitation,
            "rule_id":rule_id, "demo_only":demo_only, "source":source
        }

    def analyze(self, raw_meds, patient):
        resolutions = [self.resolve_name(m) for m in raw_meds if str(m).strip()]
        # Only exact matches are allowed to trigger downstream rules. Fuzzy candidates
        # are shown for manual verification but are not treated as confirmed medicines.
        resolved = [r["generic_name"] for r in resolutions
                    if r["generic_name"] and r["status"] == "exact"]
        alerts = []
        # General context prompts only; these are not medicine-specific clinical rules.
        try:
            age = int(patient.get("age", 0) or 0)
        except (TypeError, ValueError):
            age = 0
        if age < 18:
            alerts.append(self._alert(
                "age_context_review", "REVIEW", [],
                "The patient is under 18. This dataset does not contain validated pediatric dosing or age-specific safety rules.",
                "Have a qualified clinician or pharmacist verify each medicine, formulation, and dose using an authoritative pediatric reference.",
                1.0,
                "General context prompt only; no pediatric dosing or medicine-specific age rule is implemented.",
                rule_id="GENERAL_AGE_CONTEXT_UNDER_18", demo_only=False,
                source="general safety workflow prompt; not a clinical decision rule"
            ))
        elif age >= 65:
            alerts.append(self._alert(
                "age_context_review", "REVIEW", [],
                "The patient is 65 or older. Age can affect medication review, but this Kaggle dataset does not include validated older-adult criteria.",
                "Ask a qualified clinician or pharmacist to review the complete medication list, doses, kidney function, and potential adverse effects.",
                1.0,
                "General context prompt only; this does not mean any listed medicine is unsafe and does not replace a validated older-adult reference.",
                rule_id="GENERAL_AGE_CONTEXT_65_PLUS", demo_only=False,
                source="general safety workflow prompt; not a clinical decision rule"
            ))
        # An eGFR value is context, not a basis for a dose recommendation here.
        try:
            egfr = float(patient.get("egfr", 0) or 0)
        except (TypeError, ValueError):
            egfr = 0
        if egfr > 0:
            alerts.append(self._alert(
                "kidney_function_review", "REVIEW", [],
                f"An eGFR value ({egfr:g}) was supplied. The Kaggle files bundled here do not provide validated eGFR thresholds or patient-specific renal dosing rules.",
                "Have a qualified clinician or pharmacist compare the current eGFR and prescribed doses with an authoritative, medicine-specific renal dosing reference.",
                1.0,
                "No dose adjustment is calculated. Units, date of test, clinical context, and individual medicine guidance must be verified.",
                rule_id="KIDNEY_FUNCTION_CONTEXT_REVIEW", demo_only=False,
                source="general safety workflow prompt; not a clinical decision rule"
            ))
        # Allergy/condition/pregnancy context reminders are not diagnostic rules.
        allergy_text = str(patient.get("allergies", "") or "").strip()
        condition_text = str(patient.get("conditions", "") or patient.get("diagnoses", "") or "").strip()
        pregnancy_context = str(patient.get("pregnancy_breastfeeding", "") or "").strip().lower()
        if allergy_text:
            alerts.append(self._alert(
                "allergy_review", "REVIEW", [],
                "Allergy information was supplied, but this prototype has no validated allergen-to-medicine or cross-reactivity reference.",
                "Compare every medicine and ingredient against the person's documented allergy record with a pharmacist or clinician before use.",
                1.0,
                "The app does not determine whether a medicine is safe for a stated allergy.",
                rule_id="ALLERGY_CONTEXT_REVIEW", demo_only=False,
                source="general safety workflow prompt; not a clinical decision rule"
            ))
            allergy_terms = {norm(x) for x in re.split(r"[,;\\n]", allergy_text) if norm(x)}
            for med in set(resolved):
                if norm(med) in allergy_terms:
                    alerts.append(self._alert(
                        "possible_allergy_name_match", "REVIEW", [med],
                        "The medicine name exactly matches a term entered in the allergy field.",
                        "Do not rely on this prototype to decide whether to take it; contact a pharmacist or clinician to verify the allergy record and next steps.",
                        1.0,
                        "Exact text matching is not a clinical allergy assessment and cannot evaluate ingredients or cross-reactivity.",
                        rule_id="ALLERGY_EXACT_TEXT_MATCH", demo_only=False,
                        source="user-entered text comparison; requires clinical verification"
                    ))
        if condition_text:
            alerts.append(self._alert(
                "condition_review", "REVIEW", [],
                "Health conditions were supplied, but no validated condition-specific contraindication rules are loaded.",
                "Ask a clinician or pharmacist to review the complete medicine list alongside the person's conditions.",
                1.0,
                "The app does not infer contraindications from free-text conditions.",
                rule_id="CONDITION_CONTEXT_REVIEW", demo_only=False,
                source="general safety workflow prompt; not a clinical decision rule"
            ))
        if pregnancy_context in {"yes", "pregnant", "breastfeeding", "both"}:
            alerts.append(self._alert(
                "pregnancy_breastfeeding_review", "REVIEW", [],
                "Pregnancy or breastfeeding was selected. The bundled dataset does not contain validated medicine-specific pregnancy or lactation guidance.",
                "Check each medicine with an obstetric clinician or pharmacist before starting, stopping, or changing a medicine.",
                1.0,
                "No medicine is classified as safe or unsafe by this prompt.",
                rule_id="PREGNANCY_LACTATION_CONTEXT_REVIEW", demo_only=False,
                source="general safety workflow prompt; not a clinical decision rule"
            ))

        # Unknown and uncertain names are surfaced rather than silently accepted.
        for r in resolutions:
            if r["status"] == "unmatched":
                alerts.append(self._alert("medication_name_unresolved","REVIEW",
                    [r["input"]],"The name did not match the demonstration reference.",
                    "Verify the package, spelling, and generic name with the source record.",
                    r["confidence"],"No safety checks can be trusted for an unresolved medicine."))
            elif r["status"] == "fuzzy_candidate_requires_verification":
                alerts.append(self._alert("medication_name_uncertain","REVIEW",
                    [r["input"],r["generic_name"]],"A fuzzy candidate was found, but the match is not confirmed.",
                    "Verify the medicine identity before relying on any downstream alert.",
                    r["confidence"],"Similarity is not proof of medicine identity."))

        # Interaction checks use exact medicine-name matches only.
        resolved_norms = {norm(x): x for x in resolved}
        checked_pairs = set()
        for i, a in enumerate(resolved):
            for b in resolved[i+1:]:
                pair_key = frozenset((norm(a), norm(b)))
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)
                for interaction in self.interaction_index.get(pair_key, []):
                    mechanism = interaction.get("mechanism", "Interaction description not supplied")
                    dataset_action = interaction.get("dataset_action", "not specified")
                    reason = (f"The supplied dataset describes: {mechanism}; action field: {dataset_action}. "
                              "This is a screening signal, not a confirmed patient-specific interaction assessment.")
                    alerts.append(self._alert("interaction", interaction["severity"], [a,b],
                        reason,
                        interaction.get("action", "Verify against an authoritative interaction reference."),
                        1.0, interaction.get("limitation", "Reference data not independently validated."),
                        interaction.get("rule_id"), demo_only=interaction.get("demo_only", True),
                        source=interaction.get("source")))

        # Duplicate ingredient and class checks.
        for med in set(resolved):
            if resolved.count(med) > 1:
                alerts.append(self._alert("duplicate_therapy","REVIEW",[med],
                    "The same generic medicine appears more than once.",
                    "Confirm whether entries are duplicate records or intentionally different formulations.",
                    1.0,"The list may be incomplete and directions/formulations were not modelled."))
        class_groups = {}
        for med in set(resolved):
            cls = self.medicines[med].get("class")
            if cls in self.duplicate_classes:
                class_groups.setdefault(cls, []).append(med)
        for cls, meds in class_groups.items():
            if len(meds) > 1:
                alerts.append(self._alert("duplicate_therapy","REVIEW",meds,
                    "Multiple medicines share a class flagged for review in the supplied demo configuration.",
                    "Have a prescriber verify therapeutic intent; class similarity alone does not prove duplication.",
                    0.65,"This is a demonstration heuristic and requires an authoritative class/duplication rule."))

        # Renal adjustment: only flag supplied reference flags; no dose is invented.
        # The general eGFR context prompt above does not infer medicine-specific dosing.
        for med in set(resolved):
            flag = self.medicines[med].get("renal_adjustment_flag", "")
            if flag == "REVIEW_REQUIRED":
                alerts.append(self._alert("renal_dose","REVIEW",[med],
                    "The supplied demo reference marks this medicine for renal review.",
                    "Check the authoritative dosing guidance against the patient's current kidney function and prescribed dose.",
                    1.0,"No validated dose thresholds or dose schedule are included in this demo reference."))
        # Contraindication: only check explicit supplied contraindication rules if added later.
        for med in set(resolved):
            contraindications = self.medicines[med].get("contraindications", [])
            for condition in contraindications:
                if condition in (patient.get("diagnoses") or []):
                    alerts.append(self._alert("contraindication","REVIEW",[med],
                        "A supplied reference rule matched a patient diagnosis.",
                        "Verify the contraindication in the authoritative reference and assess the patient.",
                        1.0,"Demo data only; no validated contraindication reference is bundled."))

        rank = {"CRITICAL":0,"HIGH":1,"MODERATE":2,"REVIEW":3,"LOW":4}
        alerts.sort(key=lambda x: rank.get(x["severity"], 3))
        dataset_mode = any(not row.get("demo_only", True) for row in self.interactions)
        return {
            "patient_summary":{"age":patient.get("age"),"egfr":patient.get("egfr"),
                               "medication_count":len(raw_meds),"resolved_count":len(resolved)},
            "resolutions":resolutions,
            "alerts":alerts,
            "summary":{"alert_count":len(alerts),"unresolved_count":sum(r["status"]=="unmatched" for r in resolutions)},
            "disclaimer":DISCLAIMER,
            "notice":("KAGGLE DATASET MODE: rows are unvalidated reference signals, not clinical advice. "
                      "No detected alert does not prove a medication list is safe." if dataset_mode else
                      "DEMO MODE: all bundled medicines and interaction rules are synthetic placeholders. Do not use for treatment decisions.")
        }

def evaluate_predictions(truth, predicted):
    """Micro metrics on caller-supplied issue tuples. No hidden labels are bundled."""
    def keys(rows):
        return {(r["patient_id"], issue[0], issue[1]) for r in rows for issue in r.get("issues", [])}
    actual, pred = keys(truth), keys(predicted)
    tp = len(actual & pred); fp = len(pred - actual); fn = len(actual - pred)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp":tp,"fp":fp,"fn":fn,"precision":round(precision,4),
            "recall":round(recall,4),"f1":round(f1,4)}
