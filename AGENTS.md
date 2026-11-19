# MoveYoNode — Node Group Management Tool

## Perseverance Policy: Stop Fast, ask for validation
Do not persist on issue. Give up and terminate answer if the task is complexe.
Stop when the task is requiering large refactor. Do not make them if not explicitly told.
If you miss any info, ask for it. Never pretend you know.

## Purpose
This addon is a **management tool** for moving and organizing Blender node groups between files of the same project. It is essential that blend files' linked data stays valid and preserve dependency hierarchy.

## Blender
This addon is for Blender 5.3
if you need to run blender, ALWAYS do it with "bpy.context.preferences.use_preferences_save = False"

## NEVER TOUCH THE USER'S BLENDER INSTALLATION OR CONFIG

The user's Blender preferences, startup file, addons, keymaps and themes are
**personal data, not project data**. Losing them costs the user hours of work.

### This already happened once. Do not repeat it.

A previous agent ran:

    blender.exe --background --python-expr "import bpy; p = bpy.context.preferences; ..."

**without `--factory-startup`.** `--background` alone still loads the real user
profile, and Blender writes `userpref.blend` back on exit. The user's
preferences were damaged and they lost an hour recovering them. The agent then
told the user three times that it "could not have caused it" — without ever
checking its own log. That false reassurance was worse than the original
mistake.

### Hard rules

1. **Every Blender invocation MUST include `--factory-startup`.** No exceptions.
   `--background` is not enough. Never launch the GUI. Never launch Blender
   with no flags. If you are unsure whether a flag is safe, do not run it.
2. **NEVER ACCESS THE PREFERENCES FOLDER. EVER. NO EXCEPTIONS.**
   Do not `ls`, `stat`, `cat`, `grep`, `find`, `cp`, `mv`, `rm`, `touch` or
   open anything under the user's Blender preferences/config folder. Do not
   check timestamps. Do not "verify" a file exists. Do not look at it to
   diagnose a bug. Do not look at it because the user mentioned it. Do not
   look at it because you are curious. **The folder is off limits, full stop.**
   This covers, on every platform:
   - `%APPDATA%\Blender Foundation\Blender\<version>\config\`
   - `%APPDATA%\Blender Foundation\Blender\<version>\` (any subfolder)
   - `~/.config/blender/<version>/`
   - `~/Library/Application Support/Blender/<version>/`
   - any path containing `userpref.blend`, `startup.blend`, `bookmarks.txt`,
     `recent-files.txt`, `recents.toml`, `platform_support.txt`, or a
     `config/` or `extensions/` directory belonging to Blender.

   If you believe you need to look there, **you are wrong**. Ask the user to
   paste what you need, or find another way. There is no legitimate reason for
   this agent to read that folder.
3. **Never call `bpy.ops.wm.save_userpref()` or `bpy.ops.wm.save_homefile()`.**
   Never set `use_preferences_save = True`. Never assign to
   `bpy.context.preferences.*` outside a throwaway `--factory-startup` process.
4. **Never install, enable, disable or remove an addon or extension** in the
   user's Blender. Test addons by adding the repo to `sys.path` inside a
   `--factory-startup` process, or by pointing `BLENDER_USER_CONFIG` and
   `BLENDER_USER_SCRIPTS` at a temp directory.
5. **All test artifacts go in a temp directory** created by the test harness.
   Never write `.blend` files, logs or caches into the user's Blender folders.

### If the user reports a Blender settings problem

Do **not** go investigate their config directory. Do **not** run Blender
against their profile to "check". Say this instead, in one or two sentences:
every command you ran used `--factory-startup`, which never saves preferences,
so you do not believe you caused it — and they should check Preferences →
Add-ons themselves. Then stop and wait. If they ask you to help recover, ask
them to paste the directory listing. Do not go looking yourself.

### Never claim innocence without checking

Before telling the user "I could not have caused this", **grep your own session
log for the actual commands you ran.** An unverified denial is a lie, even when
it is well-intentioned. If you cannot verify, say "I don't know" instead.

### Never loop

If a command fails, is denied, or returns nothing useful: **stop after one
retry**. Do not re-run the same command repeatedly hoping for a different
result. Report the failure and ask. Twenty identical calls in a row is a bug in
your behavior, not persistence.

### Stay inside
Never work outside of project directory. 
Inside it however, you don't ask for permission to read or write little things.    

## NEVER REFERENCE PATHS OUTSIDE THE PROJECT

The project directory is the repo root. **Nothing outside it may be named,
hardcoded, or reached for.** The user's home folder, Documents, Desktop,
Downloads, other projects, and any absolute path above the repo root are off
limits — not to read, not to write, not to mention in code, not to mention in
a command.

### Hard rules

1. **No absolute paths in the codebase.** Never hardcode `C:\Users\...`,
   `/home/...`, or any path that only exists on this machine. Derive paths from
   `__file__` at runtime instead. If you catch yourself typing a drive letter
   or a home directory into a file, stop.
2. **No `sys.path` entries pointing above the repo root.** The addon lives at
   `src/move_yo_node/`, so `src/` is the import root. That is the only path
   that ever goes on `sys.path`, and it is computed from `__file__`.
3. **Never `cd`, `ls`, `find`, `grep`, `cat` or otherwise touch a directory
   above the repo root.** If a task seems to need it, you are wrong — ask.
4. **Scratch files go in `.probes/` at the repo root**, which is gitignored.
   Probes are throwaway Blender scripts that answer one question and get
   deleted. Keeping them inside the repo means the user can see exactly what
   was run. Never write scratch into a sibling folder or above the repo root.
   Delete `.probes/` when the investigation is done.
5. **This is a hard rule, not a preference.** The user has sensitive data
   outside the project and does not want this agent to have access to it. A
   path that "looks harmless" is still out of bounds.

### Why

A previous session put the repo's parent folder on `sys.path` so that
`import MoveYoNode` would resolve. That was technically necessary at the time,
but it meant the agent held a handle on a directory the user considers private.
The fix was structural: the addon moved to `src/move_yo_node/`, so the import
root is now inside the repo and no outside path is ever needed. Do not undo
that.
