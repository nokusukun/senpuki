# Gemini Agent Documentation Guidelines

This document outlines the conventions for the Gemini agent when creating documentation for new features or significant changes.

## Feature Documentation

For each new feature or significant update, the agent **must** create a new Markdown file in the `./features` directory.

### Naming Convention

Files should be named with an incrementing three-digit number, followed by a hyphen, and then a concise, hyphen-separated description of the feature, all in lowercase.

**Format:** `XXX-feature-description.md`
*   `XXX`: An incrementing three-digit number (e.g., `001`, `002`, `010`). The agent is responsible for determining the next available number.
*   `feature-description`: A short, descriptive phrase using hyphens instead of spaces.

**Example:**
*   `./features/001-task-leases.md`
*   `./features/002-database-cleanup.md`

### Content Format

Each Markdown file should be concise and provide a clear overview of the feature.

**Required Sections:**

1.  **Feature Name:** A clear, human-readable title for the feature.
2.  **Description:** A brief explanation of what the feature does and why it was implemented.
3.  **Key Changes:** A summary of the main components or files affected by the change.
4.  **Usage/Configuration (if applicable):** How to use or configure the new feature, including code examples if relevant.

### Example File Structure

```markdown
# [Feature Name]

## Description
[Brief explanation of the feature and its purpose.]

## Key Changes
*   [List of major files/components modified or added]
*   [Brief description of changes in each]

## Usage/Configuration
```python
# [Relevant code example or configuration details]
```
