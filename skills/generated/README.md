# Generated Skills — Constitution

This directory contains skills written at runtime by agents using the `write_skill` tool.

## What agents MAY write

- Step-by-step workflow instructions for recurring tasks (e.g. "how to format a monthly expense report")
- Checklists and procedural guides derived from user instructions
- Domain-specific terminology or abbreviation glossaries
- Prompt templates and output format specifications
- Integration guides for external services (API endpoints, data shapes, field mappings)
- Corrected `gws` skill overrides using the **exact same name** as the base skill (e.g. `gws-gmail`) when the agent has verified the base skill is stale via fresh `gws --help` output; shell command examples in code blocks are permitted as reference documentation

## What agents MUST NOT write

- Executable Python scripts or arbitrary shell scripts intended to run on the host system (gws CLI commands in code blocks as reference docs are fine)
- Instructions that reference or expose API keys, credentials, or secrets
- Skills that contradict existing skills in `skills/` without a verified reason (e.g. confirmed via `gws --help` that the base skill is stale)
- Skills containing harmful, deceptive, or policy-violating content
- Skills with names that collide with core system files

## Naming convention

Skill names must be lowercase, hyphen-separated slugs: `my-skill-name`.
Descriptions must be a single sentence summarizing what the skill does.

## Lifecycle

Generated skills persist across sessions and are immediately searchable via `search_skills`.
They can be overwritten by calling `write_skill` again with the same name.
Stale or incorrect skills should be reported to the user for manual deletion.
