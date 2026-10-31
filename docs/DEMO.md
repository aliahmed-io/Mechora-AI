# Mechora AI course and portfolio demonstration

Mechora is a functioning research showcase. The main story is **import → predict → investigate → explain → report**. No login or production setup is required.

## Start

From the project folder, start the backend and frontend in separate terminals as documented in `README.md`. Open `http://127.0.0.1:3000`. The dataset, trained model, fonts, and machine image are stored locally.

## Five-minute presentation

1. Introduce the landing page and the goal: understanding operating observations and estimating a machine-failure label.
2. Select **Analyze equipment**, then **Use sample dataset**. Explain the six feature columns and that failure outcomes are excluded from prediction inputs.
3. Review the validated preview and select **Run analysis**. The dashboard shows real model probabilities for the 2,000 held-out feature rows.
4. Open **Equipment records**, filter by **High**, and inspect a record. Explain the measurements and median replacement sensitivity. The explanation describes the model, not a proven cause of failure.
5. Switch to **Single observation**, run a what-if prediction, and change a measurement. The previous result disappears until the new conditions are analyzed. Switch back to the saved observation to restore its original result.
6. Open **Risk analysis**. Adjust the watch and high boundaries. Saving creates a new batch without overwriting the previous results. The precision/recall tradeoff belongs to the validation set, not your uploaded file.
7. Open **Model laboratory**. Explain the three algorithms, training-only preprocessing, validation-only selection, and separate final test results.
8. Open **Reports** and generate a PDF, then download the full CSV. The PDF includes saved model information, risk boundaries, evaluation context, and the highest-risk observations.

## Honest evaluation talking points

- Data is synthetic UCI AI4I 2020. The model is a classifier, not a time-to-failure estimator.
- The reproducible stratified split is 6,000 training / 2,000 validation / 2,000 test, seed 42.
- HistGradientBoosting was selected by validation average precision. Its current test precision, recall, and F1 are each 0.7647; ROC-AUC is 0.9716 and average precision is 0.8254.
- The classifier probabilities are not post-hoc calibrated. Do not describe a percentage as a proven industrial failure frequency.
- Saved analyses identify the exact model artifact. Explanations use that archived model, even after later retraining.
- No downtime savings, component fault localization, equipment histories, or live sensors are claimed.

## Recheck before presenting

```powershell
.\.venv-win\Scripts\python.exe -m pytest backend\tests -q
.\.venv-win\Scripts\python.exe scripts\verify_model.py
npm run typecheck
npm run build
# With both services running:
.\.venv-win\Scripts\python.exe scripts\e2e.py
.\.venv-win\Scripts\python.exe scripts\showcase_check.py
```

The browser checks create clearly named sample/demo batches and save screenshots/downloads under `output/qa/`. They preserve previously saved analyses.

## Equipment and maintenance extension

Open **Machines & replay**, select **Load sample & create replay**, then step through observations or start playback. Explain that the machine ID and clock are explicitly simulated for this demonstration, while the underlying row measurements and model calculations are genuine.

Open a reading's **Diagnostics** view to compare L/M/H product-type predictions, then select **Flag for inspection**. In **Maintenance**, add findings and resolve the investigation with an outcome. Replay outcomes are excluded from confirmed-label export.

To demonstrate a real data path, use a timestamped CSV or the saved-reading API. The optional MQTT and OPC UA adapters can connect to supplied endpoints. At the bottom of **Model laboratory**, demonstrate training on labeled data using time or machine holdouts, inspect the results, explicitly activate a candidate, and restore the benchmark when finished. See `docs/INTEGRATIONS.md` for commands and data requirements.
