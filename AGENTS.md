# MoveYoNode — Node Group Management Tool
## Perseverance Policy: Fail Fast

**Stop and report failure immediately. Do not loop indefinitely.**

When encountering an error, failure, or unexpected state:

1. **Diagnose** — Identify the root cause (missing dependency, bad argument, corrupted file, etc.)
2. **Report** — Clearly state what failed and why.
3. **Stop** — Do not retry the same failing operation endlessly.
4. **Pivot or Abort** — Either suggest a workaround, ask for clarification, or abort the task.

**Common failure signals to respect:**
- Missing file / broken import
- Invalid argument / configuration
- Missing dependency / environment issue
- Blender crash or background task failure
- Timeout or resource exhaustion

**Better to fail fast and inform than to spin forever.**

## Purpose

This addon is a **management tool** for moving Blender node groups between files while **preserving external links** and avoiding dependency issues.

## Blender
This addon is for Blender 5.3
Note : GeometryNodes is not a python package but a built-in module of Blender.
