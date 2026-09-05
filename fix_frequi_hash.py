#!/usr/bin/env python3
"""
Fix for frequi dashboard: Strategy Lab trade map not rendering on direct URL access
with #s=StrategyName hash parameter.

The issue: applyFromHash() is called in init() but LAB data is loaded asynchronously.
When openStrategy runs from hash, LAB.canonical, LAB.backtests, etc. are empty.

Fix: Wait for initial data load before calling applyFromHash, or make openStrategy
retry until data is available.
"""

import re
from pathlib import Path

JS_FILE = Path("freqtrade/rpc/api_server/ui/installed/assets/index-FbHqpW1i.js")

def apply_fix():
    if not JS_FILE.exists():
        print(f"Error: {JS_FILE} not found")
        return False
    
    content = JS_FILE.read_text(encoding='utf-8')
    
    # Check if fix already applied
    if 'StrategyLab Hash Fix' in content:
        print("Fix already applied!")
        return True
    
    # Find the init function and the applyFromHash call
    # The pattern is: init();applyFromHash();
    # We need to modify this to wait for data before calling applyFromHash
    
    # First, let's find where the LAB data loading happens
    # The key is that renderLab() fetches /api/strategies and populates LAB
    
    # Strategy: Add a wrapper that waits for LAB.canonical to be populated
    # before calling applyFromHash
    
    FIX_CODE = """
;(function(){'use strict';function applyFromHashWithRetry(){const h=decodeURIComponent((location.hash||'').replace(/^#/,''));if(h.startsWith('s=')){const name=h.slice(2);console.log('[StrategyLab Fix] Hash strategy:',name);waitForLabData(name);}else{const tab=h.startsWith('t=')?h.slice(2):'dashboard';if(typeof showTab==='function')showTab(tab,true);}}function waitForLabData(name,maxAttempts=50){let attempts=0;const check=()=>{if(window.LAB&&window.LAB.canonical&&window.LAB.canonical.length>0){console.log('[StrategyLab Fix] LAB data ready, opening strategy');if(typeof openStrategy==='function')openStrategy(name,true);return true}attempts++;if(attempts>=maxAttempts){console.warn('[StrategyLab Fix] LAB data not ready after',maxAttempts,'attempts');if(typeof openStrategy==='function')openStrategy(name,true);return true}setTimeout(check,100);return false};check()}document.addEventListener('DOMContentLoaded',applyFromHashWithRetry);window.addEventListener('hashchange',applyFromHashWithRetry);})();
"""
    
    # Find the end of the script where init();applyFromHash(); is called
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
                print(f"Found alternative pattern: {match.group(1)}")
                break
    
    if not match:
        print("Could not find init/applyFromHash call. Searching for init function...")
        # Find the init function end
        init_match = re.search(r'function init\(\)\{.*?\n\}', content, re.DOTALL)
        if init_match:
            print("Found init function, will append fix after it")
            # Insert after the init function
            insert_pos = init_match.end()
            new_content = content[:insert_pos] + FIX_CODE + content[insert_pos:]
            JS_FILE.write_text(new_content, encoding='utf-8')
            print("Fix appended after init function")
            return True
        print("Could not find suitable insertion point")
        return False
    
    # Replace with our fixed version
    old_call = match.group(1)
    new_call = old_call + FIX_CODE
    new_content = content.replace(old_call, new_call, 1)
    
    JS_FILE.write_text(new_content, encoding='utf-8')
    print(f"Fix applied, replaced: {old_call}")
    return True

if __name__ == '__main__':
    apply_fix()