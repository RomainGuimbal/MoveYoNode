# MoveYoNode — Node Group Management Tool

## Perseverance
Stop fast, ask. If a task needs a large refactor or you are missing info, stop
and ask — never guess or persist on a failing approach. Never pretend to know.

## Purpose
Management add-on for moving Blender node groups between files of the same
project. Linked data must stay valid and the dependency hierarchy preserved.

## Blender
Blender 5.3. Every invocation: `--factory-startup`, plus
`bpy.context.preferences.use_preferences_save = False`. Never the GUI, never
no flags, never `--background` alone.

## Stay inside the repo
Inside the repo, read/search/write/run freely, no permission needed.

**Outside the repo, exactly one thing is allowed: the Blender executable. One
path, one file, nothing around it. No outside reads — not even a listing.**

- Fine: running `blender` from `PATH`, or a path the user gave you.
- Never: `ls`, `stat`, `cat`, `grep`, `find`, `glob`, `test -e` outside the repo.
- Never: checking whether Blender exists, which versions are installed, or
  resolving/confirming a path. Need the path? Ask.
- A file outside becomes readable only if the user pastes its contents.
- `MYN_BLENDER` supplies the path. No machine-specific path in committed code,
  and the runner must not search the filesystem.
- `sys.path`: only `src/` (computed from `__file__`) and the repo root. Nothing
  above the repo root.
- Scratch files go in `.probes/` at the repo root, deleted when done.

## Never touch the user's Blender config
Preferences, startup file, addons, keymaps and themes are personal data.
Never read, list or stat the config folder (`%APPDATA%\Blender Foundation\`,
`~/.config/blender/`, `~/Library/Application Support/Blender/`, anything holding
`userpref.blend` or `startup.blend`) — on any pretext, even to diagnose a bug
the user reports. Never `save_userpref()`, never `save_homefile()`, never
install/enable/remove an addon. Test artifacts go in a temp dir.

If the user reports a settings problem: say every command used
`--factory-startup`, which never saves preferences, suggest they check
Preferences → Add-ons, then stop. Ask them to paste what you need — do not
go looking.

## Honesty and loops
- Never say "I could not have caused this" without grepping your own log for
  the commands you actually ran. Otherwise: "I don't know".
- A command that fails or is denied gets at most one retry. Then report and ask.
  Re-running identical calls is a bug, not persistence.
