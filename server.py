"""StudSift: local, CSV-backed LEGO brick inventory web application."""
from __future__ import annotations

import csv
import io
import json
import os
import re
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('STUDSIFT_DATA', os.environ.get('LEGO_SORTER_DATA', str(ROOT / 'data'))))
WEB = ROOT / 'web'
DEFAULT_CAPACITY = 100
MAX_CAPACITY = 10000
MAX_REQUEST = 10 * 1024 * 1024
LOCK = threading.RLock()
BRICKOGNIZE = 'https://api.brickognize.com/predict/parts/?predict_color=true&top_k_items=5&top_k_colors=5'
RB_BASE = 'https://rebrickable.com/api/v3/lego/'
FILES = {
    'inventory': ('inventory.csv', ('bag_number','part_id','description','colour','category','quantity','updated_at')),
    'bags': ('bags.csv', ('bag_number','category','created_at')),
    'sets': ('sets.csv', ('set_num','name','image_url','created_at')),
    'set_requirements': ('set_requirements.csv', ('set_num','part_id','description','colour','colour_id','required','image_url')),
    'set_pieces': ('set_pieces.csv', ('set_num','bag_number','part_id','description','colour','quantity','updated_at')),
    'set_bag_progress': ('set_bag_progress.csv', ('set_num','bag_number','completed_at')),
    'set_pick_staging': ('set_pick_staging.csv', ('set_num','source_bag','part_id','colour','quantity','updated_at')),
    'colours': ('colours.csv', ('colour_id','name')),
}
CONFIG_FILE = DATA / 'config.json'
JOURNAL_FILE = DATA / '.pending-transaction.json'
# Rebrickable and LEGO colour naming sometimes differ. Only explicit, unambiguous aliases apply.
ALIASES = {
    'bright red':'red', 'bright blue':'blue', 'bright yellow':'yellow', 'bright green':'green',
    'medium stone grey':'light bluish gray', 'medium stone gray':'light bluish gray',
    'dark stone grey':'dark bluish gray', 'dark stone gray':'dark bluish gray',
    'earth blue':'dark blue', 'earth green':'dark green', 'brick yellow':'tan',
    'sand yellow':'dark tan', 'medium nougat':'medium nougat',
    'light grey':'light gray', 'dark grey':'dark gray',
    'light bluish grey':'light bluish gray', 'dark bluish grey':'dark bluish gray',
    'transparent':'trans-clear', 'transparent clear':'trans-clear', 'trans clear':'trans-clear',
}


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8-sig', newline='', dir=path.parent,
                                         prefix='.tmp_', suffix='.csv', delete=False) as f:
            tmp = f.name
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)


def write_json(path, data):
    fd, name = tempfile.mkstemp(prefix='.tmp_', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def recover_transaction():
    if JOURNAL_FILE.exists():
        pending = json.loads(JOURNAL_FILE.read_text(encoding='utf-8'))
        for key, rows in pending.items():
            if key not in FILES:
                raise ValueError('Unrecognised pending transaction file.')
            filename, fields = FILES[key]
            write_csv(DATA / filename, rows, fields)
        JOURNAL_FILE.unlink()


def initialise():
    DATA.mkdir(parents=True, exist_ok=True)
    with LOCK:
        recover_transaction()
        for filename, fields in FILES.values():
            if not (DATA / filename).exists():
                write_csv(DATA / filename, [], fields)


def rows_for(key):
    filename, _ = FILES[key]
    with (DATA / filename).open('r', encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if key in ('inventory','set_pieces','set_pick_staging'):
            r['quantity'] = int(r['quantity'])
        elif key == 'set_requirements':
            r['required'] = int(r['required'])
    return rows


def load_all():
    recover_transaction()
    return {key: rows_for(key) for key in FILES}


def load():
    with LOCK:
        all_data = load_all()
        return all_data['inventory'], all_data['bags']


def commit(data, *keys):
    """Redo journal ensures an interrupted multi-CSV move is completed on restart."""
    if not keys:
        return
    transaction = {key: data[key] for key in keys}
    write_json(JOURNAL_FILE, transaction)
    recover_transaction()


def classification(name, category=''):
    s = (name + ' ' + category).lower()
    if any(w in s for w in ('minifig','minidoll','torso','headwear','hair piece','helmet')):
        return 'Minifigures'
    if any(w in s for w in ('technic','axle','pin connector','bush','gear','liftarm','beam','connector peg')):
        return 'Technic'
    if any(w in s for w in ('wheel','tyre','tire','vehicle','windscreen','windshield','mudguard')):
        return 'Wheels & Vehicles'
    if any(w in s for w in ('slope','wedge','arch','curved','curve')):
        return 'Slopes & Curves'
    if 'tile' in s:
        return 'Tiles'
    if 'plate' in s:
        return 'Plates'
    if 'brick' in s:
        return 'Bricks'
    return 'Other / Special'


def colour_key(name):
    key = ' '.join(str(name).strip().casefold().replace('_',' ').split())
    return ALIASES.get(key, key)



# Suggestions only. Identical part IDs with a different colour are not true
# matches until a user physically checks and corrects the inventory entry.
COLOUR_GROUPS = (
    {'light gray', 'light bluish gray', 'very light bluish gray', 'very light gray'},
    {'dark gray', 'dark bluish gray', 'black'},
    {'white', 'very light bluish gray', 'very light gray', 'light bluish gray'},
    {'brown', 'reddish brown', 'dark brown'},
    {'tan', 'dark tan', 'medium tan', 'sand yellow'},
    {'blue', 'dark blue', 'medium blue', 'light blue'},
    {'red', 'dark red', 'bright light red'},
    {'yellow', 'bright light yellow', 'light yellow'},
    {'green', 'dark green', 'bright green', 'lime'},
    {'orange', 'bright light orange'},
    {'pink', 'bright pink', 'light pink'},
    {'purple', 'dark purple', 'medium lavender', 'lavender'},
    {'trans-clear', 'trans-light blue', 'trans-blue'},
)


def likely_colour_confusion(a, b):
    x, y = colour_key(a), colour_key(b)
    return x != y and any(x in family and y in family for family in COLOUR_GROUPS)


def part_key(part, colour):
    return (str(part).strip().casefold(), colour_key(colour))


def validate_piece(data):
    if not isinstance(data, dict):
        raise ValueError('Invalid piece data.')
    part = str(data.get('part_id','')).strip()
    desc = str(data.get('description','')).strip()
    colour = str(data.get('colour','')).strip()
    qty = data.get('quantity', 1)
    if isinstance(qty, bool) or not re.fullmatch(r'[0-9]+', str(qty)):
        raise ValueError('Quantity must be a whole number.')
    qty = int(qty)
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', part):
        raise ValueError('Enter a valid part ID.')
    if not desc or len(desc) > 200 or any(ord(c)<32 for c in desc) or desc[0] in '=+@-':
        raise ValueError('Invalid description.')
    if not colour or len(colour) > 80 or any(ord(c)<32 for c in colour) or colour[0] in '=+@-':
        raise ValueError('Enter a valid colour.')
    limit = bag_capacity()
    if not 1 <= qty <= limit:
        raise ValueError(f'Quantity must be between 1 and {limit}.')
    return {'part_id':part,'description':desc,'colour':colour,'quantity':qty,
            'category':classification(desc, str(data.get('api_category',''))[:100])}


def set_number(value):
    num = str(value).strip()
    if re.fullmatch(r'\d{1,8}', num):
        num += '-1'
    if not re.fullmatch(r'\d{1,8}-\d{1,3}', num):
        raise ValueError('Enter a set number such as 75375 or 75375-1.')
    return num


def choose_bags(piece, amount, rows, bags, category):
    """Return placement without modifying the input rows or bags."""
    capacity = bag_capacity()
    counts = defaultdict(int)
    exact = set()
    for r in rows:
        counts[r['bag_number']] += r['quantity']
        if part_key(r['part_id'],r['colour']) == part_key(piece['part_id'],piece['colour']):
            exact.add(r['bag_number'])
    if any(q > capacity for q in counts.values()):
        raise ValueError(f'Existing bag exceeds the current {capacity}-piece limit. Check inventory or Settings.')
    good_bags = {b['bag_number']: b for b in bags if b['category'] == category}
    priority = sorted((b for b in exact if b in good_bags and counts[b] < capacity), key=int)
    others = sorted((b for b in good_bags if b not in exact and counts[b] < capacity),
                    key=lambda b: (-counts[b], int(b)))
    allocations, new_bags = [], []
    for bag in priority + others:
        take = min(amount, capacity - counts[bag])
        if take:
            allocations.append({'bag_number':bag, 'quantity':take, 'new_bag':False})
            amount -= take
        if amount == 0:
            break
    number = max((int(b['bag_number']) for b in bags), default=0) + 1
    while amount:
        bag = f'{number:03d}'
        take = min(amount, capacity)
        new_bags.append({'bag_number':bag,'category':category,'created_at':utcnow()})
        allocations.append({'bag_number':bag,'quantity':take,'new_bag':True})
        amount -= take
        number += 1
    return allocations, new_bags, bool(exact)


def append_placements(rows, allocations, piece, category, set_num=None):
    for alloc in allocations:
        if set_num is None:
            match = next((r for r in rows if r['bag_number'] == alloc['bag_number'] and
                          part_key(r['part_id'],r['colour']) == part_key(piece['part_id'],piece['colour'])), None)
        else:
            match = next((r for r in rows if r['set_num'] == set_num and r['bag_number'] == alloc['bag_number'] and
                          part_key(r['part_id'],r['colour']) == part_key(piece['part_id'],piece['colour'])), None)
        if match:
            match['quantity'] += alloc['quantity']
            match['updated_at'] = utcnow()
        else:
            item = {'bag_number':alloc['bag_number'],'part_id':piece['part_id'],
                    'description':piece['description'],'colour':piece['colour'],
                    'quantity':alloc['quantity'],'updated_at':utcnow()}
            if set_num is None:
                item['category'] = category
            else:
                item['set_num'] = set_num
            rows.append(item)


def requirement_counts(d, num):
    requirements = {part_key(r['part_id'],r['colour']):r for r in d['set_requirements'] if r['set_num']==num}
    found = defaultdict(int)
    for r in d['set_pieces']:
        if r['set_num']==num:
            found[part_key(r['part_id'],r['colour'])] += r['quantity']
    return requirements, found


def allocation_preview(piece, d, active_set=''):
    """Matched required pieces reserved for active set; remainder goes to loose bags."""
    amount = piece['quantity']
    set_quantity = 0
    if active_set:
        if not any(s['set_num']==active_set for s in d['sets']):
            raise ValueError('Selected set is not tracked. Add it first.')
        requirements, found = requirement_counts(d, active_set)
        key = part_key(piece['part_id'],piece['colour'])
        if key in requirements:
            reserved=sum(r['quantity'] for r in d['set_pick_staging'] if
                         r['set_num']==active_set and part_key(r['part_id'],r['colour'])==key)
            set_quantity = min(amount, max(0, requirements[key]['required'] - found[key] - reserved))
    loose_quantity = amount - set_quantity
    bags = list(d['bags'])
    set_allocations = []
    if set_quantity:
        rows = [r for r in d['set_pieces'] if r['set_num']==active_set]
        set_allocations, created, _ = choose_bags(piece, set_quantity, rows, bags, 'Set: '+active_set)
        bags.extend(created)
    else:
        created = []
    loose_allocations = []
    known = False
    category = next((r['category'] for r in d['inventory'] if
                     part_key(r['part_id'],r['colour'])==part_key(piece['part_id'],piece['colour'])), piece['category'])
    if loose_quantity:
        loose_allocations, new_loose_bags, known = choose_bags(piece, loose_quantity, d['inventory'], bags, category)
        created.extend(new_loose_bags)
    return {'category':category, 'set_num':active_set, 'set_quantity':set_quantity,
            'loose_quantity':loose_quantity, 'set_allocations':set_allocations,
            'loose_allocations':loose_allocations,'new_bags':created,'already_known':known,
            'allocations':loose_allocations}  # compatibility for previous inventory flow


def preview_piece(data):
    piece = validate_piece(data)
    active_set = str(data.get('active_set','')).strip()
    with LOCK:
        return allocation_preview(piece, load_all(), active_set)


def add_piece(payload):
    piece = validate_piece(payload)
    active_set = str(payload.get('active_set','')).strip()
    with LOCK:
        d = load_all()
        plan = allocation_preview(piece, d, active_set)
        d['bags'].extend(plan['new_bags'])
        if plan['set_allocations']:
            requirements, _ = requirement_counts(d, active_set)
            canonical = requirements[part_key(piece['part_id'],piece['colour'])]
            set_piece = dict(piece, colour=canonical['colour'], description=canonical['description'])
            append_placements(d['set_pieces'], plan['set_allocations'], set_piece, 'Set: '+active_set, active_set)
        if plan['loose_allocations']:
            append_placements(d['inventory'],plan['loose_allocations'],piece,plan['category'])
        commit(d, 'bags','inventory','set_pieces')
        return {'result':plan,'summary':build_summary(d)}


def adjust_inventory(payload):
    try:
        bag = str(payload['bag_number'])
        part = str(payload['part_id'])
        colour = str(payload['colour'])
        raw = str(payload['quantity'])
        if not re.fullmatch(r'\d+',raw):
            raise ValueError()
        quantity = int(raw)
    except (ValueError,KeyError,TypeError):
        raise ValueError('Invalid inventory adjustment.')
    capacity = bag_capacity()
    if not 0 <= quantity <= capacity:
        raise ValueError(f'New quantity must be between 0 and {capacity}.')
    with LOCK:
        d = load_all()
        row = next((r for r in d['inventory'] if r['bag_number']==bag and r['part_id']==part and r['colour']==colour), None)
        if row is None:
            raise ValueError('Inventory row not found.')
        count = sum(r['quantity'] for r in d['inventory'] if r['bag_number']==bag)
        if count-row['quantity']+quantity > capacity:
            raise ValueError(f'Bag would exceed {capacity} pieces.')
        if quantity == 0:
            d['inventory'].remove(row)
        else:
            row['quantity'] = quantity
            row['updated_at'] = utcnow()
        commit(d,'inventory')
        return build_summary(d)


def build_summary(d):
    capacity = bag_capacity()
    counts = defaultdict(int)
    for row in d['inventory'] + d['set_pieces']:
        counts[row['bag_number']] += row['quantity']
    sets = []
    for s in d['sets']:
        requirements, found = requirement_counts(d,s['set_num'])
        target = sum(r['required'] for r in requirements.values())
        have = sum(min(r['required'], found[k]) for k,r in requirements.items())
        sets.append(dict(s, required=target, collected=have,
                         missing=target-have, percent=round(have/target*100,1) if target else 100))
    return {
        'inventory':sorted(d['inventory'],key=lambda r:(int(r['bag_number']),r['description'].casefold())),
        'bags':[{'bag_number':b['bag_number'],'category':b['category'],
                 'quantity':counts[b['bag_number']], 'remaining':capacity-counts[b['bag_number']]}
                for b in sorted(d['bags'],key=lambda b:int(b['bag_number']))],
        'sets':sets,'total_pieces':sum(counts.values()), 'loose_pieces':sum(r['quantity'] for r in d['inventory']),
        'set_pieces':sum(r['quantity'] for r in d['set_pieces']),
        'total_bags':len(d['bags']), 'different_parts':len({part_key(r['part_id'],r['colour']) for r in d['inventory']}),
        'capacity':capacity
    }


def get_set_detail(num):
    with LOCK:
        d = load_all()
        entry = next((s for s in d['sets'] if s['set_num']==num),None)
        if entry is None:
            raise ValueError('Set not tracked.')
        requirements, found = requirement_counts(d,num)
        loose = defaultdict(int)
        for r in d['inventory']:
            loose[part_key(r['part_id'],r['colour'])] += r['quantity']
        parts = []
        for key, req in sorted(requirements.items(),key=lambda item:(item[1]['description'],item[1]['colour'])):
            missing = max(0,req['required']-found[key])
            parts.append({**req,'collected':found[key], 'missing':missing,
                          'available_loose':loose[key], 'potential':min(missing,loose[key])})
        staged = {(r['source_bag'], part_key(r['part_id'],r['colour'])):r['quantity']
                  for r in d['set_pick_staging'] if r['set_num']==num}
        bag_groups = defaultdict(list)
        finished = {(r['set_num'],r['bag_number']) for r in d['set_bag_progress']}
        for row in d['inventory']:
            key = part_key(row['part_id'],row['colour'])
            if key not in requirements:
                continue
            req = requirements[key]
            amount = max(0,req['required']-found[key])
            if not amount:
                continue
            bag_groups[row['bag_number']].append({'part_id':row['part_id'],'colour':row['colour'],
                'description':req['description'],'image_url':req['image_url'],
                'available':row['quantity'],'suggested':min(amount,row['quantity']),
                'needed':amount,'set_num':num,
                'staged':staged.get((row['bag_number'],key),0)})
        for finished_set, finished_bag in finished:
            if finished_set==num and finished_bag not in bag_groups:
                bag_groups[finished_bag]=[]
        # Suggestions for MISSING set requirements: same part number, recorded
        # in a different colour. No suggestion changes counts or reserves stock.
        possible = []
        for req_key, req in requirements.items():
            missing = max(0, req['required'] - found[req_key])
            if not missing:
                continue
            for source in d['inventory']:
                if str(source['part_id']).strip().casefold() != str(req['part_id']).strip().casefold():
                    continue
                if part_key(source['part_id'], source['colour']) == req_key:
                    continue
                if source['quantity'] <= 0:
                    continue
                # Protect quantities already staged for collection into ANY set.
                staged_total = sum(x['quantity'] for x in d['set_pick_staging']
                                   if x['source_bag'] == source['bag_number'] and
                                   part_key(x['part_id'], x['colour']) ==
                                   part_key(source['part_id'], source['colour']))
                available = max(0, source['quantity'] - staged_total)
                if not available:
                    continue
                similar = likely_colour_confusion(source['colour'], req['colour'])
                possible.append({
                    'set_num': num, 'part_id': req['part_id'],
                    'description': req['description'], 'image_url': req['image_url'],
                    'required_colour': req['colour'], 'recorded_colour': source['colour'],
                    'source_bag': source['bag_number'], 'available': available,
                    'missing': missing, 'suggested': min(available, missing),
                    'similar_shade': similar,
                })
        possible.sort(key=lambda item: (not item['similar_shade'],
                      item['description'].casefold(), int(item['source_bag']),
                      item['recorded_colour'].casefold()))
        picking = []
        for bag, entries in sorted(bag_groups.items(), key=lambda r:int(r[0])):
            picking.append({'bag_number':bag,'done':(num,bag) in finished,'items':entries})
        in_set = [r for r in d['set_pieces'] if r['set_num']==num]
        return {'set':entry,'parts':parts,'picking':picking,'possible_matches':possible,'set_bags':sorted(set(r['bag_number'] for r in in_set),key=int),
                'stored_in_set':sum(r['quantity'] for r in in_set),
                'total_required':sum(r['required'] for r in requirements.values()),
                'total_collected':sum(min(r['required'],found[k]) for k,r in requirements.items()),
                'can_collect_now':sum(p['potential'] for p in parts)}


def parse_legacy_recognition(result):
    if not isinstance(result,dict):
        raise ValueError('Unexpected response from Brickognize.')
    items=[]
    for row in result.get('items',[]) if isinstance(result.get('items'),list) else []:
        if isinstance(row,dict) and row.get('id') and row.get('name'):
            items.append({'id':str(row['id']),'name':str(row['name']), 'score':row.get('score'),
                          'category':row.get('category') or '', 'img_url':row.get('img_url') or ''})
    colours=[]
    for row in result.get('colors',[]) if isinstance(result.get('colors'),list) else []:
        if isinstance(row,dict) and row.get('name'):
            colours.append({'id':str(row.get('id','')),'name':str(row['name']),'score':row.get('score')})
    return {'items':items,'colours':colours}


def recognise(image):
    boundary='----StudSiftBoundary'
    body=(f'--{boundary}\r\nContent-Disposition: form-data; name="query_image"; filename="brick.jpg"\r\n'
          'Content-Type: image/jpeg\r\n\r\n').encode()+image+f'\r\n--{boundary}--\r\n'.encode()
    req=urllib.request.Request(BRICKOGNIZE,data=body,headers={
        'Content-Type':'multipart/form-data; boundary='+boundary,
        'Accept':'application/json','User-Agent':'StudSift/0.1.0'})
    try:
        with urllib.request.urlopen(req,timeout=35) as response:
            obj=json.loads(response.read(2*1024*1024))
    except urllib.error.HTTPError as exc:
        raise ValueError('Brickognize request was rate limited.' if exc.code==429 else f'Brickognize returned HTTP {exc.code}.')
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        raise ValueError(f'Could not contact Brickognize: {exc}')
    return parse_legacy_recognition(obj)


def read_config():
    if not CONFIG_FILE.exists():
        return {}
    obj = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    if not isinstance(obj, dict):
        raise ValueError('Invalid data/config.json file.')
    return obj


def bag_capacity():
    # Existing installations default to 100 until a limit is saved in Settings.
    return int(read_config().get('bag_capacity', DEFAULT_CAPACITY))


def api_key():
    return str(read_config().get('rebrickable_api_key', '')).strip()


def settings():
    config = read_config()
    return {'rebrickable_connected': bool(config.get('rebrickable_api_key')),
            'bag_capacity': int(config.get('bag_capacity', DEFAULT_CAPACITY))}


def save_settings(payload):
    if 'bag_capacity' not in payload and 'api_key' not in payload:
        raise ValueError('No settings were provided.')
    with LOCK:
        config = read_config()  # Preserve the existing Rebrickable key and other settings.
        if 'api_key' in payload:
            key = str(payload['api_key']).strip()
            if not key or len(key)>200 or not re.fullmatch(r'[A-Za-z0-9_-]+', key):
                raise ValueError('Enter a valid Rebrickable API key.')
            config['rebrickable_api_key'] = key
        if 'bag_capacity' in payload:
            raw = payload['bag_capacity']
            if isinstance(raw, bool) or not re.fullmatch(r'[0-9]+', str(raw)):
                raise ValueError('Bag limit must be a whole number.')
            limit = int(raw)
            if not 1 <= limit <= MAX_CAPACITY:
                raise ValueError(f'Bag limit must be between 1 and {MAX_CAPACITY:,}.')
            # Do not silently make an existing bag invalid when reducing the limit.
            data = load_all()
            counts = defaultdict(int)
            for row in data['inventory'] + data['set_pieces']:
                counts[row['bag_number']] += row['quantity']
            too_full = sorted(((bag, count) for bag, count in counts.items() if count>limit),
                              key=lambda item: int(item[0]))
            if too_full:
                bag, count = too_full[0]
                raise ValueError(f'Bag {bag} already contains {count} pieces. '
                                 f'Choose a limit of at least {count}, or move pieces first.')
            config['bag_capacity'] = limit
        write_json(CONFIG_FILE, config)
        return settings()


def rb_get(path, params=None, key=None):
    key = key or api_key()
    if not key:
        raise ValueError('Add your Rebrickable API key in Settings first.')
    url = RB_BASE + path.lstrip('/')
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url,headers={'Authorization':'key '+key,'Accept':'application/json',
                                             'User-Agent':'StudSift/0.1.0'})
    try:
        with urllib.request.urlopen(req,timeout=35) as response:
            return json.loads(response.read(10*1024*1024))
    except urllib.error.HTTPError as exc:
        if exc.code==401:
            raise ValueError('Rebrickable rejected your API key. Check Settings.')
        if exc.code==404:
            raise ValueError('LEGO set not found on Rebrickable.')
        if exc.code==429:
            raise ValueError('Rebrickable rate limit reached; retry after a short break.')
        raise ValueError(f'Rebrickable returned HTTP {exc.code}.')
    except (urllib.error.URLError,TimeoutError,OSError) as exc:
        raise ValueError(f'Could not contact Rebrickable: {exc}')


def rb_pages(path, params=None):
    """Paginate using fixed API base and integer pages, not untrusted response links."""
    page=1
    results=[]
    while True:
        if page>1:
            time.sleep(1.05)  # documented average 1 request/s
        query=dict(params or {},page=page,page_size=1000)
        data=rb_get(path,query)
        if not isinstance(data,dict) or not isinstance(data.get('results'),list):
            raise ValueError('Unexpected Rebrickable inventory response.')
        results.extend(data['results'])
        if not data.get('next'):
            break
        page+=1
        if page>30:
            raise ValueError('Set inventory has too many pages.')
    return results


def import_set(payload):
    num=set_number(payload.get('set_num',''))
    with LOCK:
        if any(s['set_num']==num for s in load_all()['sets']):
            raise ValueError('Set already tracked.')
    detail=rb_get(f'sets/{num}/')
    # Includes minifigure constituent parts, not a standalone 'minifigure' abstract item.
    parts=rb_pages(f'sets/{num}/parts/',{'inc_minifig_parts':1,'inc_color_details':1})
    colours=rb_pages('colors/')
    colour_entries=[{'colour_id':str(c['id']),'name':str(c['name'])} for c in colours
                    if isinstance(c,dict) and c.get('id') is not None and c.get('name')]
    seen={}
    for entry in parts:
        if not isinstance(entry,dict) or entry.get('is_spare'):
            continue
        p=entry.get('part') or {}
        if not isinstance(p,dict) or not p.get('part_num'):
            continue
        col=entry.get('color') or {}
        if not isinstance(col,dict) or col.get('id') is None:
            continue
        amount=int(entry.get('quantity') or 0)
        if amount<=0:
            continue
        part=str(p['part_num'])
        colour=str(col.get('name') or next((c['name'] for c in colour_entries if c['colour_id']==str(col['id'])),'Unknown'))
        record={'set_num':num,'part_id':part,'description':str(p.get('name') or part),
                'colour':colour,'colour_id':str(col['id']),'required':amount,
                'image_url':str(p.get('part_img_url') or '')}
        pk=(part.casefold(),str(col['id']))
        if pk in seen:
            seen[pk]['required']+=amount
        else:
            seen[pk]=record
    if not seen:
        raise ValueError('No usable set parts returned. Nothing imported.')
    with LOCK:
        d=load_all()
        if any(s['set_num']==num for s in d['sets']):
            raise ValueError('Set already tracked.')
        d['sets'].append({'set_num':num,'name':str(detail.get('name') or num),
                          'image_url':str(detail.get('set_img_url') or ''),'created_at':utcnow()})
        d['set_requirements'].extend(seen.values())
        d['colours']=colour_entries
        commit(d,'sets','set_requirements','colours')
        return {'set_num':num,'name':str(detail.get('name') or num),
                'types':len(seen),'required':sum(x['required'] for x in seen.values())}



def correct_inventory_colour(payload):
    """User-verified colour correction IN THE SAME BAG (no quantity transfer)."""
    num = set_number(payload.get('set_num',''))
    bag = str(payload.get('bag_number','')).strip()
    part = str(payload.get('part_id','')).strip()
    recorded = str(payload.get('recorded_colour','')).strip()
    target = str(payload.get('required_colour','')).strip()
    raw = payload.get('quantity')
    if (isinstance(raw, bool) or not re.fullmatch(r'[0-9]+',str(raw)) or
            not 1 <= int(raw) <= bag_capacity()):
        raise ValueError('Enter a valid number of verified pieces to correct.')
    quantity = int(raw)
    with LOCK:
        d = load_all()
        reqs, found = requirement_counts(d, num)
        if not any(x['set_num']==num for x in d['sets']):
            raise ValueError('Set not tracked.')
        key = part_key(part,target)
        if key not in reqs:
            raise ValueError('Requested target part and colour are not required by this set.')
        if found[key] >= reqs[key]['required']:
            raise ValueError('That set part is already fully collected.')
        if colour_key(recorded)==colour_key(target):
            raise ValueError('These colours already match.')
        source = next((r for r in d['inventory'] if r['bag_number']==bag and
                      r['part_id']==part and r['colour']==recorded), None)
        if source is None:
            raise ValueError('Recorded part is no longer in that bag. Refresh the set.')
        staged = sum(x['quantity'] for x in d['set_pick_staging']
                     if x['source_bag']==bag and
                     part_key(x['part_id'],x['colour']) == part_key(part,recorded))
        if quantity > source['quantity']-staged:
            raise ValueError('Some pieces are already selected for a set. Unselect them first.')
        # Canonical target colour and description come from the imported set.
        canonical = reqs[key]
        dest = next((r for r in d['inventory'] if r is not source and
                     r['bag_number']==bag and
                     part_key(r['part_id'],r['colour'])==key), None)
        source['quantity'] -= quantity
        source['updated_at'] = utcnow()
        if not source['quantity']:
            d['inventory'].remove(source)
        if dest:
            dest['quantity'] += quantity
            dest['updated_at'] = utcnow()
        else:
            d['inventory'].append({'bag_number':bag,'part_id':part,
                                   'description':canonical['description'],
                                   'colour':canonical['colour'],
                                   'category':source['category'],
                                   'quantity':quantity,'updated_at':utcnow()})
        # Bag totals remain identical. No set collection is recorded yet.
        commit(d,'inventory')
        return {'corrected':quantity,'bag_number':bag,
                'old_colour':recorded,'new_colour':canonical['colour']}


def stage_pick(payload):
    """Persist the marked-as-removed items without deducting inventory until Finish bag."""
    num=set_number(payload.get('set_num',''))
    bag=str(payload.get('bag_number','')).strip()
    part=str(payload.get('part_id','')).strip()
    colour=str(payload.get('colour','')).strip()
    raw=payload.get('quantity')
    if isinstance(raw,bool) or not re.fullmatch(r'[0-9]+',str(raw)) or not 0<=int(raw)<=bag_capacity():
        raise ValueError(f'Select a quantity from 0 to {bag_capacity()}.')
    amount=int(raw)
    with LOCK:
        d=load_all()
        if not any(s['set_num']==num for s in d['sets']):
            raise ValueError('Set not tracked.')
        if any(r['set_num']==num and r['bag_number']==bag for r in d['set_bag_progress']):
            raise ValueError('Bag already completed. Reopen it first.')
        source=next((r for r in d['inventory'] if r['bag_number']==bag and
                     r['part_id']==part and r['colour']==colour),None)
        if source is None:
            raise ValueError('Source bag entry no longer exists.')
        if amount>source['quantity']:
            raise ValueError('Not enough pieces in that bag.')
        reqs,found=requirement_counts(d,num)
        key=part_key(part,colour)
        if key not in reqs:
            raise ValueError('Part and colour are not needed for this set.')
        other_staged=sum(r['quantity'] for r in d['set_pick_staging'] if
                         r['set_num']==num and part_key(r['part_id'],r['colour'])==key
                         and not (r['source_bag']==bag and r['part_id']==part and r['colour']==colour))
        need=max(0,reqs[key]['required']-found[key]-other_staged)
        if amount>need:
            raise ValueError(f'Only {need} additional pieces of this type are needed.')
        d['set_pick_staging']=[r for r in d['set_pick_staging'] if not
                               (r['set_num']==num and r['source_bag']==bag and
                                r['part_id']==part and r['colour']==colour)]
        if amount:
            d['set_pick_staging'].append({'set_num':num,'source_bag':bag,'part_id':part,
                                          'colour':colour,'quantity':amount,'updated_at':utcnow()})
        commit(d,'set_pick_staging')
        return {'staged':amount}


def finish_bag(payload, reopen=False):
    num=set_number(payload.get('set_num',''))
    bag=str(payload.get('bag_number','')).strip()
    with LOCK:
        d=load_all()
        if not any(s['set_num']==num for s in d['sets']):
            raise ValueError('Set not tracked.')
        if not any(b['bag_number']==bag and not b['category'].startswith('Set: ') for b in d['bags']):
            raise ValueError('Unknown loose bag.')
        progress=[r for r in d['set_bag_progress'] if r['set_num']==num and r['bag_number']==bag]
        if reopen:
            if not progress:
                raise ValueError('Bag is not marked complete.')
            d['set_bag_progress']=[r for r in d['set_bag_progress'] if r not in progress]
            commit(d,'set_bag_progress')
            return {'bag_number':bag,'done':False}
        if progress:
            raise ValueError('Bag already completed.')
        picks=[r for r in d['set_pick_staging'] if r['set_num']==num and r['source_bag']==bag]
        reqs,found=requirement_counts(d,num)
        for staged in picks:
            key=part_key(staged['part_id'],staged['colour'])
            source=next((r for r in d['inventory'] if r['bag_number']==bag and
                 r['part_id']==staged['part_id'] and r['colour']==staged['colour']),None)
            if not source or source['quantity']<staged['quantity']:
                raise ValueError('Source bag quantity has changed. Review the picked items.')
            if key not in reqs or staged['quantity']>reqs[key]['required']-found[key]:
                raise ValueError('Set requirements have changed. Review the picked items.')
            found[key]+=staged['quantity']
        allocations=[]
        for staged in picks:
            source=next(r for r in d['inventory'] if r['bag_number']==bag and
                        r['part_id']==staged['part_id'] and r['colour']==staged['colour'])
            req=reqs[part_key(source['part_id'],source['colour'])]
            piece={'part_id':source['part_id'],'colour':req['colour'],
                   'description':req['description']}
            placements,new_bags,_=choose_bags(piece,staged['quantity'],
                [r for r in d['set_pieces'] if r['set_num']==num],d['bags'],'Set: '+num)
            d['bags'].extend(new_bags)
            append_placements(d['set_pieces'],placements,piece,'Set: '+num,num)
            source['quantity']-=staged['quantity']
            if not source['quantity']:
                d['inventory'].remove(source)
            allocations.append({'part_id':piece['part_id'],'quantity':staged['quantity'],
                                'destinations':placements})
        d['set_pick_staging']=[r for r in d['set_pick_staging'] if not
                              (r['set_num']==num and r['source_bag']==bag)]
        d['set_bag_progress'].append({'set_num':num,'bag_number':bag,'completed_at':utcnow()})
        commit(d,'bags','inventory','set_pieces','set_pick_staging','set_bag_progress')
        return {'bag_number':bag,'done':True,'moved':allocations}


def served_javascript():
    """Serve the checked-in JavaScript (no runtime source rewriting)."""
    return (WEB / 'app.js').read_bytes()


class Handler(BaseHTTPRequestHandler):
    server_version='StudSift/0.1.0'

    def log_message(self,fmt,*args):
        print(f'[{self.log_date_time_string()}] {fmt % args}')

    def json_out(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route=urllib.parse.urlsplit(self.path)
        path=route.path
        try:
            if path=='/api/summary':
                with LOCK:
                    self.json_out(200,build_summary(load_all()))
            elif path=='/api/settings':
                self.json_out(200,settings())
            elif path=='/api/set':
                num=set_number(urllib.parse.parse_qs(route.query).get('set_num',[''])[0])
                self.json_out(200,get_set_detail(num))
            elif path=='/api/colours':
                with LOCK:
                    self.json_out(200,rows_for('colours'))
            elif path.startswith('/api/') and path[5:-4] in FILES and path.endswith('.csv'):
                name=path[5:-4]
                with LOCK:
                    recover_transaction()
                    raw=(DATA / FILES[name][0]).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type','text/csv; charset=utf-8')
                self.send_header('Content-Disposition',f'attachment; filename="{FILES[name][0]}"')
                self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store')
                self.end_headers()
                self.wfile.write(raw)
            else:
                assets={'/':'index.html','/index.html':'index.html','/app.js':'app.js','/styles.css':'styles.css'}
                if path not in assets:
                    return self.json_out(404,{'error':'Not found'})
                raw=served_javascript() if path=='/app.js' else (WEB/assets[path]).read_bytes()
                mime={'html':'text/html','js':'text/javascript','css':'text/css'}[assets[path].split('.')[-1]]
                self.send_response(200)
                self.send_header('Content-Type',mime+'; charset=utf-8')
                self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store')
                self.send_header('X-Content-Type-Options','nosniff')
                self.end_headers()
                self.wfile.write(raw)
        except ValueError as e:
            self.json_out(400,{'error':str(e)})
        except Exception:
            traceback.print_exc()
            self.json_out(500,{'error':'Server error; check the Python terminal.'})

    def do_POST(self):
        route=urllib.parse.urlsplit(self.path).path
        routes={'/api/recognise','/api/preview','/api/add','/api/adjust','/api/settings',
                '/api/import-set','/api/stage-pick','/api/finish-bag','/api/reopen-bag',
                '/api/correct-colour'}
        if route not in routes:
            return self.json_out(404,{'error':'Not found'})
        origin=self.headers.get('Origin')
        if origin:
            try:
                if urllib.parse.urlsplit(origin).netloc.casefold()!=self.headers.get('Host','').casefold():
                    return self.json_out(403,{'error':'Invalid request origin.'})
            except ValueError:
                return self.json_out(403,{'error':'Invalid request origin.'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size<=0 or size>MAX_REQUEST:
                raise ValueError('Request must be nonempty and under 10 MB.')
            raw=self.rfile.read(size)
            if route=='/api/recognise':
                if not raw.startswith(b'\xff\xd8\xff'):
                    raise ValueError('Webcam image must be JPEG.')
                return self.json_out(200,recognise(raw))
            payload=json.loads(raw)
            if not isinstance(payload,dict):
                raise ValueError('Invalid JSON object.')
            if route=='/api/preview': result=preview_piece(payload)
            elif route=='/api/add': result=add_piece(payload)
            elif route=='/api/adjust': result={'summary':adjust_inventory(payload)}
            elif route=='/api/settings': result=save_settings(payload)
            elif route=='/api/import-set': result=import_set(payload)
            elif route=='/api/correct-colour': result=correct_inventory_colour(payload)
            elif route=='/api/stage-pick': result=stage_pick(payload)
            elif route=='/api/finish-bag': result=finish_bag(payload)
            else: result=finish_bag(payload,True)
            self.json_out(200,result)
        except (ValueError,KeyError,json.JSONDecodeError) as e:
            self.json_out(400,{'error':str(e)})
        except Exception:
            traceback.print_exc()
            self.json_out(500,{'error':'Server error; check the Python terminal.'})


def main():
    initialise()
    port=int(os.environ.get('STUDSIFT_PORT', os.environ.get('LEGO_SORTER_PORT','8765')))
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'StudSift v0.1.0: http://localhost:{port}')
    print(f'CSV files: {DATA}')
    print('Local computer only. Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__=='__main__':
    main()
