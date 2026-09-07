import re

with open(r'M:\Documents\Programming\Python\freqtrade\user_data\scripts\build_report.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''    <section>
      <div class="section-head"><h2>Dry run (local)</h2>
        <span class="hint">start a detached freqtrade trade process on this machine \u2014 survives lab server restarts; log lives at user_data/logs/dryrun-<id>.log</span></div>
      <div class="card">
        <div class="controls">
          <button class="btn" id="dryrunStartBtn" onclick="dryrunStart()">\u25b6 Start dry run</button>
          <button class="btn" id="dryrunStopBtn" onclick="dryrunStop()" disabled>\u25a0 Stop</button>
          <span id="dryrunStatus" class="hint">No dry run</span>
        </div>
        <div id="dryrunMeta" class="hint" style="margin-top:6px"></div>
        <pre id="dryrunLog" style="display:none; max-height:240px; overflow:auto; background:var(--bg-soft); padding:8px; border-radius:4px; font-size:12px; line-height:1.4; white-space:pre-wrap; margin-top:8px"></pre>
        <div id="dryrunFooter" class="hint" style="margin-top:4px"></div>
      </div>
    </section>
    <section>
      <div class="section-head"><h2>Benchmark</h2>
        <span class="hint">run every strategy on the shared config and compare distributions</span></div>
      <div class="card">
        <div class="controls">
          <button class="btn" onclick="labBench()">Run benchmark</button>
          <label>Strategies: <input id="benchStrategies" type="text" placeholder="comma separated (empty = all)" style="min-width:220px"></label>
          <label>Range: <input id="benchRange" type="text" value="20230101-20240101" style="width:150px"></label>
          <label>TF: <input id="benchTf" type="text" value="5m" style="width:70px"></label>
        </div>
      </div>
    </section>'''

new = '''    <section>
      <div class="section-head"><h2>Dry run (local)</h2>
        <span class="hint">start a detached freqtrade trade process on this machine \u2014 survives lab server restarts; log lives at user_data/logs/dryrun-<id>.log</span></div>
      <div class="card">
        <div class="controls">
          <label>Strategy: <select id="dryrunStrategy" style="min-width:220px"><option value="">(choose...)</option></select></label>
          <label>Config: <select id="dryrunConfig" style="min-width:200px"><option value="">auto (optional)</option></select></label>
          <button class="btn" id="dryrunStartBtn" onclick="dryrunStart()">Start dry run</button>
          <button class="btn" id="dryrunStopBtn" onclick="dryrunStop()" disabled>Stop</button>
        </div>
        <div id="dryrunMeta" class="hint" style="margin-top:6px"></div>
        <pre id="dryrunLog" style="display:none; max-height:240px; overflow:auto; background:var(--bg-soft); padding:8px; border-radius:4px; font-size:12px; line-height:1.4; white-space:pre-wrap; margin-top:8px"></pre>
        <div id="dryrunFooter" class="hint" style="margin-top:4px"></div>
      </div>
    </section>
    <section>
      <div class="section-head"><h2>Benchmark</h2>
        <span class="hint">run every strategy on the shared config and compare distributions</span></div>
      <div class="card">
        <div class="controls">
          <label>Mode: <select id="benchMode" onchange="labBenchUpdateFields()">
            <option value="backtest">Backtest</option>
            <option value="hyperopt">Hyperopt</option>
            <option value="walkforward">Walk-forward</option>
          </select></label>
          <button class="btn" onclick="labBench()">Run benchmark</button>
          <label>Strategies: <input id="benchStrategies" type="text" placeholder="comma separated (empty = all)" style="min-width:220px"></label>
          <label>Range: <input id="benchRange" type="text" value="20230101-20240101" style="width:150px"></label>
          <label>TF: <input id="benchTf" type="text" value="5m" style="width:70px"></label>
          <label data-benchfield="hyperopt walkforward" class="hidden">Epochs: <input id="benchEpochs" type="number" value="100" style="width:90px"></label>
          <label data-benchfield="hyperopt walkforward" class="hidden">Loss: <select id="benchLoss"></select></label>
          <label data-benchfield="hyperopt walkforward" class="hidden">Spaces: <input id="benchSpaces" value="buy sell roi stoploss trailing" style="min-width:200px"></label>
          <label data-benchfield="hyperopt walkforward" class="hidden">Jobs: <input id="benchJobs" type="number" placeholder="-1" style="width:70px"></label>
          <label data-benchfield="hyperopt walkforward" class="hidden">Seed: <input id="benchRandomState" type="number" placeholder="auto" style="width:90px"></label>
          <label data-benchfield="walkforward" class="hidden">Train d: <input id="benchTrain" type="number" value="90" style="width:80px"></label>
          <label data-benchfield="walkforward" class="hidden">Test d: <input id="benchTest" type="number" value="7" style="width:70px"></label>
          <label data-benchfield="walkforward" class="hidden">Step d: <input id="benchStep" type="number" value="7" style="width:70px"></label>
        </div>
      </div>
    </section>'''

if old in content:
    content = content.replace(old, new)
    with open(r'M:\Documents\Programming\Python\freqtrade\user_data\scripts\build_report.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Replaced successfully')
else:
    print('Old string not found')
    idx = content.find('Dry run (local)')
    if idx >= 0:
        print('Found at index:', idx)
        print(repr(content[idx:idx+500]))