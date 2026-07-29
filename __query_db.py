import sqlite3, json
db = sqlite3.connect('D:/code/cs-Solidarity/data/cs2-video/jobs.sqlite3')
db.row_factory = sqlite3.Row
cur = db.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('tables:', [r[0] for r in cur.fetchall()])
cur.execute("SELECT id, player_id, match_id, status, created_at FROM jobs ORDER BY created_at DESC LIMIT 5")
for r in cur.fetchall():
    print(r['id'][:16], r['match_id'], r['status'])
print('---')
cur.execute("SELECT id, player_id, match_id, data FROM jobs WHERE status='failed' ORDER BY created_at DESC LIMIT 1")
row = cur.fetchone()
if row:
    data = json.loads(row['data'])
    events = data.get('events') or []
    print('player_id:', row['player_id'])
    print('match_id:', row['match_id'])
    print('num events:', len(events))
    if events:
        rc = (events[0].get('raw_clip') or {})
        print('target_spec_slot:', rc.get('target_spec_slot'))
        players = ((events[0].get('match_meta') or {}).get('all_players') or [])
        print('all_players count:', len(players))
        for p in players:
            name = p.get('name') or ''
            print(f"  {name!r:25} steamid={p.get('steamid')} spec_slot={p.get('spec_slot')}")
