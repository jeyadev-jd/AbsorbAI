# AbsorbAI

AbsorbAI is a deterministic drug-food interaction scheduling platform, computationally optimized and evidence-traceable. It helps resolve polypharmacy conflicts before they become pharmacokinetic failures.

## Features

- **Deterministic Rule Engine**: Every interaction rule is explicitly coded from regulatory labels, preventing probabilistic inference.
- **Patient Dashboard**: View a doctor-prescribed schedule, understand medication instructions, set voice reminders, and flag dietary patterns.
- **Doctor Dashboard**: Full clinical controls, PK impact summaries, evidence citations, real-time prescription management, and full interaction matrices.
- **FHIR / ABDM Integration**: Ready for seamless interoperability with hospital EHR systems via FHIR-compliant APIs.

## Setup & Local Development

To run the application locally, you can serve the existing directory using any local web server, for instance:

```bash
python3 -m http.server
```

Then visit `http://localhost:8000/absorbai.html` in your browser.
