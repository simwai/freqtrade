import re

with open(r'M:\Documents\Programming\Python\freqtrade\user_data\scripts\build_report.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the exact section
idx = content.find('Dry run (local)')
if idx >= 0:
    section = content[idx:idx+2000]
    print('Found section:')
    print(repr(section[:800]))

# The issue is the em dash — and the HTML entities < >
# Let me match more loosely
idx2 = content.find('start a detached freqtrade trade process')
if idx2 >= 0:
    print('Found hint at:', idx2)
    print(repr(content[idx2:idx2+100]))