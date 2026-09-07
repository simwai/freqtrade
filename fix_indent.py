with open(r'M:\Documents\Programming\Python\freqtrade\user_data\scripts\server.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Fix the indentation around line 280-290
old = 'holds_lock = False\n    if single_flight:\n        if not _REFRESH_LOCK.acquire(blocking=False):\n            with JOB_LOCK:\n                JOBS[job_id]["status"] = "skipped"\n                JOBS[job_id]["finished"] = time.time()\n                # Do NOT clear _REFRESH_JOB_ACTIVE here - the running job still owns it\n            with JOB_LOCK:\n                _log_append_locked(job_id, "\n-- skipped: refresh/report already running --\n")\n            return\n        holds_lock = True'

new = '    holds_lock = False\n    if single_flight:\n        if not _REFRESH_LOCK.acquire(blocking=False):\n            with JOB_LOCK:\n                JOBS[job_id]["status"] = "skipped"\n                JOBS[job_id]["finished"] = time.time()\n                # Do NOT clear _REFRESH_JOB_ACTIVE here - the running job still owns it\n            with JOB_LOCK:\n                _log_append_locked(job_id, "\n-- skipped: refresh/report already running --\n")\n            return\n        holds_lock = True'

if old in content:
    content = content.replace(old, new)
    with open(r'M:\Documents\Programming\Python\freqtrade\user_data\scripts\server.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Fixed')
else:
    print('Not found')
    # Find the actual content
    idx = content.find('holds_lock = False')
    if idx >= 0:
        print('Found at:', idx)
        print(repr(content[idx:idx+300]))