# Codex repository instructions

## Product goal
Build and maintain a lightweight CRM for graphite recarburizer sales. The core concept is a sales funnel with auditable stage transitions.

## Non-negotiable requirements
- UI language: Simplified Chinese.
- Preserve manual data-entry workflows; never require demo data.
- Keep all data schemas backward compatible or provide migrations.
- Never commit secrets, tokens, private keys, or real customer data to a public repository.
- Data write operations must fail safely and display actionable errors.
- Every stage change must append a stage_history record.
- Do not calculate a conversion rate from snapshot counts without labelling it as an approximation.
- Add or update tests for storage and scoring logic.

## Architecture
- Streamlit frontend in app.py.
- Domain helpers under src/.
- Stage configuration in config/stages.yaml.
- Lead scoring model configuration in models/lead_score.json.
- JSON persistence in data/ with local and GitHub Contents API backends.

## Definition of done
- `pytest -q` passes.
- `streamlit run app.py` starts without demo data.
- Local mode can create, edit, follow up, change stage, create order, and export data.
- GitHub mode reads and writes the configured data branch using secrets.
- README deployment instructions stay current.
