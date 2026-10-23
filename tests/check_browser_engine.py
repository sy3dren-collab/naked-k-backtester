"""Parity checks for the standalone JavaScript engine; requires Node 18+."""
import copy
import json
import math
import random
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
from backtester.engine import run
from backtester.data import csv_columns, guess_mapping, parse_csv
from backtester.strategy import templates
from test_backtester import bars, flat, settings_strategy, simple_block


def check_close(expected, actual, path='result'):
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert isinstance(actual, (int, float)) and math.isclose(expected, actual, abs_tol=1e-7, rel_tol=1e-10), (path, expected, actual)
    elif isinstance(expected, dict):
        assert set(expected) == set(actual), (path, set(expected) ^ set(actual))
        for key in expected:
            check_close(expected[key], actual[key], path + '.' + key)
    elif isinstance(expected, list):
        assert len(expected) == len(actual), (path, len(expected), len(actual))
        for i, (left, right) in enumerate(zip(expected, actual)):
            check_close(left, right, f'{path}[{i}]')
    else:
        assert expected == actual, (path, expected, actual)


def check_csv_headers():
    texts=[
        '日期,時間,開盤價,最高價,最低價,收盤價,備註,備註,,\n2024/2/1,08:45,100,110,90,102,first,second,,',
        'datetime,open,high,low,close,open\n2024-02-01 08:45,100,110,90,102,105',
        '日期,日期,時間,open,high,low,close\n2024/2/1,2024/2/2,08:45,100,110,90,102',
        'datetime,open,high,low,close,open,open [第 2 欄]\n2024-02-01 08:45,100,110,90,102,105,107',
    ]
    fixtures=[]
    for text in texts:
        original=text.split('\n')[0].split(',');columns=csv_columns(original)
        guessed=guess_mapping([c['key'] for c in columns],original)
        mappings=[None]
        if guessed['open']=='':
            mappings += [{**guessed,'open':c['key']} for c in columns if c['name']=='open']
        if guessed['datetime']=='':mappings.append({**guessed,'datetime':columns[0]['key']})
        for mapping in mappings:
            bars,report=parse_csv(text.encode(),mapping)
            fixtures.append({'text':text,'mapping':mapping,'expected':{'columns':columns,'guessed':guessed,'error':bool(report['errors']),
                'bars':[[b.start.isoformat(),b.open,b.high,b.low,b.close,b.volume] for b in bars]}})
    source="""
const fs=require('fs'),vm=require('vm');
vm.runInThisContext(fs.readFileSync('static/csv.js','utf8'));
const fixtures=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(fixtures.map(f=>{const columns=NakedCSV.columns(f.text),r=NakedCSV.parse(f.text,f.mapping);return {columns,guessed:NakedCSV.guess(columns.map(c=>c.key),columns.map(c=>c.name)),error:r.report.errors.length>0,bars:r.bars.map(b=>[NakedCSV.iso(b.start),b.open,b.high,b.low,b.close,b.volume])};})));
"""
    output=subprocess.run(['node','-e',source],input=json.dumps(fixtures,ensure_ascii=False),capture_output=True,text=True,cwd=ROOT,check=True)
    for i,(fixture,actual) in enumerate(zip(fixtures,json.loads(output.stdout))):check_close(fixture['expected'],actual,f'csv[{i}]')
    print(f'PASS: {len(fixtures)} Python / JavaScript CSV comparisons (blank/duplicate/colliding headers, explicit column choices, ambiguous dates)')


def main():
    check_csv_headers()
    fixtures = []
    samples = [flat(5) + [(100,105,99,104),(104,130,90,104),(105,106,104,105)],
               flat(20) + [(100,106,99,105),(105,106,104,105),(105,106,101,103),(103,105,102,104),(104,105,103,104)],
               [(100,101,99,100),(100,102,98,100),(100,110,90,100),(100,103,97,100),(100,102,98,100),(100,112,99,111),(112,113,89,100),(100,101,99,100)]]
    randomizer = random.Random(431)
    for _ in range(12):
        row, previous = [], 1000
        for i in range(120):
            close = previous + randomizer.randint(-12, 12)
            row.append((previous, max(previous, close) + randomizer.randint(1, 8), min(previous, close) - randomizer.randint(1, 8), close))
            previous = close
        samples.append(row)
    for values in samples:
        for template in templates():
            for timeframe in (1, 5, 15):
                strategy = copy.deepcopy(template)
                if timeframe != 1:
                    strategy['timeframe'] = timeframe
                    for block in strategy['blocks']:
                        if block['type'] != 'opening_range':
                            block['timeframe'] = timeframe
                strategy['costs'] = settings_strategy()['costs'] | {'commission': 2, 'slippage': 1, 'tax_rate': .00002}
                data = bars(values)
                fixtures.append({'bars': [b.json() for b in data], 'strategy': strategy, 'expected': run(data, strategy)})
    source = '''
const fs=require('fs'),vm=require('vm'),crypto=require('crypto');
for(const file of ['static/csv.js','static/engine.js'])vm.runInThisContext(fs.readFileSync(file,'utf8'),{filename:file});
for(const text of ['', 'abc', '日期時間', 'a'.repeat(129)])if(NakedEngine.sha256(text)!==crypto.createHash('sha256').update(text).digest('hex'))throw Error('SHA-256 mismatch');
const fixtures=JSON.parse(fs.readFileSync(0,'utf8'));
console.log(JSON.stringify(fixtures.map(f=>NakedEngine.run(f.bars.map(b=>({...b,start:Date.parse(b.start)})),f.strategy,{}))));
'''
    completed = subprocess.run(['node', '-e', source], input=json.dumps(fixtures, ensure_ascii=False), text=True, capture_output=True, cwd=ROOT, check=True)
    results = json.loads(completed.stdout)
    for i, (fixture, actual) in enumerate(zip(fixtures, results)):
        expected = fixture['expected']
        # Numeric representation in human-readable reasons can differ (1 vs 1.0).
        for result in (expected, actual):
            result.pop('engine_version')
            for trade in result['trades']:
                trade['entry_reason'] = trade['entry_reason'].split('；')[0]
                trade['exit_reason'] = trade['exit_reason'].split('；')[0]
            for signal in result['signals']:
                signal['reason'] = signal['reason'].split('；')[0]
        check_close(expected, actual, f'fixture[{i}]')
    print(f'PASS: SHA-256 and {len(results)} Python / JavaScript engine comparisons (trades, signals, equity, costs, metrics)')


if __name__ == '__main__':
    main()
