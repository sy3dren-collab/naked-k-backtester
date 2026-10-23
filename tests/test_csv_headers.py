"""Regression coverage for spreadsheet exports with repeated and blank headers."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from backtester.data import csv_columns, guess_mapping, parse_csv
from backtester.engine import canonical
from backtester.store import Store


class CSVHeaderTests(unittest.TestCase):
    def test_empty_trailing_and_duplicate_unused_columns_do_not_block_prices(self):
        text='日期,時間,開盤價,最高價,最低價,收盤價,成交量,備註,備註,,\r\n2024/2/1,08:45:00,100,110,90,102,12,first,second,,\r\n'
        for encoding in ('utf-8-sig','cp950','utf-16'):
            with self.subTest(encoding=encoding):
                bars,report=parse_csv(text.encode(encoding))
                self.assertEqual(report['errors'],[])
                self.assertEqual(len(bars),1)
                self.assertEqual((bars[0].open,bars[0].close,bars[0].volume),(100,102,12))
                self.assertEqual(len(report['columns']),11)
                self.assertEqual(report['columns'][8]['name'],'備註')
                self.assertEqual(report['columns'][10]['key'],'未命名欄位 [第 11 欄]')
                self.assertTrue(any('欄名' in w for w in report['warnings']))

    def test_same_named_prices_require_an_explicit_physical_column(self):
        text='datetime,open,high,low,close,open\n2024-02-01 08:45,100,110,90,102,105\n'
        bars,report=parse_csv(text.encode())
        self.assertEqual(bars,[])
        self.assertTrue(any('open' in e for e in report['errors']))
        mapping={'datetime':'datetime','high':'high','low':'low','close':'close'}
        for selected,expected in (('open [第 2 欄]',100),('open [第 6 欄]',105)):
            with self.subTest(column=selected):
                bars,report=parse_csv(text.encode(),{**mapping,'open':selected})
                self.assertEqual(report['errors'],[])
                self.assertEqual(bars[0].open,expected)

    def test_generated_names_do_not_collide_with_genuine_headers(self):
        names=['open','open','open [第 1 欄]','','未命名欄位 [第 4 欄]']
        columns=csv_columns(names);keys=[c['key'] for c in columns]
        self.assertEqual(len(keys),len(set(keys)))
        self.assertEqual(keys[0],'open [第 1 欄]#')
        self.assertEqual(keys[2],names[2])
        self.assertEqual(keys[3],'未命名欄位 [第 4 欄]#')
        self.assertEqual(keys[4],names[4])

    def test_ambiguous_date_does_not_silently_fall_back_to_time(self):
        names=['日期','日期','時間','open','high','low','close']
        keys=[c['key'] for c in csv_columns(names)]
        mapping=guess_mapping(keys,names)
        self.assertEqual(mapping['datetime'],'')
        self.assertEqual(mapping['time'],'時間')
        text=','.join(names)+'\n2024-02-01,2024-02-02,08:45,100,110,90,102\n'
        mapping['datetime']='日期 [第 1 欄]'
        bars,report=parse_csv(text.encode(),mapping)
        self.assertEqual(report['errors'],[])
        self.assertEqual(bars[0].start.isoformat(),'2024-02-01T08:45:00+08:00')

    def test_equivalent_aliases_are_ambiguous_and_never_overwrite_values(self):
        names=['datetime','open','開盤價','high','low','close']
        self.assertEqual(guess_mapping(names)['open'],'')
        text=','.join(names)+'\n2024-02-01 08:45,100,105,110,90,102\n'
        mapping={'datetime':'datetime','open':'開盤價','high':'high','low':'low','close':'close'}
        bars,report=parse_csv(text.encode(),mapping)
        self.assertEqual(report['errors'],[])
        self.assertEqual(bars[0].open,105)

    def test_reimport_after_upgrade_does_not_reuse_an_old_failed_report(self):
        raw=b'datetime,open,high,low,close,,\n2024-02-01 08:45,100,110,90,102,,\n'
        old_id=hashlib.sha256(raw+b'\0'+canonical({}).encode()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            store=Store(Path(directory)/'test.sqlite3')
            old_report={'errors':['CSV 欄位名稱重複，請先調整欄名'],'warnings':[],'rows':0}
            with store.connect() as db:
                db.execute('INSERT INTO datasets(id,name,raw,mapping,report,bars) VALUES (?,?,?,?,?,?)',
                           (old_id,'old.csv',raw,'{}',canonical(old_report),'[]'))
            imported=store.import_data('fixed.csv',raw)
            self.assertNotEqual(imported['id'],old_id)
            bars,report=store.dataset(imported['id'])
            self.assertEqual(report['errors'],[])
            self.assertEqual(len(bars),1)
            self.assertEqual(store.import_data('fixed.csv',raw)['id'],imported['id'])
            with store.connect() as db:
                retained=db.execute('SELECT report FROM datasets WHERE id=?',(old_id,)).fetchone()
            self.assertEqual(json.loads(retained['report']),old_report)


if __name__=='__main__':unittest.main()
