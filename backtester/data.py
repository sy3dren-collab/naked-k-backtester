import csv
import hashlib
import io
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, time

TAIPEI = timezone(timedelta(hours=8))
DAY_OPEN, DAY_CLOSE = time(8, 45), time(13, 45)
TIMEFRAMES = (1, 5, 15, 30)
ALIASES = {
    'datetime': ['datetime', 'timestamp', '日期時間', '交易時間', '時間'],
    'date': ['date', '日期', '交易日期'], 'time': ['time', '時間'],
    'open': ['open', '開盤', '開盤價'], 'high': ['high', '最高', '最高價'],
    'low': ['low', '最低', '最低價'], 'close': ['close', '收盤', '收盤價'],
    'volume': ['volume', 'vol', '成交量', '交易量', '總成交量'],
    'contract': ['contract', 'symbol', '合約', '商品合約', '合約月份', '契約'], 'source': ['source', '資料來源', '來源'],
}


def decode_csv(raw):
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16'), 'utf-16'
    try:
        return raw.decode('utf-8-sig'), 'utf-8'
    except UnicodeDecodeError:
        return raw.decode('cp950'), 'big5'


def guess_mapping(headers):
    def normalized(value):
        return re.sub(r'[\s_\-()（）]', '', value).lower()
    def find(key):
        return next((h for h in headers if normalized(h) in [normalized(a) for a in ALIASES[key]]), '')
    date = find('date')
    return {'datetime': date or find('datetime'), 'time': find('time') if date else '',
            **{key: find(key) for key in ('open', 'high', 'low', 'close', 'volume', 'contract', 'source')}}


def parse_datetime(value, clock=''):
    value = value.strip() + (' ' + clock.strip() if clock else '')
    match = re.fullmatch(r'(\d{3,4})[-/](\d{1,2})[-/](\d{1,2})(?:[ T](.+))?', value)
    if not match:
        packed = re.fullmatch(r'(\d{7,8})(?:[ T](.+))?', value)
        if packed:
            d = packed[1]
            parts = (d[:-4], d[-4:-2], d[-2:], packed[2])
        else:
            raise ValueError('日期格式須為 YYYY-MM-DD、YYYY/MM/DD 或 YYYYMMDD')
    else:
        parts = match.groups()
    year, month, day, clock = parts
    year = int(year) + (1911 if len(year) == 3 else 0)
    clock = clock or '00:00'
    zone = re.search(r'([+-])(\d{2}):?(\d{2})$', clock)
    if zone and (int(zone[2]) > 23 or int(zone[3]) > 59):
        raise ValueError('時區偏移不合法')
    if clock.isdigit() and len(clock) in (4, 6):
        clock = clock[:2] + ':' + clock[2:4] + (':' + clock[4:] if len(clock) == 6 else '')
    clock = re.sub(r'^(\d):', r'0\1:', clock)
    dt = datetime.fromisoformat(f'{year:04}-{int(month):02}-{int(day):02}T{clock}')
    return dt.replace(tzinfo=TAIPEI) if dt.tzinfo is None else dt.astimezone(TAIPEI)


def parse_number(raw):
    text = raw.strip()
    if ',' in text and not re.fullmatch(r'[+-]?\d{1,3}(?:,\d{3})+(?:\.\d*)?(?:[eE][+-]?\d+)?', text):
        raise ValueError('數值的千分位格式錯誤')
    cleaned = text.replace(',', '')
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', cleaned):
        raise ValueError('數值須為十進位數字')
    return float(cleaned)


@dataclass(frozen=True)
class Bar:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    minutes: int = 1
    contract: str | None = None
    source: str | None = None

    @property
    def end(self):
        return self.start + timedelta(minutes=self.minutes)

    def json(self):
        return {**self.__dict__, 'start': self.start.isoformat()}


def day_session(dt):
    return dt.weekday() < 5 and DAY_OPEN <= dt.time().replace(tzinfo=None) < DAY_CLOSE


def parse_csv(raw, mapping=None):
    """Validate without silently repairing duplicate/unsorted/invalid records."""
    mapping = mapping or {}
    report = {'errors': [], 'warnings': [], 'missing_minutes': [], 'night_rows': 0,
              'outside_session_rows': 0, 'volume_missing_rows': 0, 'rows': 0}
    try:
        text, encoding = decode_csv(raw)
        report['source_encoding'] = mapping.get('_source_encoding', encoding)
        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        headers = reader.fieldnames or []
        if not mapping:
            mapping = guess_mapping(headers)
        if len(set(headers)) != len(headers):
            report['errors'].append('CSV 欄位名稱重複，請先調整欄名')
            return [], report
        required = ['datetime', 'open', 'high', 'low', 'close']
        absent = [k for k in required if mapping.get(k, k) not in headers]
        if absent:
            report['errors'].append('缺少必要欄位：' + ', '.join(absent))
            return [], report
        if len({mapping.get(k, k) for k in required}) != len(required):
            report['errors'].append('日期與 OHLC 必須對應不同欄位')
            return [], report
        bars, seen, previous = [], set(), None
        import math
        for line, row in enumerate(reader, 2):
            report['rows'] += 1
            try:
                dt = parse_datetime(row[mapping.get('datetime', 'datetime')], row.get(mapping.get('time', ''), '') or '')
                if dt.second or dt.microsecond:
                    raise ValueError('時間必須為整分鐘')
                values = [parse_number(row[mapping.get(k, k)]) for k in required[1:]]
                o, h, l, c = values
                if not all(math.isfinite(v) and v > 0 for v in values) or not l <= min(o, c) <= max(o, c) <= h:
                    raise ValueError('OHLC 非有限正值或高低價關係不合法')
                vol = (row.get(mapping.get('volume', 'volume'), '') or '').strip()
                vol = parse_number(vol) if vol else None
                if vol is not None and (not math.isfinite(vol) or vol < 0):
                    raise ValueError('成交量不合法')
                if vol is None:
                    report['volume_missing_rows'] += 1
                if dt in seen:
                    report['errors'].append(f'第 {line} 列：重複時間 {dt.isoformat()}')
                if previous is not None and dt < previous:
                    report['errors'].append(f'第 {line} 列：資料未按時間排序')
                seen.add(dt)
                previous = dt
                contract = (row.get(mapping.get('contract', ''), '') or '').strip() or None
                source = (row.get(mapping.get('source', ''), '') or mapping.get('_source', '') or '').strip() or None
                bars.append(Bar(dt, o, h, l, c, vol, contract=contract, source=source))
                if not day_session(dt):
                    report['outside_session_rows'] += 1
                    if dt.time() >= time(15) or dt.time() < time(5):
                        report['night_rows'] += 1
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                report['errors'].append(f'第 {line} 列：{exc}')
        daily = {}
        for b in bars:
            if day_session(b.start):
                daily.setdefault(b.start.date(), set()).add(b.start)
        for date, stamps in sorted(daily.items()):
            cursor, last = min(stamps), max(stamps)
            while cursor <= last:
                if cursor not in stamps:
                    report['missing_minutes'].append(cursor.isoformat())
                cursor += timedelta(minutes=1)
            if min(stamps).time() != DAY_OPEN or last.time() != time(13, 44):
                report['warnings'].append(f'{date}：非完整日盤，末筆 K 棒將作為當日強制平倉點')
        if report['missing_minutes']:
            report['warnings'].append(f"日盤缺棒 {len(report['missing_minutes'])} 根；不補價，缺棒區間不合成高週期 K")
        if report['volume_missing_rows']:
            report['warnings'].append('部分或全部成交量缺漏；純價格策略仍可執行')
        if report['outside_session_rows']:
            report['warnings'].append('非日盤資料保留，但 V1 不執行交易；未內建交易所假日行事曆')
        report['contract_changes'] = [{'time': b.start.isoformat(), 'from': a.contract, 'to': b.contract}
                                      for a, b in zip(bars, bars[1:]) if a.contract and b.contract and a.contract != b.contract]
        report['provenance'] = {'source': mapping.get('_source', ''), 'contract_column': mapping.get('contract', ''),
                                'source_column': mapping.get('source', ''), 'contract_known': any(b.contract for b in bars)}
        if not report['provenance']['contract_known']:
            report['warnings'].append('未提供商品合約欄位；無法自動辨識換月，來源與欄位對應仍完整保存')
        if not bars:
            report['errors'].append('CSV 沒有行情資料')
        return bars, report
    except (UnicodeError, csv.Error) as exc:
        report['errors'].append(f'無法解碼或解析 CSV，請使用 UTF-8 或 Big5：{exc}')
        return [], report


def aggregate(bars, minutes):
    if minutes not in TIMEFRAMES:
        raise ValueError('只支援 1、5、15、30 分 K')
    groups = {}
    for b in bars:
        if not day_session(b.start):
            continue
        anchor = b.start.replace(hour=8, minute=45)
        offset = int((b.start - anchor).total_seconds() // 60)
        bucket = anchor + timedelta(minutes=(offset // minutes) * minutes)
        groups.setdefault(bucket, []).append(b)
    result = []
    for start, rows in sorted(groups.items()):
        if len(rows) != minutes or any(b.start != start + timedelta(minutes=i) for i, b in enumerate(rows)):
            continue
        if len({b.contract for b in rows if b.contract}) > 1:
            continue
        result.append(Bar(start, rows[0].open, max(b.high for b in rows), min(b.low for b in rows),
                          rows[-1].close, sum(b.volume for b in rows) if all(b.volume is not None for b in rows) else None, minutes,
                          rows[0].contract, rows[0].source))
    return result


def fingerprint(raw):
    return hashlib.sha256(raw).hexdigest()
