#!/usr/bin/env python3
"""
Apply the Strategy Lab hash fix to the built JavaScript file.
This modifies freqtrade/rpc/api_server/ui/installed/assets/index-FbHqpW1i.js
to add initialization code that handles the #s=StrategyName hash parameter.
"""

import re
from pathlib import Path

JS_FILE = Path("freqtrade/rpc/api_server/ui/installed/assets/index-FbHqpW1i.js")

# The fix code to inject
FIX_CODE = """
;(function(){'use strict';function initStrategyLabFromHash(){const hash=window.location.hash;if(!hash.startsWith('#s='))return;const strategyName=hash.slice(3);console.log('[StrategyLab Fix] Found strategy in hash:',strategyName);function checkAndInit(){if(typeof openStrategy==='function'&&window.LAB){console.log('[StrategyLab Fix] Initializing strategy:',strategyName);openStrategy(strategyName,true);setTimeout(()=>{const tradesTab=Array.from(document.querySelectorAll('button,a,[role="tab"]')).find(el=>el.textContent.trim()==='Trades');if(tradesTab){console.log('[StrategyLab Fix] Clicking Trades tab');tradesTab.click()}},1000);return true}return false}if(!checkAndInit()){let attempts=0;const interval=setInterval(()=>{attempts++;if(checkAndInit()||attempts>=20)clearInterval(interval)},500)}}if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',initStrategyLabFromHash)}else{initStrategyLabFromHash()}window.addEventListener('hashchange',initStrategyLabFromHash)})();
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
    
    # Find the app mount line: Ns.mount("#app")
    # The pattern in the minified file is: Ns.mount("#app")
    mount_pattern = r'(Ns\.mount\("#app"\))'
    match = re.search(mount_pattern, content)
    
    if not match:
        print("Could not find Ns.mount('#app') in the file")
        # Try alternative patterns
        alt_patterns = [
            r'(\.mount\("#app"\))',
            r'(mount\("#app"\))',
        ]
        for pattern in alt_patterns:
            match = re.search(pattern, content)
            if match:
                print(f"Found alternative pattern: {match.group(1)}")
                break
    
    if not match:
        print("Could not find mount point. Trying to append at end of file...")
        # Append at the end before sourceMappingURL
        if '//# sourceMappingURL=' in content:
            content = content.replace('//# sourceMappingURL=', FIX_CODE + '\n//# sourceMappingURL=')
        else:
            content += FIX_CODE
        JS_FILE.write_text(content, encoding='utf-8')
        print("Fix appended at end of file")
        return True
    
    # Insert fix after the mount call
    insert_pos = match.end()
    new_content = content[:insert_pos] + FIX_CODE + content[insert_pos:]
    
    JS_FILE.write_text(new_content, encoding='utf-8')
    print(f"Fix applied after: {match.group(1)}")
    return True

if __name__ == '__main__':
    apply_fix()