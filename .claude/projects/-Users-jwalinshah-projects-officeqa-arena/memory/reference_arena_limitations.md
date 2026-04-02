---
name: Arena CLI Limitations
description: Known limitations of arena submit that affect file handling
type: reference
---

## Arena Ignores .arenaignore

**The Problem:**
Arena CLI (`arena submit`) completely ignores `.arenaignore` file. Even with comprehensive exclusions listed, the submission includes all files in the directory.

**Why This Matters:**
- Submissions become very large (includes __pycache__, .pyc, results/, data/, etc.)
- Slower upload/deploy times
- Unnecessary bloat in submitted packages

**Workarounds:**
1. Keep repo clean - minimize unnecessary directories at root
2. Only commit essential files
3. Accept that submissions will be large
4. Monitor submission size in arena logs

**For Future Sessions:**
This is a known limitation - can't be fixed from our side. Arena CLI ignores .arenaignore completely.
