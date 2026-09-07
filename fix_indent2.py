with open(r'M:\Documents\Programming\Python\freqtrade\user_data\scripts\server.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Fix line 1047 - should be indented with 8 spaces
lines[1046] = '        if path == "/api/report":\n'

with open(r'M:\Documents\Programming\Python\freqtrade\user_data\scripts\server.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print('Fixed line 1047')