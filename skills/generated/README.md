# Generated Skills — Constitution

This directory contains skills written at runtime by agents using the `write_skill` tool.

## What agents MAY write

- Step-by-step workflow instructions for recurring tasks (e.g. "how to format a monthly expense report")
- Checklists and procedural guides derived from user instructions
- Domain-specific terminology or abbreviation glossaries
- Prompt templates and output format specifications
- Integration guides for external services (API endpoints, data shapes, field mappings)

## What agents MUST NOT write

- Executable code or shell commands intended to run on the host system
- Instructions that reference or expose API keys, credentials, or secrets
- Skills that override or contradict existing skills in `skills/` (use `search_skills` first)
- Skills containing harmful, deceptive, or policy-violating content
- Skills with names that collide with core system files

## Naming convention

Skill names must be lowercase, hyphen-separated slugs: `my-skill-name`.
Descriptions must be a single sentence summarizing what the skill does.

## Lifecycle

Generated skills persist across sessions and are immediately searchable via `search_skills`.
They can be overwritten by calling `write_skill` again with the same name.
Stale or incorrect skills should be reported to the user for manual deletion.
