# Synthetic data policy

The project generator is deterministic and uses only synthetic scenario templates, fictional names, and reserved `example.com` email addresses. It does not call an LLM. Do not add real company, college, employee, or personal data. The gold labels are a held-out evaluation asset: do not ingest them, use them in prompts, or tune thresholds against them before the scheduled final evaluation.

Before the data is considered final, a human reviewer must inspect every scenario in `data/scenarios.json`, correct technical details and routing, and set its `review_status` to `approved_by_user`. The generator preserves these approvals when rerun.
