import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .data import Bar, CSV_PARSER_VERSION, parse_csv
from .engine import canonical, ENGINE_VERSION
from .strategy import validate, version_identity


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, raw BLOB NOT NULL,
                    mapping TEXT NOT NULL, report TEXT NOT NULL, bars TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS strategies (
                    id TEXT NOT NULL, version TEXT NOT NULL, document TEXT NOT NULL,
                    PRIMARY KEY(id, version));
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL,
                    strategy_id TEXT NOT NULL, strategy_version TEXT NOT NULL,
                    settings TEXT NOT NULL, result TEXT NOT NULL,
                    FOREIGN KEY(dataset_id) REFERENCES datasets(id));
                CREATE TABLE IF NOT EXISTS strategy_archive (
                    id TEXT NOT NULL, version TEXT NOT NULL, PRIMARY KEY(id,version));
                CREATE TABLE IF NOT EXISTS learning_studies (
                    id TEXT PRIMARY KEY, document TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS learning_checks (
                    study_id TEXT NOT NULL, candidate_id TEXT NOT NULL, dataset_id TEXT NOT NULL,
                    start TEXT NOT NULL, end TEXT NOT NULL, document TEXT NOT NULL,
                    PRIMARY KEY(study_id,candidate_id), FOREIGN KEY(study_id) REFERENCES learning_studies(id));
            ''')
            columns = {row[1] for row in db.execute('PRAGMA table_info(datasets)')}
            for name in ('first_time', 'last_time'):
                if name not in columns:
                    db.execute(f'ALTER TABLE datasets ADD COLUMN {name} TEXT')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    def import_data(self, name, raw, mapping=None):
        mapping = mapping or {}
        bars, report = parse_csv(raw, mapping)
        id = hashlib.sha256(raw + b'\0' + canonical(mapping).encode() + b'\0' + CSV_PARSER_VERSION.encode()).hexdigest()
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO datasets(id,name,raw,mapping,report,bars,first_time,last_time) VALUES (?,?,?,?,?,?,?,?)',
                       (id, name, raw, canonical(mapping), canonical(report), canonical([b.json() for b in bars]),
                        bars[0].start.isoformat() if bars else None, bars[-1].start.isoformat() if bars else None))
        return {'id': id, 'name': name, 'report': report, 'first': bars[0].start.isoformat() if bars else None,
                'last': bars[-1].start.isoformat() if bars else None}

    def dataset(self, id):
        with self.connect() as db:
            row = db.execute('SELECT * FROM datasets WHERE id=?', (id,)).fetchone()
        if row is None:
            raise ValueError('找不到匯入資料')
        report = json.loads(row['report'])
        if report['errors']:
            raise ValueError('資料檢查有錯誤，請修正 CSV 後重新匯入')
        bars = [Bar(**{**b, 'start': datetime.fromisoformat(b['start'])}) for b in json.loads(row['bars'])]
        return bars, report

    def datasets(self):
        with self.connect() as db:
            return [{**dict(r), 'report': json.loads(r['report'])} for r in db.execute('SELECT id,name,report,first_time AS first,last_time AS last FROM datasets ORDER BY rowid DESC')]

    def dataset_name(self,id):
        with self.connect() as db:row=db.execute('SELECT name FROM datasets WHERE id=?',(id,)).fetchone()
        if not row:raise ValueError('找不到匯入資料')
        return row[0]

    def save_strategy(self, strategy):
        validate(strategy)
        doc = canonical(strategy)
        with self.connect() as db:
            existing = db.execute('SELECT document FROM strategies WHERE id=? AND version=?',
                                  (strategy['strategy_id'], str(strategy['version']))).fetchone()
            if existing and canonical(version_identity(json.loads(existing['document']))) != canonical(version_identity(strategy)):
                raise ValueError('相同策略 ID／版本已有不同內容；請增加版本號以保留可重現性')
            db.execute('INSERT OR IGNORE INTO strategies VALUES (?,?,?)', (strategy['strategy_id'], str(strategy['version']), doc))
            db.execute('DELETE FROM strategy_archive WHERE id=? AND version=?', (strategy['strategy_id'], str(strategy['version'])))

    def strategies(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute('SELECT s.document FROM strategies s LEFT JOIN strategy_archive a ON s.id=a.id AND s.version=a.version WHERE a.id IS NULL ORDER BY s.rowid DESC')]

    def strategy(self, id, version):
        with self.connect() as db:
            row = db.execute('SELECT document FROM strategies WHERE id=? AND version=?', (id, str(version))).fetchone()
        if row is None: raise ValueError('找不到策略版本')
        return json.loads(row[0])

    def delete_strategy(self, id, version):
        self.strategy(id, version)
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO strategy_archive VALUES (?,?)', (id, str(version)))

    def clone_strategy(self, strategy, id, name=None):
        import copy
        cloned = copy.deepcopy(strategy)
        cloned['strategy_id'], cloned['version'] = id, '1.0'
        cloned['name'] = name or strategy.get('name', id)+' 副本'
        self.save_strategy(cloned)
        return cloned

    def prepare_version(self, strategy):
        import copy
        result = copy.deepcopy(strategy)
        validate(result)
        with self.connect() as db:
            rows = db.execute('SELECT version,document FROM strategies WHERE id=?', (result['strategy_id'],)).fetchall()
        existing = {r['version']: r['document'] for r in rows}
        version = str(result['version'])
        if version not in existing or canonical(version_identity(json.loads(existing[version]))) == canonical(version_identity(result)):
            return result
        parts = version.split('.')
        if parts[-1].isdigit():
            prefix, number = '.'.join(parts[:-1]), int(parts[-1])+1
            candidate = (prefix+'.' if prefix else '')+str(number)
            while candidate in existing:
                number += 1; candidate = (prefix+'.' if prefix else '')+str(number)
        else:
            number, candidate = 1, version+'.1'
            while candidate in existing:
                number += 1; candidate = version+'.'+str(number)
        result['version'] = candidate
        return result

    def save_run(self, dataset_id, result):
        strategy = result['strategy']
        id = hashlib.sha256(canonical([result.get('engine_version', ENGINE_VERSION), dataset_id, strategy, result['settings']]).encode()).hexdigest()
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?)',
                       (id, dataset_id, strategy['strategy_id'], str(strategy['version']), canonical(result['settings']), canonical(result)))
        return id

    def result(self, id):
        with self.connect() as db:
            row = db.execute('SELECT result FROM runs WHERE id=?', (id,)).fetchone()
        if row is None:
            raise ValueError('找不到回測結果')
        return json.loads(row[0])

    def run_metadata(self, id):
        with self.connect() as db:
            row = db.execute('SELECT id,dataset_id,settings,strategy_id,strategy_version FROM runs WHERE id=?', (id,)).fetchone()
        if row is None: raise ValueError('找不到回測紀錄')
        return {**dict(row), 'settings': json.loads(row['settings'])}

    def runs(self):
        with self.connect() as db:
            rows = db.execute('SELECT id,dataset_id,strategy_id,strategy_version,settings,result FROM runs ORDER BY rowid DESC').fetchall()
        return [{k: r[k] for k in ('id', 'dataset_id', 'strategy_id', 'strategy_version')} |
                {'settings': json.loads(r['settings']), 'metrics': {k:v for k,v in json.loads(r['result'])['metrics'].items() if k!='cumulative_pnl'}} for r in rows]

    def save_learning_study(self,study):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO learning_studies VALUES (?,?)',(study['id'],canonical(study)))

    def learning_study(self,id,required=True):
        with self.connect() as db:row=db.execute('SELECT document FROM learning_studies WHERE id=?',(id,)).fetchone()
        if row:return json.loads(row[0])
        if required:raise ValueError('找不到研究紀錄')

    def learning_studies(self):
        with self.connect() as db:
            rows=db.execute('SELECT id,document FROM learning_studies ORDER BY rowid DESC LIMIT 20').fetchall()
        return [{'id':r['id'],**{k:doc[k] for k in ('recipe','config','split')}} for r in rows for doc in [json.loads(r['document'])]]

    def learning_check(self,study_id,candidate_id):
        with self.connect() as db:
            row=db.execute('SELECT document FROM learning_checks WHERE study_id=? AND candidate_id=?',(study_id,candidate_id)).fetchone()
        return json.loads(row[0]) if row else None

    def learning_check_ids(self,study_id):
        with self.connect() as db:
            return [r[0] for r in db.execute('SELECT candidate_id FROM learning_checks WHERE study_id=?',(study_id,))]

    def save_learning_check(self,check):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO learning_checks VALUES (?,?,?,?,?,?)',
                       (check['study_id'],check['candidate_id'],check['dataset_id'],check['period']['start'],check['period']['end'],canonical(check)))

    def learning_exposures(self,dataset_id,period):
        with self.connect() as db:
            return db.execute('SELECT COUNT(*) FROM learning_checks WHERE dataset_id=? AND start<=? AND end>=?',
                              (dataset_id,period['end'],period['start'])).fetchone()[0]
