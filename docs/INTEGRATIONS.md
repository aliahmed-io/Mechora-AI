# Connecting Mechora to equipment and maintenance work

The application now supports timestamped equipment histories, recorded-data replay, persisted connector measurements, investigation notes and outcomes, product-type comparisons, and training on supplied labeled data. The original UCI benchmark remains available. These are working software paths; a physical factory connection still requires an actual endpoint, a measurement mapping, and representative labeled data.

## Machines and imported history

Open **Machines & replay** to register a machine by its actual identifier, name, and location. IDs are stable identifiers such as `CNC-01`; they are not prediction features.

The existing inference CSV supports two optional context columns:

```csv
Type,Air temperature [K],Process temperature [K],Rotational speed [rpm],Torque [Nm],Tool wear [min],machine_id,observed_at
M,298.1,308.6,1551,42.8,0,CNC-01,2026-10-31T09:00:00Z
M,298.2,308.7,1500,45.0,3,CNC-01,2026-10-31T09:01:00Z
```

These are illustrative format examples. Supply both context columns or neither. `Machine ID` and `Timestamp` are also accepted aliases. Timestamps must include a timezone. Running the imported analysis saves the readings to the machine timeline. Reanalyzing identical measurements does not create duplicate history entries. The original CSV workflow still works without machine context; it does not fabricate equipment identities or histories.

The machine page shows recent observations, source, model version, latest probability and risk category, and selectable trends for failure estimate, process temperature, rotational speed, torque, and tool usage. It refreshes while open. The chart shows up to 200 recent readings; the timeline lists the latest 30. The API supports up to 1,000 recent readings per request.

## Recorded-data replay

In **Machines & replay**, choose an imported dataset and select **New replay**, or use **Load sample & create replay**. Controls support start, pause, one-observation stepping, playback speed, and restoring a saved replay after navigation.

Each replay has a separate `REPLAY-...` demonstration machine. The original row measurements are preserved, but observation timestamps use a clearly labeled simulated clock at one-minute intervals. Playback speed controls how quickly rows are processed, not the simulated interval between measurements. This is historical/synthetic data replay, not a live sensor feed or a validated chronological reconstruction of the source dataset.

Replay runs on the backend and continues when navigating between pages. A backend restart pauses interrupted replay runs. A new replay starts from the beginning without deleting a previous run. Replayed observations and their maintenance outcomes are excluded from the confirmed-outcome training export.

## Saved measurement API

`POST /api/ingestion/readings` accepts the six operating features plus machine/time context and returns a persisted reading with its prediction. For example:

```json
{
  "machine_id": "CNC-01",
  "observed_at": "2026-10-31T09:00:00Z",
  "type": "M",
  "air_temperature": 298.1,
  "process_temperature": 308.6,
  "rotational_speed": 1551,
  "torque": 42.8,
  "tool_wear": 20,
  "external_id": "controller-observation-0001"
}
```

The values above illustrate the request shape; they are not a claimed factory observation. The optional external ID deduplicates retries for that machine and source. Reusing the ID for different measurements returns an error rather than silently replacing a saved observation. Product type is L/M/H quality variant, temperatures are Kelvin, speed is rpm, torque is Nm, and tool wear is minutes of tool usage. Do not substitute motor age for tool usage or map arbitrary machine categories to L/M/H.

Other useful endpoints:

- `GET /api/machines`: equipment register, latest reading, counts, and open investigations.
- `GET /api/machines/{id}/readings`: timestamped history.
- `GET /api/readings/{id}`: saved prediction and its original-model explanation.
- `POST /api/machines`: register or update the display name/location of an equipment ID.

Interactive request schemas are at `http://127.0.0.1:8001/docs`.

## CSV, MQTT, and OPC UA adapters

The connector is `scripts/connector.py`. It sends actual supplied measurements into the saved-reading endpoint. It does not generate missing measurements or silently invent observation times.

CSV forwarding works with the core Python dependencies:

```powershell
.\.venv-win\Scripts\python.exe scripts\connector.py csv path\to\timestamped-observations.csv
```

Install optional protocol adapters:

```powershell
.\.venv-win\Scripts\python.exe -m pip install -r backend\requirements-connectors.txt
```

MQTT subscribes to a supplied broker/topic. Messages must contain JSON in the saved-reading request shape:

```powershell
.\.venv-win\Scripts\python.exe scripts\connector.py mqtt --host 127.0.0.1 --port 1883 --topic factory/cnc01/observations
```

OPC UA reads the five numeric measurements from your configured server nodes. Copy `docs/opcua-nodes.example.json`, replace every example node ID with the actual equipment node IDs, and run:

```powershell
.\.venv-win\Scripts\python.exe scripts\connector.py opcua --url opc.tcp://127.0.0.1:4840 --nodes docs\my-machine-nodes.json --machine-id CNC-01 --product-type M --interval 2
```

OPC UA timestamps each acquired set of readings at collection time in UTC. Product type can be a configured process variant or a mapped OPC UA node. Use `--count 2` for a short connection check. The sample node map alone is not a real server connection. The supplied adapters target directly accessible endpoints; factory-specific credentials and endpoint policies require configuration appropriate to that installation.

For sensors reporting Celsius, put `--temperature-unit C` before the adapter subcommand. Use short temperature names (`air_temperature`, `process_temperature`) in Celsius data; columns explicitly labeled `[K]` cannot be converted again. The connector adds 273.15 before sending temperatures to inference.

```powershell
.\.venv-win\Scripts\python.exe scripts\connector.py --temperature-unit C csv measurements-in-celsius.csv
```

## Maintenance investigations and outcomes

Open a saved batch observation or machine reading in **Diagnostics**, then select **Flag for inspection**. **Maintenance** records the original measurements and prediction, an inspection title, notes, status changes, and a human-entered outcome. An existing open investigation is reused if the same observation is flagged twice.

Statuses are Open, In progress, and Resolved. Resolving requires an outcome and an inspection note. Outcomes include confirmed failure, no fault found, maintenance performed, and inconclusive. A full note/status timeline remains available. Reopening an investigation clears its resolution timestamp without deleting the previous timeline entries.

**Export confirmed outcomes** produces the six features, available machine/time context, and a `Machine failure` label. Only resolved, non-replay cases marked **confirmed failure (1)** or **no fault found (0)** are included. Preventive maintenance and inconclusive findings are not automatically labeled as failure or normal. Human-entered labels still require evidence; the export does not certify their accuracy.

## Product-type comparison

Diagnostics now shows the trained model's prediction for L, M, and H with all five numeric measurements held fixed. The observed variant is marked. Differences are shown in percentage points relative to the original prediction. This is a model sensitivity comparison, not a causal claim or an instruction to change the product variant.

## Train and evaluate supplied equipment data

At the bottom of **Model laboratory**, upload a CSV with the six features plus a confirmed `Machine failure` column containing 0/1. The equipment/context schema above is supported. Training requires at least 100 records, at least 10 records of each outcome, and at least 10 rows plus both outcome classes in each split. These are computational minimums, not proof of sufficient data for a real installation.

Choose the evaluation strategy:

- **Later observations (temporal):** orders the unique supplied timestamps, uses the earliest approximately 60% for training, the next 20% for validation, and the latest 20% for test. Equal timestamps are kept in the same partition. At least 10 distinct timestamps are required.
- **Different machines:** uses disjoint machine groups for training, validation, and test. At least five machines are required. Both outcomes must exist in every resulting partition; the service refuses an invalid split rather than quietly changing the strategy.
- **Stratified random benchmark:** uses the original 60/20/20 seed-42 approach, useful for benchmark comparisons when time or machine holdout is unavailable. It does not establish temporal or cross-machine generalization.

All strategies train Logistic Regression, Random Forest, and HistGradientBoosting with preprocessing fitted only on training rows. Model selection uses validation average precision, and the classification boundary maximizes validation F1. The selected model is evaluated on the separate test partition. No target outcomes, machine identifiers, or timestamps enter the predictor. The split audit and complete metrics are saved with the candidate.

Training runs in the background; its status, progress, validation comparisons, and selected-model test scores appear in the laboratory. A failed run displays its reason. An interrupted backend restart marks unfinished training as failed so it can be rerun.

Select **Use this trained model** to apply a completed candidate to new predictions. Previous analyses retain their archived model and explanations. **Previously used models** lets you restore the benchmark or another archived model. Candidate files and labels are stored in ignored `artifacts/experiments/`; original models remain in `artifacts/models/`. Back up these folders with `backend/data/mechora.db`.

Training on a file does not independently prove that the file came from physical equipment. Use authentic outcome records for real-world studies. The browser integration check uses explicitly synthetic demonstration records, restores the original benchmark afterward, and makes no claim of factory validation.

## Verification

```powershell
.\.venv-win\Scripts\python.exe -m pytest backend\tests -q
.\.venv-win\Scripts\python.exe scripts\integration_check.py
```

Optional real-protocol checks use temporary local simulated sources:

```powershell
.\.venv-win\Scripts\python.exe -m pip install -r backend\requirements-connectors.txt amqtt
.\.venv-win\Scripts\python.exe scripts\check_connectors.py
```

The protocol checks exercise actual OPC UA reads, MQTT subscription delivery, HTTP inference/persistence, and idempotent MQTT redelivery. No physical machine or remote factory server is contacted.

Recorded verification: 37 backend tests passed; the original browser workflow and the equipment-integration workflow passed with zero JavaScript page errors. The integration walkthrough covered context import, machine history, L/M/H comparison, maintenance resolution and label export, replay, temporal candidate training, activation, benchmark restoration, and desktop/tablet/mobile layouts. The local OPC UA and MQTT protocol checks also passed.
