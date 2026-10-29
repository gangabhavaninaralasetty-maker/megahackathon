import os, io, csv, json, urllib.request, urllib.error
from flask import Flask, render_template, request, jsonify, send_file, session, redirect, url_for, flash
from functools import wraps
from datetime import datetime, timezone
import secrets
from engine import SafetyEngine, load_demo_data, load_dataset_data, evaluate_predictions

app = Flask(__name__)
app.secret_key = os.environ.get("MEDIGUARD_SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 8 * 1024 * 1024
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
try:
    DATA = load_dataset_data(DATA_DIR)
except FileNotFoundError:
    DATA = load_demo_data()
ENGINE = SafetyEngine(DATA["medicines"], DATA["interactions"], DATA["duplicate_classes"])
DEMO_MODE = not DATA.get("dataset_mode", False)
# Privacy-preserving demo counters only: no medication lists or patient identifiers are stored.
STATS = {"checks": 0, "pdf_exports": 0, "assistant_requests": 0}

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/checker")
def checker():
    return render_template("checker.html", medicines=sorted(DATA["medicines"].keys()))

@app.route("/medicine-guide")
def medicine_guide():
    return render_template("medicine_guide.html", medicine_count=len(DATA["medicines"]))

@app.route("/technical")
def technical():
    return render_template("technical.html", demo_mode=DEMO_MODE)

@app.route("/assistant")
def assistant():
    return render_template("assistant.html", model=os.environ.get("OLLAMA_MODEL", "llama3.2:3b"))

@app.route("/api/ollama-status")
def ollama_status():
    """Check the local Ollama API without exposing patient data."""
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    try:
        req = urllib.request.Request(base_url + "/api/tags", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        model_names = [item.get("name", "") for item in payload.get("models", [])]
        model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
        found = any(name == model or name.startswith(model + ":") for name in model_names)
        return jsonify({"status": "connected", "model": model, "model_available": found, "models": model_names})
    except Exception:
        return jsonify({"status": "disconnected", "model": os.environ.get("OLLAMA_MODEL", "llama3.2:3b"), "model_available": False}), 503

@app.route("/api/assistant", methods=["POST"])
def ollama_assistant():
    """Use local Ollama for explanations, never as the interaction checker."""
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("question", "")).strip()
    if not question or len(question) > 2000:
        return jsonify({"error": "Enter a question (up to 2,000 characters)."}), 400

    language = str(payload.get("language", "en")).lower()
    if language not in {"en", "te"}:
        language = "en"
    STATS["assistant_requests"] += 1
    summary = payload.get("screening_summary")
    if summary is not None:
        if not isinstance(summary, dict):
            return jsonify({"error": "Invalid screening summary."}), 400
        resolutions = summary.get("resolutions", [])
        alerts = summary.get("alerts", [])
        if not isinstance(resolutions, list) or not isinstance(alerts, list):
            return jsonify({"error": "Invalid screening summary."}), 400
        safe_summary = {
            "mode": str(summary.get("mode", "unknown"))[:80],
            "resolutions": [{"input": str(x.get("input", ""))[:100], "generic_name": str(x.get("generic_name", ""))[:100], "status": str(x.get("status", ""))[:50]} for x in resolutions[:20] if isinstance(x, dict)],
            "alerts": [{"issue_type": str(x.get("issue_type", ""))[:100], "severity": str(x.get("severity", ""))[:30], "drugs": [str(d)[:100] for d in x.get("drugs", [])[:2]] if isinstance(x.get("drugs", []), list) else [], "reason": str(x.get("reason", ""))[:500], "suggested_action": str(x.get("suggested_action", ""))[:500], "limitations": str(x.get("limitations", ""))[:500]} for x in alerts[:190] if isinstance(x, dict)],
            "notice": "This is an unvalidated educational screening prototype. No matching alert is not proof of safety."
        }
        user_content = ("Explain the supplied screening output in simple language. Do not add or infer any new interaction, contraindication, dose, diagnosis, or safety conclusion. If the output does not establish a fact, say it is not verified.\n\nScreening output JSON:\n" + json.dumps(safe_summary, ensure_ascii=False) + "\n\nUser question: " + question)
    else:
        user_content = question

    language_instruction = ("Respond in simple Telugu (తెలుగు), preferably conversational Telugu, while keeping medicine names and technical terms in English when clearer. Do not translate or alter medicine names." if language == "te" else "Respond in simple English.")
    system_prompt = (
        "You are MediGuard AI's educational medicine-information explainer. " + language_instruction + " You are not a clinician and must not diagnose, prescribe, recommend starting/stopping/changing a medicine, or provide patient-specific dosage instructions. "
        "Never invent drug interactions, side effects, indications, contraindications, evidence, or citations. If asked whether a specific medicine or combination is safe, say you cannot verify that from the available evidence and direct the user to a pharmacist or prescriber. "
        "When a screening output is supplied, explain only the exact fields in that output and clearly state its dataset is unvalidated. Do not interpret absence of alerts as proof of safety. "
        "For emergencies or a possible serious reaction, advise seeking urgent local medical help. Use simple, concise language and label uncertain information clearly."
    )
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
    body = json.dumps({"model": model, "stream": False, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}], "options": {"temperature": 0.1}}).encode("utf-8")
    req = urllib.request.Request(base_url + "/api/chat", data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
        answer = str(result.get("message", {}).get("content", "")).strip()
        if not answer:
            return jsonify({"error": "Ollama returned an empty response. Try again."}), 502
        return jsonify({"answer": answer, "model": model, "disclaimer": "AI-generated educational explanation only. Not verified medical advice; do not use it to make treatment decisions."})
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")[:500]
        return jsonify({"error": "Ollama API error. Check that the selected model is downloaded and Ollama is running.", "details": details}), 502
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return jsonify({"error": "Cannot reach Ollama at " + base_url + ". Open the Ollama app and check `ollama list` in Terminal.", "details": str(exc)[:300]}), 503

@app.route("/api/medicine-info")
def medicine_info():
    """Look up only metadata present in the bundled reference CSV; no medical advice."""
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"error": "Enter a medicine name."}), 400
    match = ENGINE.resolve_name(q)
    if match.get("status") == "exact":
        name = match.get("generic_name")
        info = DATA["medicines"].get(name, {})
        return jsonify({
            "status": "exact",
            "name": name,
            "database_id": info.get("database_id", ""),
            "target": info.get("target", ""),
            "enzyme": info.get("enzyme", ""),
            "message": "Only the metadata shown above is present in this dataset. It does not establish approved uses, dose, side effects, or whether this medicine is appropriate for a person."
        })
    if match.get("status") == "fuzzy_candidate_requires_verification":
        return jsonify({
            "status": "fuzzy_candidate_requires_verification",
            "candidate": match.get("generic_name"),
            "confidence": match.get("confidence", 0),
            "message": "No exact match was found. This is only a text-similarity suggestion; check the spelling and verify the medicine with a pharmacist."
        })
    return jsonify({
        "status": "unmatched",
        "message": "No matching medicine name was found in the bundled dataset. That does not mean the medicine is invalid or safe; this dataset is incomplete."
    })

@app.route("/api/medicine-search")
def medicine_search():
    q = request.args.get("q", "")
    return jsonify(ENGINE.resolve_name(q))

@app.route("/api/analyze", methods=["POST"])
def analyze():
    payload = request.get_json(silent=True) or {}
    meds = payload.get("medications", [])
    patient = payload.get("patient", {})
    if not isinstance(meds, list) or not meds:
        return jsonify({"error": "Add at least one medicine name.", "alerts": []}), 400
    meds = [str(m).strip() for m in meds if str(m).strip()]
    if len(meds) > 20:
        return jsonify({"error": "Enter up to 20 medicine entries per check.", "alerts": []}), 400
    if not meds:
        return jsonify({"error": "Add at least one medicine name.", "alerts": []}), 400
    try:
        age = int(patient.get("age", 0) or 0)
        egfr_raw = patient.get("egfr", "")
        egfr = float(egfr_raw) if str(egfr_raw).strip() else 0.0
    except (TypeError, ValueError):
        return jsonify({"error": "Age must be a whole number and eGFR must be numeric if provided.", "alerts": []}), 400
    if age < 0 or age > 120:
        return jsonify({"error": "Enter an age between 0 and 120.", "alerts": []}), 400
    if egfr < 0 or egfr > 200:
        return jsonify({"error": "Enter an eGFR between 0 and 200, or leave it blank.", "alerts": []}), 400
    result = ENGINE.analyze(meds, {**patient, "age": age, "egfr": egfr})
    STATS["checks"] += 1
    result["mode"] = "DEMO_ONLY" if DEMO_MODE else "KAGGLE_DATASET_UNVALIDATED"
    if not DEMO_MODE:
        result["dataset_summary"] = DATA.get("source_summary", {})
    return jsonify(result)

@app.route("/api/demo-evaluation")
def demo_evaluation():
    # This intentionally evaluates only a tiny, labelled demonstration fixture.
    # It is NOT the hackathon's hidden-label evaluation.
    truth = [
        {"patient_id":"D1","issues":[("interaction","DEMO_PAIR_A_B")]},
        {"patient_id":"D2","issues":[("duplicate_therapy","DEMO_DUPLICATE")]},
    ]
    predicted = [
        {"patient_id":"D1","issues":[("interaction","DEMO_PAIR_A_B")]},
        {"patient_id":"D2","issues":[("duplicate_therapy","DEMO_DUPLICATE")]},
    ]
    return jsonify({
        "status":"DEMO_FIXTURE_ONLY",
        "note":"These are hand-authored toy fixtures, not benchmark results. Upload the official evaluation data and use the supplied evaluate.py contract before reporting hackathon scores.",
        "metrics":evaluate_predictions(truth, predicted),
        "official_near_miss_recall":None,
        "official_serious_issue_recall":None
    })

@app.route("/api/import-csv", methods=["POST"])
def import_csv():
    """Validate an uploaded CSV schema without silently treating it as authoritative."""
    f = request.files.get("file")
    kind = request.form.get("kind", "")
    required = {
        "medicines": {"generic_name"},
        "interactions": {"drug_a", "drug_b", "severity"},
        "patients": {"patient_id", "age", "medications"},
        "labels": {"patient_id", "issue_type", "drug_or_pair"}
    }
    if not f or kind not in required:
        return jsonify({"error":"Choose a CSV file and a supported data type."}), 400
    try:
        rows = list(csv.DictReader(io.StringIO(f.stream.read().decode("utf-8-sig"))))
    except Exception:
        return jsonify({"error":"Could not read CSV. Save it as UTF-8 CSV and try again."}), 400
    if not rows:
        return jsonify({"error":"CSV has no data rows."}), 400
    missing = required[kind] - set(rows[0].keys())
    if missing:
        return jsonify({"error":"Missing required columns: " + ", ".join(sorted(missing)), "rows_read":len(rows)}), 400
    return jsonify({
        "status":"VALIDATED_NOT_ACTIVATED",
        "kind":kind,
        "rows_read":len(rows),
        "columns":list(rows[0].keys()),
        "message":"Schema looks compatible. This prototype does not activate uploaded clinical references automatically; inspect and map official columns before use."
    })


@app.route("/api/report.pdf", methods=["POST"])
def export_pdf_report():
    """Create a downloadable PDF from the current screening output; no report is stored."""
    payload = request.get_json(silent=True) or {}
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("resolutions"), list) or not isinstance(result.get("alerts"), list):
        return jsonify({"error": "Run the medication checker first, then export its results."}), 400
    if len(result.get("resolutions", [])) > 20 or len(result.get("alerts", [])) > 190:
        return jsonify({"error": "Report contains more entries than this prototype supports."}), 400
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
        from xml.sax.saxutils import escape
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=17*mm, leftMargin=17*mm, topMargin=16*mm, bottomMargin=16*mm, title="MediGuard AI Screening Summary")
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name="SmallText", parent=styles["BodyText"], fontSize=8, leading=10, spaceAfter=3))
        story = [Paragraph("MediGuard AI — Medication Screening Summary", styles["Title"]), Spacer(1, 5*mm)]
        story.append(Paragraph("Educational prototype only. This report is not medical advice and is not proof that a medicine list is safe. Dataset matches are unvalidated screening signals. Ask a pharmacist or prescriber to verify all findings.", styles["BodyText"]))
        story.append(Spacer(1, 4*mm))
        summary = result.get("patient_summary", {}) if isinstance(result.get("patient_summary", {}), dict) else {}
        story.append(Paragraph("Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M") + " · Mode: " + escape(str(result.get("mode", "unknown"))[:80]), styles["SmallText"]))
        story.append(Paragraph("Entries: " + escape(str(summary.get("medication_count", len(result["resolutions"])))) + " · Resolved: " + escape(str(summary.get("resolved_count", "not supplied"))) + " · Alerts: " + str(len(result["alerts"])), styles["SmallText"]))
        story.append(Spacer(1, 3*mm)); story.append(Paragraph("Name resolution", styles["Heading2"]))
        rows = [["Entered name", "Resolved name", "Match status"]]
        for item in result["resolutions"][:20]:
            if isinstance(item, dict): rows.append([Paragraph(escape(str(item.get("input", ""))[:120]), styles["SmallText"]), Paragraph(escape(str(item.get("generic_name", "Unresolved"))[:120]), styles["SmallText"]), Paragraph(escape(str(item.get("status", "unknown"))[:60]), styles["SmallText"])])
        table = Table(rows, colWidths=[48*mm, 65*mm, 45*mm], repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,0),colors.HexColor("#eaf1fb")),("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#11233f")),("GRID",(0,0),(-1,-1),0.4,colors.HexColor("#d0d7e2")),("VALIGN",(0,0),(-1,-1),"TOP"),("PADDING",(0,0),(-1,-1),5)]))
        story.append(table); story.append(Spacer(1, 4*mm)); story.append(Paragraph("Alerts and review prompts", styles["Heading2"]))
        if not result["alerts"]:
            story.append(Paragraph("No issue was found in the rules that ran. This does not establish that the list is safe.", styles["BodyText"]))
        for i, alert in enumerate(result["alerts"][:190], 1):
            if not isinstance(alert, dict): continue
            drugs = alert.get("drugs", [])
            if not isinstance(drugs, list): drugs = []
            content = [Paragraph(f"<b>{i}. {escape(str(alert.get('issue_type','Review item')).replace('_',' '))} — {escape(str(alert.get('severity','REVIEW')))}</b>", styles["BodyText"]), Paragraph("Medicines: " + escape(", ".join(str(x)[:100] for x in drugs[:2])), styles["SmallText"]), Paragraph("Reason: " + escape(str(alert.get("reason", "Not supplied"))[:700]), styles["SmallText"]), Paragraph("Suggested review: " + escape(str(alert.get("suggested_action", "Ask a pharmacist to verify."))[:500]), styles["SmallText"]), Paragraph("Limitations: " + escape(str(alert.get("limitations", "Unvalidated data."))[:500]), styles["SmallText"])]
            story.append(KeepTogether(content)); story.append(Spacer(1, 2*mm))
        doc.build(story); buf.seek(0); STATS["pdf_exports"] += 1
        return send_file(buf, mimetype="application/pdf", as_attachment=True, download_name="mediguard-screening-summary.pdf")
    except ImportError:
        return jsonify({"error": "PDF support is not installed. Run: pip install reportlab"}), 503
    except Exception as exc:
        app.logger.exception("PDF report generation failed")
        return jsonify({"error": "Could not create the PDF report. Please retry."}), 500

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authenticated"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        configured_user = os.environ.get("ADMIN_USERNAME", "admin")
        configured_password = os.environ.get("ADMIN_PASSWORD", "")
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if not configured_password:
            return render_template("admin_login.html", setup_error="Set ADMIN_PASSWORD in Terminal before using the admin dashboard.")
        if secrets.compare_digest(username, configured_user) and secrets.compare_digest(password, configured_password):
            session.clear(); session["admin_authenticated"] = True
            return redirect(url_for("admin_dashboard"))
        return render_template("admin_login.html", setup_error="Username or password was not accepted.")
    return render_template("admin_login.html", setup_error="")

@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.clear()
    return redirect(url_for("admin_login"))

@app.route("/admin")
@admin_required
def admin_dashboard():
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
    ollama_ok = False; models = []
    try:
        with urllib.request.urlopen(base_url + "/api/tags", timeout=2) as response:
            models = [m.get("name", "") for m in json.loads(response.read().decode()).get("models", [])]
        ollama_ok = True
    except Exception:
        pass
    return render_template("admin_dashboard.html", stats=STATS, medicine_count=len(DATA["medicines"]), interaction_count=len(DATA["interactions"]), mode="DEMO ONLY" if DEMO_MODE else "UNVALIDATED KAGGLE DATASET", ollama_ok=ollama_ok, model=model, models=models)

@app.route("/health")
def health():
    return jsonify({"status":"ok", "app":"MediGuard AI", "mode":"DEMO_ONLY" if DEMO_MODE else "KAGGLE_DATASET_UNVALIDATED", "medicines_loaded": len(DATA["medicines"]), "interaction_rows_loaded": len(DATA["interactions"])})

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG", "0") == "1", host="127.0.0.1", port=int(os.environ.get("PORT", "5000")))
