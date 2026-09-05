#!/usr/bin/env python3
"""
Fix for frequi dashboard: append fix at end of file
"""

from pathlib import Path

JS_FILE = Path("freqtrade/rpc/api_server/ui/installed/assets/index-wxgNlDZx.js")

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
    
    # Insert before sourceMappingURL
    if '//# sourceMappingURL=' in content:
        content = content.replace('//# sourceMappingURL=', FIX_CODE + '\n//# sourceMappingURL=')
        JS_FILE.write_text(content, encoding='utf-8')
        print("Fix inserted before sourceMappingURL")
        return True
    
    # Otherwise append at end
    content += FIX_CODE
    JS_FILE.write_text(content, encoding='utf-8')
    print("Fix appended at end of file")
    return True

if __name__ == '__main__':
    apply_fix()