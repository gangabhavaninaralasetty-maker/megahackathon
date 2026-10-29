from engine import SafetyEngine, load_demo_data, evaluate_predictions

def make_engine():
    d = load_demo_data()
    return SafetyEngine(d["medicines"], d["interactions"], d["duplicate_classes"])

def test_exact_alias_resolution():
    result = make_engine().resolve_name("demoa")
    assert result["generic_name"] == "demo_medicine_a"
    assert result["status"] == "exact"

def test_fuzzy_candidate_is_not_confirmed():
    result = make_engine().resolve_name("demo_medcine_a")
    assert result["status"] in ("fuzzy_candidate_requires_verification", "unmatched")
    if result["status"] == "fuzzy_candidate_requires_verification":
        assert result["confidence"] < 1.0

def test_interaction_demo_rule():
    result = make_engine().analyze(["demoa", "demob"], {"age":70, "egfr":60})
    assert any(a["issue_type"] == "interaction" for a in result["alerts"])
    assert "clinician" in result["disclaimer"].lower()

def test_renal_review_flag():
    result = make_engine().analyze(["demoa"], {"age":70, "egfr":25})
    assert any(a["issue_type"] == "renal_dose" for a in result["alerts"])

def test_duplicate_ingredient():
    result = make_engine().analyze(["demoa", "demoa"], {"age":50, "egfr":90})
    assert any(a["issue_type"] == "duplicate_therapy" for a in result["alerts"])

def test_metrics():
    truth = [{"patient_id":"p1","issues":[("interaction","x"),("renal_dose","y")]}]
    pred = [{"patient_id":"p1","issues":[("interaction","x")]}]
    m = evaluate_predictions(truth, pred)
    assert m["tp"] == 1 and m["fn"] == 1
    assert m["precision"] == 1.0 and m["recall"] == 0.5


def test_age_context_prompt_for_older_adult():
    result = make_engine().analyze([], {"age": 70, "egfr": 0, "diagnoses": []})
    assert any(a["issue_type"] == "age_context_review" for a in result["alerts"])


def test_age_context_prompt_for_under_18():
    result = make_engine().analyze([], {"age": 16, "egfr": 0, "diagnoses": []})
    assert any(a["issue_type"] == "age_context_review" for a in result["alerts"])


def test_egfr_context_prompt_does_not_calculate_dose():
    result = make_engine().analyze([], {"age": 40, "egfr": 28, "diagnoses": []})
    alerts = [a for a in result["alerts"] if a["issue_type"] == "kidney_function_review"]
    assert len(alerts) == 1
    assert "do not provide validated eGFR thresholds" in alerts[0]["reason"]


def test_allergy_context_prompt_is_not_clinical_rule():
    from engine import SafetyEngine, load_dataset_data
    from pathlib import Path
    data = load_dataset_data(Path(__file__).resolve().parents[1] / "data")
    engine = SafetyEngine(data["medicines"], data["interactions"], data["duplicate_classes"])
    result = engine.analyze(["Apixaban"], {"age": 40, "egfr": 0, "allergies": "penicillin"})
    assert any(a["issue_type"] == "allergy_review" for a in result["alerts"])


def test_repeated_medicine_entry_gets_duplicate_review():
    from engine import SafetyEngine, load_dataset_data
    from pathlib import Path
    data = load_dataset_data(Path(__file__).resolve().parents[1] / "data")
    engine = SafetyEngine(data["medicines"], data["interactions"], data["duplicate_classes"])
    result = engine.analyze(["Apixaban", "Apixaban"], {"age": 40, "egfr": 0})
    assert any(a["issue_type"] == "duplicate_therapy" for a in result["alerts"])
