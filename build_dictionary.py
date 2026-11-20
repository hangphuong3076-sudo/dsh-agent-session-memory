"""Build the offline CC-CEDICT lookup. python build_dictionary.py cedict.txt.gz dictionary.sqlite"""
import gzip
from pathlib import Path
import re
import sqlite3
import sys

if __name__ == '__main__':
    source, target = map(Path, sys.argv[1:])
    with gzip.open(source, 'rt', encoding='utf8') as lines, sqlite3.connect(target) as db:
        db.execute('CREATE TABLE lex(term TEXT, translation TEXT, PRIMARY KEY(term,translation)) WITHOUT ROWID')
        for line in lines:
            match = re.match(r'(\S+) (\S+) \[.*?\] /(.+)/$', line.strip())
            if not match:
                continue
            traditional, simplified, glosses = match.groups()
            for gloss in re.split(r'[/;]', glosses)[:6]:
                english = re.sub(r'\([^)]*\)', '', gloss).strip().casefold().removeprefix('to ')
                if not re.fullmatch(r"[a-z][a-z-]*(?: [a-z-]+){0,2}", english):
                    continue
                for han in {simplified, traditional}:
                    if len(han) >= 2:
                        db.executemany('INSERT OR IGNORE INTO lex VALUES(?,?)', [(han, english), (english, han)])

