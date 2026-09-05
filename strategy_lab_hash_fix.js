// Fix for Strategy Lab trade map not rendering on direct URL access
// Add this to the main entry point (index-FbHqpW1i.js) after the Vue app is mounted

(function() {
  'use strict';
  
  // Wait for the app to be fully initialized
  function initStrategyLabFromHash() {
    const hash = window.location.hash;
    if (!hash.startsWith('#s=')) return;
    
    const strategyName = hash.slice(3); // Remove '#s='
    console.log('[StrategyLab Fix] Found strategy in hash:', strategyName);
    
    // Wait for LAB and openStrategy to be available
    function checkAndInit() {
      if (typeof openStrategy === 'function' && window.LAB) {
        console.log('[StrategyLab Fix] Initializing strategy:', strategyName);
        openStrategy(strategyName, true); // fromHash = true
        
        // Also trigger trade map rendering after a delay
        setTimeout(() => {
          const tradesTab = document.querySelector('text=Trades') || 
                           document.querySelector('[href="#trades"]') ||
                           document.querySelector('button:contains("Trades")') ||
                           Array.from(document.querySelectorAll('button, a')).find(el => el.textContent.trim() === 'Trades');
          if (tradesTab) {
            console.log('[StrategyLab Fix] Clicking Trades tab');
            tradesTab.click();
          }
        }, 1000);
        
        return true;
      }
      return false;
    }
    
    // Try immediately
    if (!checkAndInit()) {
      // Retry every 500ms for up to 10 seconds
      let attempts = 0;
      const interval = setInterval(() => {
        attempts++;
        if (checkAndInit() || attempts >= 20) {
          clearInterval(interval);
        }
      }, 500);
    }
  }
  
  // Run after DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initStrategyLabFromHash);
  } else {
    initStrategyLabFromHash();
  }
  
  // Also handle hash changes
  window.addEventListener('hashchange', initStrategyLabFromHash);
})();