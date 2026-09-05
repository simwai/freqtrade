#!/usr/bin/env python3
"""
Fix for frequi dashboard: Strategy Lab trade map not rendering on direct URL access
with #s=StrategyName hash parameter.
"""

import re
from pathlib import Path

JS_FILE = Path("freqtrade/rpc/api_server/ui/installed/assets/index-wxgNlDZx.js")

# The fix code to inject - waits for LAB data before calling openStrategy
FIX_CODE = """
;(function(){'use strict';function applyFromHashWithRetry(){const h=decodeURIComponent((location.hash||'').replace(/^#/,''));if(h.startsWith('s=')){const name=h.slice(2);console.log('[StrategyLab Fix] Hash strategy:',name);waitForLabData(name);}else{const tab=h.startsWith('t=')?h.slice(2):'dashboard';if(typeof showTab==='function')showTab(tab,true);}}function waitForLabData(name,maxAttempts=50){let attempts=0;const check=()=>{if(window.LAB&&window.LAB.canonical&&window.LAB.canonical.length>0){console.log('[StrategyLab Fix] LAB data ready, opening strategy');if(typeof openStrategy==='function')openStrategy(name,true);return true}attempts++;if(attempts>=maxAttempts){console.warn('[StrategyLab Fix] LAB data not ready after',maxAttempts,'attempts');if(typeof openStrategy==='function')openStrategy(name,true);return true}setTimeout(check,100);return false};check()}document.addEventListener('DOMContentLoaded',applyFromHashWithRetry);window.addEventListener('hashchange',applyFromHashWithRetry);})();
"""

def apply_fix():
    if not JS_FILE.exists():
        print(f"Error: {JS_FILE} not found")
        return False
    
    content = JS_FILE.read_text(encoding='utf-8')
    
    # Check if fix already applied
    if 'StrategyLab Fix' in content:
        print("Fix already applied!")
        return True
    
    # Find the end of the file where init();applyFromHash(); is called
    # Pattern: init();applyFromHash();
    pattern = r'(init\(\);applyFromHash\(\);)'
    match = re.search(pattern, content)
    
    if not match:
        # Try alternative patterns
        alt_patterns = [
            r'(init\(\);\s*applyFromHash\(\);)',
            r'(applyFromHash\(\);)',
        ]
        for p in alt_patterns:
            match = re.search(p, content)
            if match:
                print(f"Found alternative pattern: {match.group(1)[:50]}...")
                break
    
    if not match:
        print("Could not find init/applyFromHash call. Searching for 'init' function end...")
        # Find the last occurrence of 'init()' followed by 'applyFromHash'
        # The file is minified, so look for the end
        idx = content.rfind('applyFromHash()')
        if idx >= 0:
            # Find the semicolon after it
            end_idx = content.find(';', idx)
            if end_idx >= 0:
                old_call = content[idx:end_idx+1]
                print(f"Found at end: {old_call}")
                new_content = content[:end_idx+1] + FIX_CODE + content[end_idx+1:]
                JS_FILE.write_text(new_content, encoding='utf-8')
                print("Fix appended at end of file")
                return True
    
    if match:
        old_call = match.group(1)
        new_call = old_call + FIX_CODE
        new_content = content.replace(old_call, new_call, 1)
        JS_FILE.write_text(new_content, encoding='utf-8')
        print(f"Fix applied, replaced: {old_call[:50]}...")
        return True
    
    print("Could not find suitable insertion point")
    return False

if __name__ == '__main__':
    apply_fix()