# Generate the interactive Archify artifact

The repository audit and Mermaid draft are already in this branch. The actual Archify renderer must run in a local environment with Node.js and Codex CLI because this ChatGPT session cannot execute the Archify CLI against a checked-out working tree.

## 1. Check out this branch

```bash
git fetch origin
git checkout docs/gativa-architecture-audit
```

## 2. Install Archify for Codex in this repository

From the Gativa repository root:

```bash
npx -y skills add tt-a1i/archify --skill archify --agent codex --copy --yes
```

This installs the agent skill; it should not add Archify as an application runtime dependency.

## 3. Run this prompt in Codex CLI

```text
Use the installed Archify skill to inspect this repository at the current checked-out commit and generate a source-backed interactive architecture diagram for Gativa.

Read docs/architecture/README.md and docs/architecture/architecture.mmd as review context, but independently verify all edges and claims against the actual source. Do not treat the README or Mermaid draft as proof.

Requirements:
- Use Archify's typed JSON architecture format and renderer. Do not substitute a hand-written HTML file or Mermaid rendering for the Archify artifact.
- Keep the diagram at 8–12 core components for the high-level view. Use focused workflow/sequence/dataflow diagrams only if Archify supports them as separate artifacts and they materially improve understanding.
- Include the primary user journey: polygon selection → POST /api/analyses → analysis orchestration → OSM/traffic/weather ingestion → persisted analysis → dashboard → simulation prepare/run → comparison/congestion telemetry.
- Include external providers, persistence boundaries, native SUMO/TraCI runtime dependency, and fallback/unavailable modes only where source proves them.
- Attach revision-pinned source references and line ranges only when Archify can verify the checked-out Git origin, commit, file blobs, and lines. Do not fabricate citations.
- Distinguish source-verified components from runtime-dependent integrations and unresolved inference paths.
- Explicitly represent the ML inference call path as unknown until the full source proves it.
- Inspect the road-network fallback and storage fallback paths; document any discrepancy rather than silently resolving it by assumption.
- Retain Archify's editable typed JSON source, the self-contained interactive HTML, and any validation receipt in docs/architecture/.
- Use Archify's validate/deliver workflow and require successful validation. If validation fails, report the exact diagnostics and do not claim success.
- Do not overwrite any existing files. Use new distinct filenames if the target paths already exist.
- Do not modify application code, UI, dependencies, package manifests, environment files, or runtime configuration.
- After generation, list the files created, validation status, source commit SHA, and any claims that remain unverified.
```

## 4. Validate before committing

Inspect the diff. Confirm that only new files under `docs/architecture/` changed. Run the Archify validation/delivery command documented by the installed skill, and preserve its JSON receipt. Do not mark the diagram as source-validated unless the Archify validator reports success.

## Reference

Archify project and installation instructions: https://github.com/tt-a1i/archify
