"""Offline exact-evidence check. Supply the upstream chat-history history.py as argv[1]."""
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import closing
import json
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import memory
import minilm
from native_sources import parse_file

# Invented messages. Each target also appears under an English query.
CASES = [
    ('防滑链', 'snow chains for a truck on an icy road', '货车要在结冰的公路上行驶，出车前请安装防滑链。'),
    ('琴弦', 'tuning a piano and adjusting the pitch of its strings', '演出前请为钢琴调音，调整每根琴弦的音高。'),
    ('望远镜', 'a telescope for observing planets at night', '夜间观测行星时，请调整望远镜的焦距。'),
]
DISTRACTORS = ['花盆底部需要排水孔。', '晚餐选择清淡的南瓜汤。', '新书封面改用浅绿色。']

def skill_hit(script, folder, terms, message):
    cmd = [sys.executable, '-X', 'utf8', str(script), 'search', str(folder)]
    for term in terms:
        cmd += ['-e', term]
    result = subprocess.run(cmd, capture_output=True, encoding='utf8')
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise RuntimeError(result.stderr)
    hits = [json.loads(line) for line in result.stdout.splitlines()]
    if not hits:
        return False
    first = hits[0]
    original = Path(first['path']).read_text(encoding='utf8').splitlines()[first['line']-1]
    return json.loads(original)['message']['content'] == message and message in first['text']

def main():
    script = Path(sys.argv[1]).resolve(strict=True)
    with TemporaryDirectory() as tmp, closing(memory.connect(Path(tmp)/'demo.sqlite')) as db:
        folder = Path(tmp)/'fixture'
        folder.mkdir()
        for i, body in enumerate([case[2] for case in CASES] + DISTRACTORS):
            path = folder/f'demo-{i}.jsonl'
            row = dict(type='user', uuid='turn1', message=dict(role='user', content=body))
            path.write_text(json.dumps(row, ensure_ascii=False)+'\n', encoding='utf8')
            rows, *_ = parse_file('claude', path, {})
            memory.store_external(db, str(path), '1', f'claude:demo-{i}', '', '示例', i+1, rows)
        built = minilm.build(db)
        assert built.get('indexed') == len(CASES) + len(DISTRACTORS), built
        for i, (keyword, english, answer) in enumerate(CASES):
            for query in (keyword, english):
                result = memory.dispatch(dict(op='pair_search', query=query), db, None)
                assert not result['semantic_error'], result['semantic_error']
                first = result['candidates'][0]
                has_quote = False
                for field in ('hit', 'semantic'):
                    hit = first.get(field) or {}
                    if first['session'] == f'claude:demo-{i}' and hit.get('reference'):
                        body = memory.read_evidence(db, first['session'], hit['reference'])['text']
                        has_quote |= body == answer and body.startswith(hit['quote'],hit['offset'])
                # Simulate literal command specified by the simple prompt; no LLM answers are graded.
                raw = subprocess.run(['rg','--no-config','--no-ignore','-l','-i','-F','--',query,str(folder)],capture_output=True,encoding='utf8')
                if raw.returncode not in (0,1): raise RuntimeError(raw.stderr)
                paths = raw.stdout.splitlines()
                prompt_hit = bool(paths and json.loads(Path(paths[0]).read_text(encoding='utf8'))['message']['content'] == answer)
                print(query, dict(prompt_rg=prompt_hit, skill=skill_hit(script,folder,[query],answer),
                                  skill_with_gloss=skill_hit(script,folder,[query,keyword],answer), plugin=has_quote))

if __name__ == '__main__':
    main()

